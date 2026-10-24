"""Spec 038, #588: the coordinator's view of every open upstream report across the product's
repos (upstream_state.py), and its rows in the watch, over a scripted forge, without gh or
the network"""

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.gate import Action, decide, parse_findings

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "github-issue-triage" / "scripts"
WATCH = ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
HOME = "acme/product"
API = "acme/api"
SDK = "other-org/sdk"
BOT = "shipmill-app[bot]"
QUESTION = "<!-- shipmill:needs-decision -->\n@amy which repo owns the index?"
CONFIG = f'[agents]\napp_id = 7\n\n[product]\nrepos = ["{API}", "{SDK}"]\n'
NOW = dt.datetime(2026, 10, 24, 12, 0, tzinfo=dt.UTC)


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def us() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))  # it imports chains and triage_state, as when run from its folder
    try:
        return load("upstream_state", SCRIPTS / "upstream_state.py")
    finally:
        sys.path.remove(str(SCRIPTS))


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("watch_state_upstream_rows", WATCH)


def said(body: str, who: str = "amy", association: str = "OWNER", bot: bool = False) -> dict[str, Any]:
    author = {"__typename": "Bot" if bot else "User", "login": who.removesuffix("[bot]") if bot else who}
    return {"body": body, "author": author, "authorAssociation": association}


class Forge:
    """A scripted GitHub behind each repo's runner: its issues, and every call, recorded as
    (the repo whose runner made it, the query's kind, its variables)"""

    def __init__(self, us: ModuleType) -> None:
        self.us = us
        self.issues: dict[tuple[str, str, int], dict[str, Any]] = {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.broken: str | None = None  # a repo whose runner answers every query with an error

    def add(
        self,
        ref: str,
        *comments: dict[str, Any],
        labels: tuple[str, ...] = ("upstream",),
        body: str = "",
        author: str = "amy",
        association: str = "OWNER",
        bot: bool = False,
        subs: tuple[str, ...] = (),
        state: str = "OPEN",
        reason: str | None = None,
        kind: str = "Issue",
        older: tuple[list[dict[str, Any]], ...] = (),
    ) -> None:
        """older: pages of comments before ``comments``, oldest first, read by paging back"""
        repo, _, number = ref.partition("#")
        owner, _, name = repo.partition("/")
        self.issues[(owner.lower(), name.lower(), int(number))] = {
            "repo": repo,
            "number": int(number),
            "author": {
                "__typename": "Bot" if bot else "User",
                "login": author.removesuffix("[bot]") if bot else author,
            },
            "authorAssociation": association,
            "labels": labels,
            "body": body,
            "comments": list(comments),
            "subs": subs,
            "state": state,
            "stateReason": reason,
            "kind": kind,
            "older": list(older),
        }

    def get(self, owner: str, name: str, number: int) -> dict[str, Any]:
        return self.issues[(owner.lower(), name.lower(), number)]

    def node(self, ref: str) -> dict[str, Any]:
        repo, _, number = ref.partition("#")
        owner, _, name = repo.partition("/")
        item = self.get(owner, name, int(number))
        return {
            "number": item["number"],
            "state": item["state"],
            "stateReason": item["stateReason"],
            "closedAt": None if item["state"] == "OPEN" else "2026-10-20T10:00:00Z",
            "repository": {"nameWithOwner": item["repo"]},
        }

    def readers(self, repo: str) -> Any:
        def run(query: str, variables: dict[str, Any]) -> dict[str, Any]:
            return self.answer(repo, query, variables)

        return run

    def answer(self, reader: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        us = self.us
        kind = {us.REPORTS: "reports", us.REPORT: "report", us.COMMENTS: "comments"}.get(query, "children")
        self.calls.append((reader, kind, dict(variables)))
        if self.broken is not None and reader.lower() == self.broken.lower():
            return {"errors": [{"type": "FORBIDDEN", "message": "Resource not accessible by integration"}]}
        if kind == "children":
            data: dict[str, Any] = {}
            errors = []
            for key in variables:
                if key.startswith("o"):
                    i = key[1:]
                    wanted = (variables[f"o{i}"].lower(), variables[f"n{i}"].lower(), variables[f"k{i}"])
                    if wanted not in self.issues:
                        data[f"c{i}"] = {"issueOrPullRequest": None}
                        errors.append({"type": "NOT_FOUND", "message": f"Could not resolve to an issue {wanted[2]}"})
                        continue
                    item = self.issues[wanted]
                    node = {"__typename": item["kind"], "state": item["state"]}
                    if item["kind"] == "Issue":
                        node["stateReason"] = item["stateReason"]
                    data[f"c{i}"] = {"issueOrPullRequest": node}
            return {"data": data, **({"errors": errors} if errors else {})}
        owner, name = variables["owner"], variables["name"]
        if kind == "reports":
            nodes = [
                {"number": i["number"], "author": i["author"], "authorAssociation": i["authorAssociation"]}
                for (o, n, _), i in sorted(self.issues.items())
                if (o, n) == (owner.lower(), name.lower()) and "upstream" in i["labels"] and i["state"] == "OPEN"
            ]
            page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}
            return {"data": {"repository": {"issues": page}}}
        item = self.get(owner, name, variables["number"])
        older = item["older"]
        if kind == "comments":  # page back: cursor pK is the K-th page before the newest
            k = int(variables["cursor"].removeprefix("p"))
            more = k + 1 < len(older)
            page = {
                "pageInfo": {"hasPreviousPage": more, "startCursor": f"p{k + 1}" if more else None},
                "nodes": older[-(k + 1)],
            }
            return {"data": {"repository": {"issue": {"comments": page}}}}
        issue = {
            "number": item["number"],
            "body": item["body"],
            "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": n} for n in item["labels"]]},
            "comments": {
                "pageInfo": {"hasPreviousPage": bool(older), "startCursor": "p0" if older else None},
                "nodes": item["comments"],
            },
            "subIssues": {"pageInfo": {"hasNextPage": False}, "nodes": [self.node(s) for s in item["subs"]]},
        }
        return {"data": {"repository": {"issue": issue}}}

    def read(self, ref: str) -> list[tuple[str, str]]:
        """The (reader, kind) of each call that read ref's own fields or named it as a child"""
        repo, _, number = ref.partition("#")
        owner, _, name = repo.partition("/")
        found = []
        for reader, kind, variables in self.calls:
            if kind in ("report", "comments") and (variables["owner"], variables["name"], variables["number"]) == (
                owner,
                name,
                int(number),
            ):
                found.append((reader, kind))
            if kind == "children":
                for key, value in variables.items():
                    i = key[1:]
                    if key.startswith("o") and (value, variables[f"n{i}"], variables[f"k{i}"]) == (
                        owner,
                        name,
                        int(number),
                    ):
                        found.append((reader, kind))
        return found


def checkout(tmp_path: Path, config: str = CONFIG) -> Path:
    (tmp_path / ".git").mkdir(parents=True)
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "shipmill.toml").write_text(config, encoding="utf-8")
    return tmp_path


def run_state(
    us: ModuleType, forge: Forge, folder: Path, capsys: pytest.CaptureFixture[str], *args: str
) -> tuple[int, list[dict[str, str]]]:
    code = us.main([HOME, "--json", *args], forge.readers, folder)
    return code, [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def states(rows: list[dict[str, str]]) -> dict[str, tuple[str, str]]:
    return {r["ref"]: (r["state"], r["note"]) for r in rows}


# -- S-038-18 ------------------------------------------------------------------------------


def product_forge(us: ModuleType) -> Forge:
    forge = Forge(us)
    forge.add(f"{HOME}#1")  # no children, no question
    forge.add(f"{HOME}#2", said(QUESTION, BOT, "NONE", bot=True), labels=("upstream", "needs-decision"))
    forge.add(
        f"{API}#3",
        said(QUESTION, BOT, "NONE", bot=True),
        said("acme/api owns it"),
        labels=("upstream", "needs-decision"),
        author=BOT,
        association="NONE",
        bot=True,
    )
    forge.add(f"{API}#4", subs=(f"{API}#40", f"{SDK}#41"))
    forge.add(f"{API}#40", labels=(), state="CLOSED", reason="COMPLETED")
    forge.add(f"{SDK}#41", labels=())
    forge.add(f"{SDK}#5", subs=(f"{SDK}#50",), body=f"Depends on {API}#51\n")
    forge.add(f"{SDK}#50", labels=(), state="CLOSED", reason="COMPLETED")
    forge.add(f"{API}#51", labels=(), state="CLOSED", reason="COMPLETED")
    forge.add(f"{SDK}#6", subs=(f"{SDK}#60", f"{SDK}#61"))
    forge.add(f"{SDK}#60", labels=(), state="CLOSED", reason="COMPLETED")
    forge.add(f"{SDK}#61", labels=(), state="CLOSED", reason="NOT_PLANNED")
    return forge


def test_s038_18_one_line_per_open_report_of_the_home_and_every_listed_repo(
    us: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = product_forge(us)
    code, rows = run_state(us, forge, checkout(tmp_path), capsys, "--bot-login", BOT)
    assert code == 1
    assert [r["ref"] for r in rows] == [f"{HOME}#1", f"{HOME}#2", f"{API}#3", f"{API}#4", f"{SDK}#5", f"{SDK}#6"]
    assert states(rows) == {
        f"{HOME}#1": ("ROUTE_DUE", "no children"),
        f"{HOME}#2": ("ASKED", "waits on a reply"),
        f"{API}#3": ("ANSWERED", "answered by @amy"),
        f"{API}#4": ("ROUTED", f"children 1/2 closed {API}#40:closed {SDK}#41:open"),
        f"{SDK}#5": ("CLOSE_DUE", f"completed, children 2/2 closed {API}#51:closed {SDK}#50:closed"),
        f"{SDK}#6": ("CLOSE_DUE", f"not_planned, children 2/2 closed {SDK}#60:closed {SDK}#61:not_planned"),
    }
    # each repo is read through its own runner: the home repo's, and each listed repo's
    assert {
        (reader, variables["owner"] + "/" + variables["name"])
        for reader, kind, variables in forge.calls
        if kind == "reports"
    } == {
        (HOME, HOME),
        (API, API),
        (SDK, SDK),
    }


def test_s038_18_the_text_lines_and_exit_0_when_nothing_is_due(
    us: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(us)
    forge.add(f"{HOME}#2", said(QUESTION, "amy"), labels=("upstream", "needs-decision"))
    forge.add(f"{API}#4", subs=(f"{API}#40",))
    forge.add(f"{API}#40", labels=())
    forge.add(f"{API}#9", labels=("bug",))  # no upstream label: not a report
    forge.add(f"{SDK}#7", state="CLOSED", reason="COMPLETED")  # a closed report: not read
    assert us.main([HOME], forge.readers, checkout(tmp_path)) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"{HOME}#2 ASKED waits on a reply",
        f"{API}#4 ROUTED children 0/1 closed {API}#40:open",
    ]


def test_s038_18_comments_are_paged_back_to_the_question(
    us: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(us)
    pages = ([said(QUESTION, BOT, "NONE", bot=True)], [said("+1", "eve", "NONE")])
    forge.add(f"{HOME}#2", said("acme/api owns it"), labels=("upstream", "needs-decision"), older=pages)
    code, rows = run_state(us, forge, checkout(tmp_path), capsys, "--bot-login", BOT)
    assert (code, states(rows)) == (1, {f"{HOME}#2": ("ANSWERED", "answered by @amy")})
    assert [kind for _, kind, _ in forge.calls].count("comments") == 2


def test_s038_18_a_labelled_report_with_no_question_waits_too(
    us: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(us)
    forge.add(f"{HOME}#2", labels=("upstream", "needs-decision"), subs=(f"{API}#40",))
    forge.add(f"{API}#40", labels=(), state="CLOSED", reason="COMPLETED")
    code, rows = run_state(us, forge, checkout(tmp_path), capsys)
    assert (code, states(rows)) == (0, {f"{HOME}#2": ("ASKED", "labelled, no question")})


def test_s038_18_a_pull_request_closed_unmerged_closes_the_report_as_not_planned(
    us: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(us)
    forge.add(f"{HOME}#1", body=f"Depends on {API}#8\nDepends on {API}#9\n")
    forge.add(f"{API}#8", labels=(), state="MERGED", kind="PullRequest")
    forge.add(f"{API}#9", labels=(), state="CLOSED", kind="PullRequest")
    code, rows = run_state(us, forge, checkout(tmp_path), capsys)
    assert (code, states(rows)) == (
        1,
        {f"{HOME}#1": ("CLOSE_DUE", f"not_planned, children 2/2 closed {API}#8:merged {API}#9:closed_unmerged")},
    )


@pytest.mark.parametrize("broken", [HOME, API, SDK])
def test_s038_18_a_gh_failure_exits_2_with_no_partial_report(
    us: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], broken: str
) -> None:
    forge = product_forge(us)
    forge.broken = broken
    with pytest.raises(SystemExit) as stopped:
        us.main([HOME, "--json"], forge.readers, checkout(tmp_path))
    assert stopped.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "Resource not accessible by integration" in err


def test_s038_18_a_child_that_cant_be_read_exits_2(
    us: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(us)
    forge.add(f"{HOME}#1")
    forge.add(f"{HOME}#2", body=f"Depends on {SDK}#99\n")  # no such issue in the forge
    with pytest.raises(SystemExit) as stopped:
        us.main([HOME], forge.readers, checkout(tmp_path))
    assert stopped.value.code == 2
    out, err = capsys.readouterr()
    assert out == "" and "Could not resolve to an issue 99" in err


@pytest.mark.parametrize(
    ("config", "said"),
    [
        ("[agents]\napp_id = 7\n", "has no [product] repos"),
        ('[product]\nhome = "acme/product"\n', "has no [product] repos"),
        (f'[product]\nrepos = ["{API}", "{HOME}"]\n', "lists the home repo"),
        ('[product]\nrepos = ["acme"]\n', "each repo is owner/name"),
        ("[product]\nrepos = []\n", "must list at least one repo"),
        (f'[product]\nhome = "{HOME}"\nrepos = ["{API}"]\n', "can't both be set"),
        (f'[product]\nrepos = ["{API}", "ACME/api"]\n', "twice"),
    ],
)
def test_s038_18_a_config_it_refuses_exits_2_before_any_read(
    us: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str, said: str
) -> None:
    forge = product_forge(us)
    with pytest.raises(SystemExit) as stopped:
        us.main([HOME], forge.readers, checkout(tmp_path, config))
    assert stopped.value.code == 2
    assert said in capsys.readouterr().err
    assert forge.calls == []


def test_s038_18_the_listed_repos_are_read_with_the_product_token(us: ModuleType, tmp_path: Path) -> None:
    """The home repo through the session's gh, each listed repo through `shipmill gh --product`
    as the plugin's pinned release, run in the checkout"""
    top = checkout(tmp_path)
    ran: list[list[str]] = []

    def execute(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"data": {}}), "")

    readers = us.default_readers(HOME, top, execute)
    for repo in (HOME, API):
        readers(repo)("query { x }", {"owner": "o"})
    version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    assert ran[0][:3] == ["gh", "api", "graphql"]
    assert ran[1][:8] == ["uvx", f"shipmill=={version}", "--repo", str(top), "gh", "--product", API, "api"]
    assert ran[1][8] == "graphql"


# -- S-038-19 ------------------------------------------------------------------------------


@pytest.mark.parametrize("association", ["NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER"])
def test_s038_19_an_untrusted_report_reads_untrusted_and_nothing_of_it_is_read(
    us: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], association: str
) -> None:
    forge = Forge(us)
    # it would read CLOSE_DUE, ANSWERED, or ROUTE_DUE if its fields were read
    forge.add(
        f"{API}#3",
        said(QUESTION, BOT, "NONE", bot=True),
        said("acme/api owns it"),
        labels=("upstream", "needs-decision"),
        body=f"Depends on {SDK}#30\nStands in for {SDK}#31\n",
        author="eve",
        association=association,
        subs=(f"{SDK}#30",),
    )
    forge.add(f"{SDK}#30", labels=(), state="CLOSED", reason="COMPLETED")
    forge.add(f"{HOME}#1", author="eve", association=association)
    code, rows = run_state(us, forge, checkout(tmp_path), capsys, "--bot-login", BOT)
    assert code == 0
    assert states(rows) == {
        f"{HOME}#1": ("UNTRUSTED", f"opened by @eve ({association.lower()})"),
        f"{API}#3": ("UNTRUSTED", f"opened by @eve ({association.lower()})"),
    }
    # only the reports' list was read: no body, label, comment, or child of either
    assert {kind for _, kind, _ in forge.calls} == {"reports"}
    assert forge.read(f"{API}#3") == [] and forge.read(f"{SDK}#30") == [] and forge.read(f"{HOME}#1") == []


def test_s038_19_the_bot_login_and_trusted_authors_are_read(
    us: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(us)
    forge.add(f"{HOME}#1", author=BOT, association="NONE", bot=True)
    forge.add(f"{API}#2", author="max", association="MEMBER")
    forge.add(f"{SDK}#3", author="cat", association="COLLABORATOR")
    code, rows = run_state(us, forge, checkout(tmp_path), capsys, "--bot-login", BOT)
    assert code == 1
    assert {r["state"] for r in rows} == {"ROUTE_DUE"}
    # without --bot-login the bot's own report is no one's it trusts
    code, rows = run_state(us, forge, checkout(tmp_path / "again"), capsys)
    assert states(rows)[f"{HOME}#1"] == ("UNTRUSTED", "opened by @shipmill-app[bot] (none)")


def test_s038_19_an_outsiders_comment_never_answers_and_their_marker_never_asks(
    us: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(us)
    labels = ("upstream", "needs-decision")
    forge.add(f"{HOME}#1", said(QUESTION, BOT, "NONE", bot=True), said("acme/api!", "eve", "NONE"), labels=labels)
    forge.add(
        f"{HOME}#2",
        said(QUESTION, BOT, "NONE", bot=True),
        said("acme/api"),
        said(QUESTION, "eve", "NONE"),
        labels=labels,
    )
    code, rows = run_state(us, forge, checkout(tmp_path), capsys, "--bot-login", BOT)
    assert states(rows) == {
        f"{HOME}#1": ("ASKED", "waits on a reply"),
        f"{HOME}#2": ("ANSWERED", "answered by @amy"),
    }
    assert code == 1


# -- S-038-20 ------------------------------------------------------------------------------


def test_s038_20_children_are_sub_issues_and_depends_on_lines_each_once_across_repos(
    us: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(us)
    body = f"Depends on {API}#10\nDepends on ACME/API#11 and {SDK}#12\n- Depends on #13\n"
    forge.add(f"{HOME}#1", body=body, subs=(f"{API}#11",))
    forge.add(f"{API}#10", labels=(), state="CLOSED", reason="COMPLETED")  # a link the forge refused: text only
    forge.add(f"{API}#11", labels=())
    forge.add(f"{SDK}#12", labels=(), state="CLOSED", reason="COMPLETED")
    forge.add(f"{HOME}#13", labels=(), state="CLOSED", reason="COMPLETED")
    code, rows = run_state(us, forge, checkout(tmp_path), capsys)
    assert (code, states(rows)) == (
        0,
        {
            f"{HOME}#1": (
                "ROUTED",
                f"children 3/4 closed {API}#10:closed {API}#11:open {HOME}#13:closed {SDK}#12:closed",
            )
        },
    )
    # the sub-issue named by a Depends on line too is read once, from the sub-issues; each
    # other child through its own repo's runner
    assert forge.read(f"{API}#11") == [] and forge.read(f"{API}#10") == [(API, "children")]
    assert forge.read(f"{SDK}#12") == [(SDK, "children")] and forge.read(f"{HOME}#13") == [(HOME, "children")]


def test_s038_20_a_depends_on_line_alone_makes_a_child(
    us: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(us)
    forge.add(f"{SDK}#5", body=f"Depends on {API}#10\n")
    forge.add(f"{API}#10", labels=(), state="CLOSED", reason="NOT_PLANNED")
    code, rows = run_state(us, forge, checkout(tmp_path), capsys)
    assert (code, states(rows)) == (
        1,
        {f"{SDK}#5": ("CLOSE_DUE", f"not_planned, children 1/1 closed {API}#10:not_planned")},
    )


def test_s038_20_a_stand_in_line_puts_link_in_the_route_due_note(
    us: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(us)
    forge.add(f"{API}#2", body=f"We need a bulk endpoint.\n\nStands in for {SDK}#31\n")
    forge.add(f"{API}#3", body=f"- stands in for: https://github.com/{SDK}/issues/32\n")
    forge.add(f"{API}#4", body=f"Mentions {SDK}#33, which it stands in for only mid-line\n")
    code, rows = run_state(us, forge, checkout(tmp_path), capsys)
    assert (code, states(rows)) == (
        1,
        {
            f"{API}#2": ("ROUTE_DUE", f"link {SDK}#31"),
            f"{API}#3": ("ROUTE_DUE", f"link {SDK}#32"),
            f"{API}#4": ("ROUTE_DUE", "no children"),
        },
    )
    # once linked, the stand-in's issue is a child like any other
    forge.add(f"{SDK}#31", labels=())
    forge.issues[("acme", "api", 2)]["subs"] = (f"{SDK}#31",)
    code, rows = run_state(us, forge, checkout(tmp_path / "again"), capsys)
    assert states(rows)[f"{API}#2"] == ("ROUTED", f"children 0/1 closed {SDK}#31:open")


# -- S-038-21 ------------------------------------------------------------------------------


def upstream_line(ref: str, state: str, note: str = "a note from a report's text") -> str:
    return json.dumps({"ref": ref, "state": state, "note": note})


def spawned(code: int, out: str = "", err: str = "") -> Any:
    calls: list[tuple[list[str], Path | None]] = []

    def execute(cmd: list[str], cwd: Path | None, env: dict[str, str] | None) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, cwd))
        return subprocess.CompletedProcess(cmd, code, out, err)

    return execute, calls


def test_s038_21_the_watch_reports_the_due_asked_and_untrusted_reports(ws: ModuleType, tmp_path: Path) -> None:
    lines = [
        upstream_line(f"{HOME}#1", "ROUTE_DUE"),
        upstream_line(f"{HOME}#2", "ASKED"),
        upstream_line(f"{API}#3", "ANSWERED"),
        upstream_line(f"{API}#4", "ROUTED"),
        upstream_line(f"{SDK}#5", "CLOSE_DUE"),
        upstream_line(f"{SDK}#6", "UNTRUSTED"),
        upstream_line(f"{SDK}#7", "ASKED"),
    ]
    execute, calls = spawned(1, "\n".join(lines) + "\n")
    rows = ws.coordinator_rows(CONFIG, tmp_path / "shipmill.toml", HOME, tmp_path, BOT, execute)
    assert [(r.state, r.subject, r.detail) for r in rows] == [
        ("UPSTREAM_DUE", HOME, f"ROUTE_DUE {HOME}#1; ANSWERED {API}#3; CLOSE_DUE {SDK}#5"),
        ("UPSTREAM_ASKED", HOME, f"{HOME}#2 {SDK}#7"),
        ("UPSTREAM_UNTRUSTED", HOME, f"{SDK}#6"),
    ]
    assert [r.json()["agent"] for r in rows] == [True, False, False]
    assert "UPSTREAM_DUE" in ws.AGENT and "UPSTREAM_ASKED" in ws.ACTION and "UPSTREAM_ASKED" not in ws.AGENT
    assert "UPSTREAM_UNTRUSTED" not in ws.ACTION and "UPSTREAM_UNTRUSTED" not in ws.AGENT
    assert all("a note" not in (r.detail + (r.fix or "")) for r in rows)  # refs only, never a report's text (D-16)
    # one run, in the checkout, with the --bot-login
    assert calls == [([sys.executable, str(ws.UPSTREAM_STATE), HOME, "--json", "--bot-login", BOT], tmp_path)]


def test_s038_21_the_gate_starts_a_session_for_due_reports_only(ws: ModuleType, tmp_path: Path) -> None:
    def decision(*lines: str) -> Action:
        execute, _ = spawned(1 if any("_DUE" in line or "ANSWERED" in line for line in lines) else 0, "\n".join(lines))
        rows = ws.coordinator_rows(CONFIG, tmp_path / "shipmill.toml", HOME, tmp_path, BOT, execute)
        printed = "\n".join(json.dumps(r.json(), sort_keys=True) for r in rows)
        return decide(parse_findings(printed), [], None, NOW, dt.timedelta(hours=1)).action

    assert decision(upstream_line(f"{API}#3", "ROUTE_DUE")) == Action.LAUNCH
    assert decision(upstream_line(f"{API}#3", "CLOSE_DUE")) == Action.LAUNCH
    assert decision(upstream_line(f"{API}#3", "ASKED"), upstream_line(f"{API}#4", "UNTRUSTED")) == Action.QUIET
    assert decision(upstream_line(f"{API}#4", "ROUTED")) == Action.QUIET


@pytest.mark.parametrize(
    ("code", "out", "err"),
    [
        (2, "", "error: reading the upstream reports of acme/api: Resource not accessible by integration\n"),
        (2, "", "shipmill: gh --product acme/api needs [agents] app_id\nerror: something\n"),
        (1, "not json\n", ""),
        (0, upstream_line(f"{API}#3", "ROUTE_DUE"), ""),  # an exit code its lines don't explain
        (1, upstream_line(f"{API}#3", "ASKED"), ""),
        (0, upstream_line("acme/api#x", "ASKED"), ""),
        (0, upstream_line(f"{API}#3", "WHATEVER"), ""),
        (3, "", ""),
    ],
)
def test_s038_21_a_failing_run_is_one_unreadable_row(
    ws: ModuleType, tmp_path: Path, code: int, out: str, err: str
) -> None:
    execute, _ = spawned(code, out, err)
    rows = ws.coordinator_rows(CONFIG, tmp_path / "shipmill.toml", HOME, tmp_path, BOT, execute)
    assert [(r.state, r.subject) for r in rows] == [("UPSTREAM_UNREADABLE", HOME)]
    row = rows[0]
    assert row.detail.startswith("error:")
    assert row.fix == f"see why: uv run --directory {tmp_path} --no-project python {ws.UPSTREAM_STATE} {HOME}"
    assert row.json()["agent"] is False and "UPSTREAM_UNREADABLE" in ws.ACTION


@pytest.mark.parametrize(
    "config",
    [
        None,  # no config at all
        "[agents]\napp_id = 7\n",  # in no product
        '[product]\nhome = "acme/product"\n',  # a component
    ],
)
def test_s038_21_without_product_repos_no_upstream_state_runs(
    ws: ModuleType, tmp_path: Path, config: str | None
) -> None:
    execute, calls = spawned(1, upstream_line(f"{API}#3", "ROUTE_DUE"))
    policy = None if config is None else tmp_path / "shipmill.toml"
    assert ws.coordinator_rows(config, policy, "o/r", tmp_path, BOT, execute) == []
    assert calls == []


@pytest.mark.parametrize(
    "text",
    [
        CONFIG,
        f"[product]\nrepos = [\"{API}\", '{SDK}',]\n",
        f'[product]\nrepos = ["{API}"] # one\n[agents]\napp_id = 7\n',
    ],
)
def test_s038_21_product_repos_reads_the_same_on_310(ws: ModuleType, tmp_path: Path, text: str) -> None:
    policy = tmp_path / "shipmill.toml"
    assert ws.product_repos(text, policy) == ws.product_repos_310(text, policy)
    assert ws.product_repos(text, policy) is not None


@pytest.mark.parametrize(
    "text",
    [
        "[product]\nrepos = []\n",
        '[product]\nrepos = ["acme"]\n',
        '[product]\nrepos = "acme/api"\n',
        f'[product]\nrepos = ["{API}", "Acme/API"]\n',
        "[product]\nrepos = [7]\n",
    ],
)
def test_s038_21_a_malformed_repos_is_refused(ws: ModuleType, tmp_path: Path, text: str) -> None:
    with pytest.raises(ws.Refused):
        ws.product_repos(text, tmp_path / "shipmill.toml")
    with pytest.raises(ws.Refused):
        ws.product_repos_310(text, tmp_path / "shipmill.toml")


@pytest.mark.parametrize(
    "text",
    [
        f'[product]\nrepos = ["{API}",\n',  # never closes
        f'[product]\nrepos = [\n  "{API}",\n]\n',  # an array on several lines: 3.11+ reads it
        f'[product]\nrepos = ["{API}"] x\n',
        f'[product]\nrepos.x = ["{API}"]\n',
        f'[product]\nrepos = ["{API}"]\nrepos = ["{SDK}"]\n',
    ],
)
def test_s038_21_the_310_reader_refuses_repos_it_cant_read(ws: ModuleType, tmp_path: Path, text: str) -> None:
    with pytest.raises(ws.Refused, match=r"can't read \[product\]"):
        ws.product_repos_310(text, tmp_path / "shipmill.toml")
