"""github-ship-watch's maintainer queue (spec S-069): fleet.py queue, from a fake gh"""

import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "github-ship-watch" / "scripts"
NOW = dt.datetime(2026, 11, 19, 12, 0, tzinfo=dt.timezone.utc)  # noqa: UP017 (runs under 3.10 too)
MARKER = "<!-- shipmill:needs-decision -->"
BOT = "shipmill-app[bot]"


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"queue_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fl() -> ModuleType:
    return load_script("fleet")


def proc(code: int, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, out, err)


def ago(**delta: int) -> str:
    return (NOW - dt.timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def comment(body: str, author: str = "amy", association: str = "OWNER", at: str = "") -> dict[str, Any]:
    bot = author.endswith("[bot]")
    who = {"__typename": "Bot" if bot else "User", "login": author.removesuffix("[bot]")}
    return {"author": who, "authorAssociation": association, "body": body, "createdAt": at or ago(days=9)}


def item(
    number: int,
    title: str,
    *,
    pr: bool = False,
    author: str = "amy",
    association: str = "OWNER",
    labels: Sequence[str] = (),
    comments: Sequence[dict[str, Any]] = (),
    labelled: Sequence[tuple[str, str]] = (),
    created: str = "",
    state: str = "OPEN",
    closed: str | None = None,
) -> dict[str, Any]:
    bot = author.endswith("[bot]")
    return {
        "__typename": "PullRequest" if pr else "Issue",
        "number": number,
        "title": title,
        "url": f"https://github.com/o/r/{'pull' if pr else 'issues'}/{number}",
        "state": state,
        "createdAt": created or ago(days=30),
        "closedAt": closed,
        "body": "",
        "authorAssociation": association,
        "author": {"__typename": "Bot" if bot else "User", "login": author.removesuffix("[bot]")},
        "labels": {"nodes": [{"name": n} for n in labels]},
        "comments": {"nodes": list(comments)},
        "timelineItems": {"nodes": [{"createdAt": at, "label": {"name": n}} for n, at in labelled]},
    }


def watch_row(state: str, subject: str, detail: str) -> dict[str, Any]:
    return {"state": state, "subject": subject, "detail": detail, "agent": False, "fix": None}


def asked(number: int, title: str, at: str, **kw: Any) -> dict[str, Any]:
    """An item whose bot question has no reply"""
    question = comment(f"{MARKER}\nWhich one?", BOT, "NONE", at)
    return item(number, title, labels=["needs-decision"], comments=[question], **kw)


@dataclass
class FakeGh:
    """Answers the clone, watch_state.py, triage_state.py, intake_state.py, gh api user, and gh
    api graphql, recording each call and the folder it ran in. The clone of a repo not in
    undirected holds docs/product.md; intake_state.py --plans fails without it, as
    `shipmill product show` does"""

    watch: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    triage: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    intake: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    github: dict[str, dict[int, dict[str, Any]]] = field(default_factory=dict)
    failing: dict[str, tuple[str, str]] = field(default_factory=dict)  # repo: (step, stderr)
    calls: list[list[str]] = field(default_factory=list)
    folders: dict[tuple[str, str], Path | None] = field(default_factory=dict)  # (script, repo): its cwd
    undirected: set[str] = field(default_factory=set)  # repos with no docs/product.md
    roles: dict[str, str] = field(default_factory=dict)  # repo: what `shipmill roles --flags` prints in its clone
    relayed: dict[str, set[int]] = field(default_factory=dict)  # repo: plans a relayed maintainer answer accepted
    pulls: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # repo: its open pull requests
    page: int = 0  # pull requests per page of the open pull requests' read; 0 for one page

    def cli(self, cmd: list[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
        """The pinned CLI's `--repo <clone> roles --flags`, the repo read from the clone's path"""
        assert cmd[-2:] == ["roles", "--flags"], cmd
        clone = Path(cmd[cmd.index("--repo") + 1])
        repo = f"{clone.parent.name}/{clone.name}"
        self.folders["roles", repo] = cwd
        failing = self.failing.get(repo)
        if failing is not None and failing[0] == "roles":
            return proc(2, err=failing[1])
        return proc(0, self.roles.get(repo, "--role maintainer=maint\n"))

    def __call__(self, cmd: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        cmd = list(cmd)
        self.calls.append(cmd)
        if cmd[0] == "uvx":
            return self.cli(cmd, cwd)
        if cmd[0] != "gh":
            self.folders[Path(cmd[1]).name, cmd[2]] = cwd
        if cmd[:3] == ["gh", "api", "user"]:
            return proc(0, "maint\n")
        if cmd[:3] == ["gh", "repo", "clone"]:
            step, repo = "clone", cmd[3]
        elif cmd[:3] == ["gh", "api", "graphql"]:
            fields = dict(arg.split("=", 1) for arg in cmd[4::2])
            step, repo = "graphql", f"{fields['owner']}/{fields['name']}"
        else:
            step, repo = Path(cmd[1]).name, cmd[2]
        failing = self.failing.get(repo)
        if failing is not None and failing[0] == step:
            return proc(2 if step != "graphql" else 1, err=failing[1])
        if step == "clone":
            if repo not in self.undirected:
                (Path(cmd[4]) / "docs").mkdir(parents=True)
                (Path(cmd[4]) / "docs" / "product.md").write_text("# Product\n", encoding="utf-8")
            return proc(0)
        if step == "intake_state.py" and "--plans" in cmd and not (cwd and (cwd / "docs" / "product.md").is_file()):
            return proc(2, err="error: shipmill product show failed with exit 2: docs/product.md:1: no such file")
        scripted = {"watch_state.py": self.watch, "triage_state.py": self.triage, "intake_state.py": self.intake}
        if step in scripted:
            rows = scripted[step].get(repo, [])
            if step == "intake_state.py" and any(a.startswith("maintainer=") for a in cmd):
                # D-68: a relayed answer counts only when the --role flags name the maintainer
                accepted = self.relayed.get(repo, set())
                rows = [{**r, "state": "PLAN_ACCEPTED"} if r.get("number") in accepted else r for r in rows]
            return proc(0, "".join(json.dumps(r) + "\n" for r in rows))
        if "pullRequests(" in fields["query"]:
            pulls = self.pulls.get(repo, [])
            start = int(fields.get("cursor", "0"))
            end = start + self.page if self.page else len(pulls)
            more = {"hasNextPage": end < len(pulls), "endCursor": str(end)}
            found_pulls = {"pullRequests": {"pageInfo": more, "nodes": pulls[start:end]}}
            return proc(0, json.dumps({"data": {"repository": found_pulls}}))
        numbers = [int(n) for n in re.findall(r"\bi(\d+): issueOrPullRequest", fields["query"])]
        found = {f"i{n}": self.github[repo].get(n) for n in numbers}
        return proc(0, json.dumps({"data": {"repository": found}}))


FLEET = """\
[[repos]]
repo = "o/r"

[[repos]]
repo = "o/s"
"""


def run_queue(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], fake: FakeGh, *flags: str
) -> tuple[int, str]:
    path = tmp_path / "fleet.toml"
    path.write_text(FLEET, encoding="utf-8")
    code = fl.main(["queue", "--fleet", str(path), *flags], runner=fake, clock=lambda: NOW)
    return code, capsys.readouterr().out


def test_s069_1_an_unanswered_question_is_a_row_and_an_answered_one_is_none(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    answered = asked(6, "Answered", ago(days=3))
    answered["comments"]["nodes"].append(comment("Take option 1", "amy", "OWNER", ago(days=1)))
    fake = FakeGh(
        watch={"o/r": [watch_row("NEEDS_DECISION", "o/r", "#5 #6")]},  # #6 answered since the watch read it
        github={"o/r": {5: asked(5, "Pick a name", ago(days=2, hours=3)), 6: answered}},
    )
    code, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert code == 1
    assert out.splitlines() == ["o/r QUESTION      #5     answer the needs-decision question: Pick a name (2d 3h)"]
    watch = next(c for c in fake.calls if c[1] == str(fl.WATCH_STATE))
    assert {"--trusted-only", "--no-host"} <= set(watch) and watch[watch.index("--bot-login") + 1] == BOT


def test_s069_1_an_outsiders_marker_never_times_the_question(fl: ModuleType) -> None:
    node = asked(5, "Pick", ago(days=2))
    node["comments"]["nodes"].append(comment(MARKER, "stranger", "NONE", ago(hours=1)))
    found = fl.queue_item("o/r", fl.QUESTION, node, BOT)
    assert found is not None and found.since == NOW - dt.timedelta(days=2)


def test_s069_1_a_question_with_no_marker_waits_since_its_label(fl: ModuleType) -> None:
    node = item(5, "Parked", labels=["needs-decision"], labelled=[("needs-decision", ago(hours=5))])
    found = fl.queue_item("o/r", fl.QUESTION, node, BOT)
    assert found is not None and found.since == NOW - dt.timedelta(hours=5)


def person(number: int, state: str, people: Sequence[str], since: str, teams: Sequence[str] = ()) -> dict[str, Any]:
    """A triage_state.py --json line of a person's item"""
    line = {"number": number, "state": state, "title": f"Item {number}", "note": f"with @x since {since}"}
    line["assignees"] = list(people)
    if teams:
        line["teams"] = list(teams)
    return line


def persons_fake() -> FakeGh:
    triage = [
        person(7, "WITH_PERSON", ["Maint", "bob"], ago(days=2)),  # the reader, spelled in another case
        person(8, "WITH_PERSON", ["bob"], ago(days=3)),  # only another login
        person(9, "WITH_PERSON", [], ago(days=4), teams=["@o/ops"]),  # only a team
        person(10, "HANDOFF_DUE", ["maint"], ago(days=5)),  # not handed off yet: not with the person
        {"number": 11, "state": "NEW", "title": "New", "note": ""},
    ]
    return FakeGh(
        triage={"o/r": triage},
        github={"o/r": {n: item(n, f"Item {n}") for n in (7, 8, 9, 10, 11)}},
    )


def test_s069_2_a_with_person_item_assigned_to_the_reader_is_your_item(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = persons_fake()
    code, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert code == 1
    assert out.splitlines() == ["o/r YOUR_ITEM     #7     do your item: Item 7 (2d 0h)"]  # since the hand-off
    assert sum(c[:3] == ["gh", "api", "user"] for c in fake.calls) == 1  # the reader: gh api user's login, once
    triage = next(c for c in fake.calls if c[1] == str(fl.WS.TRIAGE_STATE))
    assert {"--json", "--trusted-only"} <= set(triage) and triage[triage.index("--bot-login") + 1] == BOT
    graphql = next(c for c in fake.calls if c[:3] == ["gh", "api", "graphql"])
    assert re.findall(r"\bi(\d+): issueOrPullRequest", graphql[4]) == ["7"]  # the others are never read


def test_s069_2_the_reader_is_the_login_flag_before_gh(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = persons_fake()
    code, out = run_queue(fl, tmp_path, capsys, fake, "--login", "bob")
    assert code == 1
    assert out.splitlines() == [
        "o/r YOUR_ITEM     #8     do your item: Item 8 (3d 0h)",
        "o/r YOUR_ITEM     #7     do your item: Item 7 (2d 0h)",
    ]
    assert not any(c[:3] == ["gh", "api", "user"] for c in fake.calls)


def test_s069_2_a_with_person_line_without_assignees_or_since_stops_the_run(fl: ModuleType) -> None:
    with pytest.raises(fl.Refused, match="without its assignees"):
        fl.person_items(json.dumps({"number": 7, "state": "WITH_PERSON", "note": "with @a since x"}), "o/r", "a")
    line = {"number": 7, "state": "WITH_PERSON", "note": "with @a", "assignees": ["a"]}
    with pytest.raises(fl.Refused, match="without its since"):
        fl.person_items(json.dumps(line), "o/r", "a")


def intake_line(number: int | None, state: str, kind: str = "opportunity") -> dict[str, Any]:
    """An intake_state.py --json line: an opportunity's, or a plan or goal row's"""
    if kind == "opportunity":
        return {"number": number, "kind": kind, "state": state, "title": "t", "thumbs": 0, "members": [], "note": ""}
    return {"goal": "G-1", "kind": kind, "number": number, "state": state, "title": "t", "note": "", "author": BOT}


def test_s069_3_open_opportunities_plans_and_unreasoned_declines_are_rows_and_no_other_state(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    revisions = [
        comment("<!-- shipmill:plan-revised rev=1 -->\nnew plan", BOT, "NONE", ago(days=6)),
        comment("<!-- shipmill:plan-revised rev=2 -->\nnot the App's", "stranger", "NONE", ago(days=1)),
    ]
    fake = FakeGh(
        intake={
            "o/r": [
                {"autonomy": "propose"},
                intake_line(20, "OPPORTUNITY_OPEN"),
                intake_line(21, "ACCEPTED"),
                intake_line(22, "HANDED_OFF"),
                intake_line(23, "DECLINED"),
                intake_line(24, "NO_REASON"),
                intake_line(25, "OPPORTUNITY_OPEN"),  # an outsider's opportunity
                {"number": 26, "kind": "issue", "state": "NEW_FEEDBACK", "title": "t", "thumbs": 0, "members": []},
                intake_line(None, "PLAN_DUE", "goal"),
                intake_line(30, "PLAN_OPEN", "plan"),
                intake_line(31, "PLAN_ACCEPTED", "plan"),
            ]
        },
        github={
            "o/r": {
                20: item(20, "Export to CSV", created=ago(days=9)),
                24: item(24, "Dark mode", state="CLOSED", created=ago(days=20), closed=ago(hours=7)),
                25: item(25, "Stranger's", author="stranger", association="NONE", created=ago(days=12)),
                30: item(30, "Plan for G-1", author=BOT, association="NONE", comments=revisions, created=ago(days=8)),
            }
        },
    )
    code, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert code == 1
    assert out.splitlines() == [
        "o/r OPPORTUNITY   #20    accept or decline the opportunity: Export to CSV (9d 0h)",
        "o/r PLAN          #30    answer the goal plan: Plan for G-1 (6d 0h)",  # since the App's newest revision
        "o/r NO_REASON     #24    record why the opportunity was declined: Dark mode (7h)",  # since the close
    ]
    intake = next(c for c in fake.calls if c[1] == str(fl.WS.INTAKE_STATE))
    assert {"--plans", "--json"} <= set(intake) and intake[intake.index("--bot-login") + 1] == BOT
    clone = next(c for c in fake.calls if c[:3] == ["gh", "repo", "clone"] and c[3] == "o/r")
    assert fake.folders["intake_state.py", "o/r"] == Path(clone[4])  # in the clone, where it reads the direction
    graphql = next(c for c in fake.calls if c[:3] == ["gh", "api", "graphql"])
    assert re.findall(r"\bi(\d+): issueOrPullRequest", graphql[4]) == ["20", "24", "25", "30"]


def test_s069_3_a_repo_with_no_direction_reads_its_opportunities_without_plans(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGh(
        watch={"o/r": [watch_row("NEEDS_DECISION", "o/r", "#5")]},
        intake={"o/r": [intake_line(20, "OPPORTUNITY_OPEN")]},
        github={"o/r": {5: asked(5, "Pick", ago(hours=2)), 20: item(20, "Export to CSV", created=ago(days=9))}},
        undirected={"o/r", "o/s"},
    )
    code, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert code == 1
    assert out.splitlines() == [
        "o/r OPPORTUNITY   #20    accept or decline the opportunity: Export to CSV (9d 0h)",
        "o/r QUESTION      #5     answer the needs-decision question: Pick (2h)",
    ]
    intake = [c for c in fake.calls if c[1:2] == [str(fl.WS.INTAKE_STATE)]]
    assert len(intake) == 2 and not any("--plans" in c for c in intake)  # as the watch: plans only with a direction


def test_the_items_query_asks_github_for_every_field_a_row_reads(fl: ModuleType) -> None:
    asked = set(fl.FIELDS.splitlines()[0].split())
    assert {*fl.ITEM_KEYS, "closedAt"} - {"labels"} <= asked


def test_s069_3_an_unreasoned_decline_reopened_since_is_no_row(fl: ModuleType) -> None:
    assert fl.queue_item("o/r", fl.NO_REASON, item(24, "Reopened"), BOT) is None
    assert fl.queue_item("o/r", fl.OPPORTUNITY, item(20, "Closed", state="CLOSED", closed=ago(hours=1)), BOT) is None


def test_s069_6_an_opportunity_or_person_item_in_question_is_only_a_question(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGh(
        watch={"o/r": [watch_row("NEEDS_DECISION", "o/r", "#20 #7")]},
        triage={"o/r": [person(7, "WITH_PERSON", ["maint"], ago(days=2))]},
        intake={"o/r": [intake_line(20, "OPPORTUNITY_OPEN")]},
        github={"o/r": {20: asked(20, "Opportunity", ago(hours=2)), 7: asked(7, "Item", ago(hours=1))}},
    )
    _, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert [line.split()[1] for line in out.splitlines()] == ["QUESTION", "QUESTION"]


def test_the_plan_revision_marker_is_intake_states() -> None:
    intake = Path(__file__).resolve().parents[1] / "skills" / "product-intake" / "scripts" / "intake_state.py"
    found = re.search(r'^REVISED = re\.compile\(r"(.+)"\)$', intake.read_text(encoding="utf-8"), re.MULTILINE)
    fleet = (SCRIPTS / "fleet.py").read_text(encoding="utf-8")
    assert found is not None and f'REVISED = re.compile(r"{found.group(1)}")' in fleet


SPEC_QUESTION = (
    f"{MARKER}\n@maint Decision needed: approve this spec?\n"
    "1. Take every recommendation (recommended): merge it as it stands\n"
    "2. Change some: say which\n"
)


def pull(
    number: int,
    title: str,
    *,
    body: str = "Spec for #3\n\n## Decisions for you\n",
    draft: bool = False,
    comments: Sequence[dict[str, Any]] = (),
    files: Sequence[str] = ("docs/specs/090-a-spec.md",),
    more_files: bool = False,
    ready: str | None = None,
    author: str = BOT,
    association: str = "NONE",
) -> dict[str, Any]:
    """An open pull request as the open pull requests' read gives it, the App's by default"""
    node = item(number, title, pr=True, author=author, association=association, comments=comments)
    node["body"] = body
    node["isDraft"] = draft
    node["comments"]["pageInfo"] = {"hasPreviousPage": False}
    node["files"] = {"pageInfo": {"hasNextPage": more_files}, "nodes": [{"path": p} for p in files]}
    node["timelineItems"] = {"nodes": [{"createdAt": ready}] if ready else []}
    del node["labels"]
    return node


def spec_question(at: str, *answers: dict[str, Any]) -> list[dict[str, Any]]:
    """The App's approval question on a spec pull request, then the replies"""
    return [comment(SPEC_QUESTION, BOT, "NONE", at), *answers]


def decided_comment(zone: str, author: str = BOT, association: str = "NONE") -> dict[str, Any]:
    body = f"<!-- shipmill:decided zone={zone} until=2026-11-20T00:00:00Z -->\n<!-- shipmill:head {'a' * 40} -->"
    return comment(body, author, association, ago(days=1))


def test_s069_4_an_open_spec_pull_request_nothing_lands_is_a_row(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    takes = comment("1", "amy", "OWNER", ago(days=2))
    pulls = [
        pull(40, "Spec 090: export", ready=ago(days=4)),  # waiting since it was marked ready
        pull(41, "Draft spec", draft=True),
        pull(42, "Not a spec", body="Fixes #3\n\nSpec for #3"),  # `Spec for` isn't its first line
        pull(43, "Asked, unanswered", comments=spec_question(ago(days=3))),  # a question holds it
        pull(44, "Approved by an answer", comments=spec_question(ago(days=3), takes)),
        pull(45, "Approved at notify", comments=[decided_comment("accepted-spec")]),
        pull(
            46, "Decided, edits the direction", comments=[decided_comment("accepted-spec")], files=("docs/product.md",)
        ),
        pull(
            47,
            "Answered, edits a moved section",
            comments=spec_question(ago(days=3), takes),
            files=("docs/product/u.md",),
        ),
        pull(
            48, "Relayed approval", comments=spec_question(ago(days=3), comment("Decision by @maint\n1", BOT, "NONE"))
        ),
        pull(49, "Too many files to rule out", comments=[decided_comment("accepted-spec")], more_files=True),
        pull(50, "A stranger's spec", author="stranger", association="NONE"),
    ]
    fake = FakeGh(pulls={"o/r": pulls}, page=4)
    code, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert code == 1
    asked = "merge the spec pull request"
    assert out.splitlines() == [
        f"o/r SPEC_TO_MERGE #46    {asked}: Decided, edits the direction (30d 0h)",  # since its opening
        f"o/r SPEC_TO_MERGE #47    {asked}: Answered, edits a moved section (30d 0h)",
        f"o/r SPEC_TO_MERGE #49    {asked}: Too many files to rule out (30d 0h)",
        f"o/r SPEC_TO_MERGE #40    {asked}: Spec 090: export (4d 0h)",
    ]
    reads = [c for c in fake.calls if c[:3] == ["gh", "api", "graphql"] and "pullRequests(" in c[4]]
    assert [c[10] if len(c) > 9 else None for c in reads if "owner=o" in c and "name=r" in c] == [
        None,
        "cursor=4",
        "cursor=8",
    ]  # every page of the open pull requests


def test_s069_4_an_untrusted_answer_or_decided_comment_never_lands_a_spec(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    changes = comment("2", "amy", "OWNER", ago(days=2))  # the maintainer changes a recommendation
    stranger = comment("1", "stranger", "NONE", ago(days=1))  # an outsider takes it after
    pulls = [
        pull(60, "Changed, then a stranger's 1", comments=spec_question(ago(days=3), changes, stranger)),
        pull(61, "A person's decided comment", comments=[decided_comment("accepted-spec", "amy", "OWNER")]),
        pull(62, "The App decided another zone", comments=[decided_comment("scope")]),
        pull(
            63,
            "A relay naming no maintainer",
            comments=spec_question(ago(days=3), changes, comment("Decision by @bob\n1", BOT, "NONE")),
        ),
    ]
    fake = FakeGh(pulls={"o/r": pulls})
    code, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert code == 1
    assert [line.split()[2] for line in out.splitlines()] == ["#60", "#61", "#62", "#63"]


def test_s069_4_a_spec_pull_request_in_question_is_only_a_question(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    held = asked(70, "Spec 091", ago(hours=2), pr=True)
    fake = FakeGh(
        watch={"o/r": [watch_row("NEEDS_DECISION", "o/r", "#70")]},
        github={"o/r": {70: held}},
        pulls={"o/r": [pull(70, "Spec 091", author="amy", association="OWNER")]},
    )
    _, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert [line.split()[1:3] for line in out.splitlines()] == [["QUESTION", "#70"]]


def test_s069_4_without_a_bot_login_no_decided_comment_counts(fl: ModuleType) -> None:
    node = pull(80, "Decided", author="amy", association="OWNER", comments=[decided_comment("accepted-spec")])
    assert fl.spec_item("o/r", node, BOT, frozenset({"maint"})) is None
    found = fl.spec_item("o/r", node, None, frozenset({"maint"}))
    assert found is not None and found.kind == fl.SPEC_TO_MERGE


def test_s069_4_a_failed_pull_requests_read_is_a_repo_error(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGh(pulls={"o/r": [pull(40, "Spec")]}, failing={"o/s": ("graphql", "error: HTTP 502\nmore")})
    code, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert code == 2
    assert out.splitlines()[-1] == "o/s REPO_ERROR gh api graphql: error: HTTP 502"


def test_s069_5_a_pull_request_to_merge_and_a_proposal_are_rows(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGh(
        watch={
            "o/r": [
                watch_row("PRS_PARKED", "o/r", "WITH_PERSON #4 (@a); TO_MERGE #12"),
                watch_row("PROMOTION_DUE", "production", "#20 v1.2.0: gh workflow run operate.yml -f approve=prod"),
                watch_row("PROMOTION_DUE", "staging", "would promote v1.2.0, but operate.yml has no schedule; x"),
            ]
        },
        github={
            "o/r": {
                12: item(
                    12,
                    "Fix the thing",
                    pr=True,
                    labels=["shipmill-ready"],
                    labelled=[("shipmill-ready", ago(days=4)), ("shipmill-ready", ago(minutes=12))],
                ),
                20: item(20, "Ready to promote v1.2.0 to production", created=ago(hours=5)),
            }
        },
    )
    code, out = run_queue(fl, tmp_path, capsys, fake)
    assert code == 1
    assert out.splitlines() == [
        "o/r PROMOTION     #20    approve the promotion: Ready to promote v1.2.0 to production (5h)",
        "o/r TO_MERGE      #12    merge the pull request: Fix the thing (12m)",
    ]
    graphql = [c for c in fake.calls if c[:3] == ["gh", "api", "graphql"] and "issueOrPullRequest" in c[4]]
    assert len(graphql) == 1  # one batched read for the repo's items


def test_s069_6_an_item_in_question_is_in_no_other_row(fl: ModuleType) -> None:
    rows = [
        fl.Row("PRS_PARKED", "o/r", "TO_MERGE #12 #13"),
        fl.Row("NEEDS_DECISION", "o/r", "#12 #3"),
        fl.Row("PROMOTION_DUE", "prod", "#3 v1: approve"),
    ]
    assert fl.wanted(rows) == {12: fl.QUESTION, 13: fl.TO_MERGE, 3: fl.QUESTION}


def test_s069_7_rows_from_several_repos_print_in_one_list_oldest_first(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGh(
        watch={
            "o/r": [watch_row("NEEDS_DECISION", "o/r", "#1 #2")],
            "o/s": [watch_row("NEEDS_DECISION", "o/s", "#9")],
        },
        github={
            "o/r": {1: asked(1, "Newest", ago(minutes=40)), 2: asked(2, "Tied", ago(days=1))},
            "o/s": {9: asked(9, "Oldest", ago(days=3, hours=4))},
        },
    )
    fake.github["o/s"][8] = asked(8, "Tied too", ago(days=1))
    fake.watch["o/s"][0]["detail"] = "#8 #9"
    code, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert code == 1
    assert out.splitlines() == [
        "o/s QUESTION      #9     answer the needs-decision question: Oldest (3d 4h)",
        "o/r QUESTION      #2     answer the needs-decision question: Tied (1d 0h)",  # a tie: the fleet file's order
        "o/s QUESTION      #8     answer the needs-decision question: Tied too (1d 0h)",
        "o/r QUESTION      #1     answer the needs-decision question: Newest (40m)",
    ]


def test_s069_8_json_is_one_object_in_the_tables_order(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGh(
        watch={"o/r": [watch_row("NEEDS_DECISION", "o/r", "#1 #2")]},
        github={"o/r": {1: asked(1, "New", ago(minutes=5)), 2: asked(2, "Old", ago(hours=2))}},
        failing={"o/s": ("clone", "GraphQL: Could not resolve to a Repository\nmore")},
    )
    code, out = run_queue(fl, tmp_path, capsys, fake, "--json", "--bot-login", BOT)
    assert code == 2
    found = json.loads(out)
    assert found["login"] == "maint"
    assert [i["number"] for i in found["items"]] == [2, 1]
    assert found["items"][0] == {
        "repo": "o/r",
        "kind": "QUESTION",
        "number": 2,
        "url": "https://github.com/o/r/issues/2",
        "asked": "answer the needs-decision question",
        "title": "Old",
        "since": ago(hours=2),
        "waited_minutes": 120,
    }
    assert found["errors"] == [
        {"repo": "o/s", "step": "gh repo clone", "error": "GraphQL: Could not resolve to a Repository"}
    ]


def test_s069_8_login_comes_from_the_flag_before_gh(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGh()
    code, out = run_queue(fl, tmp_path, capsys, fake, "--json", "--login", "amy")
    assert code == 0 and json.loads(out) == {"login": "amy", "items": [], "errors": []}
    assert ["gh", "api", "user", "--jq", ".login"] not in fake.calls


def test_s069_9_an_outsiders_item_is_in_no_row(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGh(
        watch={
            "o/r": [
                watch_row("NEEDS_DECISION", "o/r", "#1 #2 #3"),
                watch_row("PROMOTION_DUE", "prod", "#4 v1: approve"),
            ]
        },
        github={
            "o/r": {
                1: asked(1, "Outsider", ago(hours=1), author="stranger", association="CONTRIBUTOR"),
                2: asked(2, "The App's", ago(hours=2), author=BOT, association="NONE"),
                3: asked(3, "A member's", ago(hours=3), author="bob", association="MEMBER"),
                4: item(4, "Ready to promote v1 to prod", author="stranger", association="NONE"),
            }
        },
    )
    _, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert [line.split()[2] for line in out.splitlines()] == ["#3", "#2"]
    _, out = run_queue(fl, tmp_path, capsys, fake)  # without --bot-login, the App's item is an outsider's
    assert [line.split()[2] for line in out.splitlines()] == ["#3"]


def test_s069_5_a_promotion_the_app_opened_is_a_row(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#1371: operate.yml opens its "Ready to promote" issue as the App when the caller passes
    its key, so the proposal is the --bot-login's and a PROMOTION row; one the workflow token
    opened stays out, as S-069-9 and D-30 keep github-actions[bot] untrusted"""
    fake = FakeGh(
        watch={
            "o/r": [
                watch_row("PROMOTION_DUE", "production", "#20 v1.2.0: gh workflow run operate.yml -f approve=prod"),
                watch_row("PROMOTION_DUE", "staging", "#21 v1.2.0rc1: gh workflow run operate.yml -f approve=staging"),
            ]
        },
        github={
            "o/r": {
                20: item(20, "Ready to promote v1.2.0 to production", author=BOT, association="NONE"),
                21: item(21, "Ready to deploy v1.2.0rc1 to staging", author="github-actions[bot]", association="NONE"),
            }
        },
    )
    code, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert code == 1
    assert [line.split()[1:3] for line in out.splitlines()] == [["PROMOTION", "#20"]]


def test_s069_10_a_failed_repo_is_one_repo_error_line_and_the_rest_print(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    steps = ["watch_state.py", "triage_state.py", "intake_state.py", "graphql"]
    for step, named in [(s, "gh api graphql" if s == "graphql" else s) for s in steps]:
        fake = FakeGh(
            watch={
                "o/r": [watch_row("NEEDS_DECISION", "o/r", "#1")],
                "o/s": [watch_row("NEEDS_DECISION", "o/s", "#2")],
            },
            github={"o/r": {1: asked(1, "Fine", ago(hours=1))}, "o/s": {2: asked(2, "Unread", ago(hours=2))}},
            failing={"o/s": (step, "error: HTTP 502\nsecond line")},
        )
        code, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
        assert code == 2
        assert out.splitlines() == [
            "o/r QUESTION      #1     answer the needs-decision question: Fine (1h)",
            f"o/s REPO_ERROR {named}: error: HTTP 502",
        ]


def test_s069_11_exit_0_on_an_empty_queue_and_1_with_a_row(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGh(watch={"o/r": [watch_row("PRS_OPEN", "o/r", "#4")]})
    code, out = run_queue(fl, tmp_path, capsys, fake)
    assert (code, out) == (0, "nothing waits on the maintainer\n")
    fake.watch["o/r"].append(watch_row("NEEDS_DECISION", "o/r", "#1"))
    fake.github["o/r"] = {1: asked(1, "Asked", ago(hours=1))}
    assert run_queue(fl, tmp_path, capsys, fake)[0] == 1


@pytest.mark.parametrize("text", ["# nothing yet\n", '[[repos]]\nrepo = "o/r"\n\n[[repos]]\nrepo = "O/R"\n'])
def test_s069_11_a_fleet_file_report_refuses_queue_refuses_alike(fl: ModuleType, tmp_path: Path, text: str) -> None:
    path = tmp_path / "fleet.toml"
    path.write_text(text, encoding="utf-8")
    messages = []
    for command in ("report", "queue"):
        fake = FakeGh()
        with pytest.raises(SystemExit) as refused:
            fl.main([command, "--fleet", str(path)], runner=fake, clock=lambda: NOW)
        assert refused.value.code == 2 and fake.calls == []
        messages.append(str(refused.value))
    assert messages[0] == messages[1]


def test_s069_12_queue_makes_only_reads_on_github(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGh(
        watch={"o/r": [watch_row("NEEDS_DECISION", "o/r", "#1"), watch_row("PRS_PARKED", "o/r", "TO_MERGE #2")]},
        github={"o/r": {1: asked(1, "A", ago(hours=1)), 2: item(2, "B", pr=True, labels=["shipmill-ready"])}},
    )
    run_queue(fl, tmp_path, capsys, fake)
    gh = [c for c in fake.calls if c[0] == "gh"]
    assert {tuple(c[:3]) for c in gh} == {("gh", "api", "user"), ("gh", "repo", "clone"), ("gh", "api", "graphql")}
    for call in gh:
        assert not {"-X", "--method", "--input"} & set(call)
        assert not any(arg.startswith("query=mutation") for arg in call)
        if call[:3] == ["gh", "api", "graphql"]:
            assert next(a for a in call if a.startswith("query=")).startswith("query=query(")
    others = [c for c in fake.calls if c[0] not in ("gh", "uvx")]
    scripts = {str(fl.WATCH_STATE), str(fl.WS.TRIAGE_STATE), str(fl.WS.INTAKE_STATE)}  # each reads only (D-55)
    assert {c[1] for c in others} == scripts
    assert all(c[-2:] == ["roles", "--flags"] for c in fake.calls if c[0] == "uvx")  # the CLI only reads the roles


def role_values(cmd: list[str]) -> list[str]:
    return [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--role"]


def test_1409_both_state_scripts_carry_the_clones_roles(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGh(roles={"o/r": "--role maintainer=amy,@o/core --role reviewer=bob\n"}, undirected={"o/s"})
    code, _ = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert code == 0
    clone = next(c for c in fake.calls if c[:3] == ["gh", "repo", "clone"] and c[3] == "o/r")
    cli = [c for c in fake.calls if c[0] == "uvx"]
    assert len(cli) == 2  # one roles read per repo
    assert cli[0] == [*fl.WS.shipmill_cli(), "--repo", clone[4], "roles", "--flags"]  # the pinned CLI, as the watch's
    assert fake.folders["roles", "o/r"] == Path(clone[4])  # in the clone, whose [agents.roles] it reads

    def script(path: Path, repo: str) -> list[str]:
        return next(c for c in fake.calls if c[1:3] == [str(path), repo])

    assert role_values(script(fl.WS.TRIAGE_STATE, "o/r")) == ["maintainer=amy,@o/core", "reviewer=bob"]
    assert role_values(script(fl.WS.INTAKE_STATE, "o/r")) == ["maintainer=amy,@o/core", "reviewer=bob"]
    assert role_values(script(fl.WS.TRIAGE_STATE, "o/s")) == ["maintainer=maint"]
    assert role_values(script(fl.WS.INTAKE_STATE, "o/s")) == []  # no --plans: intake_state.py takes --role only with it


def test_1409_a_roles_read_that_fails_is_a_repo_error_and_never_a_queue_without_roles(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unread = "error: [agents.roles] maintainer lists nobody, so the maintainer is the host's gh login: HTTP 401"
    fake = FakeGh(
        watch={"o/r": [watch_row("NEEDS_DECISION", "o/r", "#1")], "o/s": [watch_row("NEEDS_DECISION", "o/s", "#2")]},
        github={"o/r": {1: asked(1, "Fine", ago(hours=1))}, "o/s": {2: asked(2, "Unread", ago(hours=2))}},
        failing={"o/s": ("roles", f"{unread}\nsecond line")},
    )
    code, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert code == 2
    assert out.splitlines() == [
        "o/r QUESTION      #1     answer the needs-decision question: Fine (1h)",
        f"o/s REPO_ERROR shipmill roles --flags: {unread}",
    ]
    assert not [c for c in fake.calls if c[0] not in ("gh", "uvx") and c[2] == "o/s"]  # no script ran without roles


def test_1409_a_plan_the_maintainer_answered_through_a_relay_leaves_the_queue(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = item(30, "Plan for G-1", author=BOT, association="NONE", created=ago(days=8))
    fake = FakeGh(intake={"o/r": [intake_line(30, "PLAN_OPEN", "plan")]}, github={"o/r": {30: plan}})
    assert run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)[0] == 1  # unanswered: a PLAN row
    fake.relayed["o/r"] = {30}  # the session relayed the maintainer's accept (D-68)
    assert run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT) == (0, "nothing waits on the maintainer\n")


@pytest.mark.parametrize("text", ["", "\n", "maintainer=amy\n", "--role\n", "--role maintainer=amy --flag x\n"])
def test_1409_roles_output_that_isnt_role_flags_stops_the_run(fl: ModuleType, text: str) -> None:
    assert fl.role_values("--role maintainer=amy --role reviewer=@o/core\n", "o/r") == [
        "maintainer=amy",
        "reviewer=@o/core",
    ]
    with pytest.raises(fl.Refused, match="shipmill roles --flags for o/r printed"):
        fl.role_values(text, "o/r")


def test_s069_13_the_fleet_section_documents_the_queue_its_rows_and_a_routine(fl: ModuleType) -> None:
    skill = (SCRIPTS.parent / "SKILL.md").read_text(encoding="utf-8")
    fleet = re.search(r"^## Fleet\n(.*?)^## ", skill, re.MULTILINE | re.DOTALL)
    assert fleet is not None
    section = fleet.group(1)
    assert "`scripts/fleet.py queue --fleet <file>" in section
    for kind in fl.ASKED:
        assert f"- `{kind}`: " in section, kind
    routine = re.findall(r"```text\n(.*?)```", section, re.DOTALL)
    assert any("fleet.py queue --fleet" in block and "oldest first" in block for block in routine)


def test_waited_text_reads_days_hours_and_minutes(fl: ModuleType) -> None:
    assert [fl.waited_text(m) for m in (0, 12, 59, 60, 5 * 60 + 59, 24 * 60, 3 * 24 * 60 + 4 * 60 + 7)] == [
        "0m",
        "12m",
        "59m",
        "1h",
        "5h",
        "1d 0h",
        "3d 4h",
    ]


def test_a_closed_item_or_one_whose_label_came_off_is_no_row(fl: ModuleType) -> None:
    assert fl.queue_item("o/r", fl.QUESTION, asked(1, "Closed", ago(hours=1), state="CLOSED"), None) is None
    assert fl.queue_item("o/r", fl.TO_MERGE, item(2, "Unlabelled", pr=True), None) is None
    assert fl.queue_item("o/r", fl.QUESTION, item(3, "No label"), None) is None


def test_a_bot_login_that_isnt_a_login_is_refused(fl: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "fleet.toml"
    path.write_text(FLEET, encoding="utf-8")
    with pytest.raises(SystemExit) as refused:
        fl.main(["queue", "--fleet", str(path), "--bot-login", "not a login"], runner=FakeGh(), clock=lambda: NOW)
    assert refused.value.code == 2


# -- fleet.py overview (#1479): the report and the queue in one pass, one clone per repo ----------


def overview_fake(**kw: Any) -> FakeGh:
    """Two repos with an action row, a report-only row, two questions, and a person's item"""
    return FakeGh(
        watch={
            "o/r": [watch_row("NEEDS_DECISION", "o/r", "#1"), watch_row("PRS_OPEN", "o/r", "#4")],
            "o/s": [watch_row("NEEDS_DECISION", "o/s", "#2")],
        },
        triage={"o/s": [person(7, "WITH_PERSON", ["maint"], ago(days=2))]},
        github={
            "o/r": {1: asked(1, "Pick a name", ago(hours=5))},
            "o/s": {2: asked(2, "Pick a port", ago(days=1)), 7: item(7, "Item 7")},
        },
        **kw,
    )


def run_overview(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], fake: FakeGh, *flags: str
) -> tuple[int, str]:
    path = tmp_path / "fleet.toml"
    path.write_text(FLEET, encoding="utf-8")
    code = fl.main(["overview", "--fleet", str(path), "--bot-login", BOT, *flags], runner=fake, clock=lambda: NOW)
    return code, capsys.readouterr().out


def test_1479_overview_prints_the_reports_rows_and_the_queues_items_as_the_two_commands_apart(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "fleet.toml"
    path.write_text(FLEET, encoding="utf-8")
    fl.main(["report", "--fleet", str(path), "--json"], runner=overview_fake(), clock=lambda: NOW)
    report = json.loads(capsys.readouterr().out)
    _, queue = run_queue(fl, tmp_path, capsys, overview_fake(), "--json", "--bot-login", BOT)
    code, both = run_overview(fl, tmp_path, capsys, overview_fake(), "--json")
    assert json.loads(both) == {"report": report, "queue": json.loads(queue)}
    assert code == 1
    assert [i["number"] for i in json.loads(queue)["items"]] == [7, 2, 1]  # oldest first across repos
    assert [r["repo"] for r in report["repos"]] == ["o/r", "o/s"]


def test_1479_overview_clones_each_repo_once_and_runs_both_watches_on_that_clone(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = overview_fake()
    code, out = run_overview(fl, tmp_path, capsys, fake)
    assert code == 1
    clones = [c for c in fake.calls if c[:3] == ["gh", "repo", "clone"]]
    assert sorted(c[3] for c in clones) == ["o/r", "o/s"]
    for clone in clones:
        watches = [c for c in fake.calls if c[1] == str(fl.WATCH_STATE) and c[2] == clone[3]]
        assert len(watches) == 2  # the report's full watch and the queue's trusted one: the PR's open point
        assert all(w[w.index("--repo-dir") + 1] == clone[4] for w in watches)
        assert sum("--trusted-only" in w for w in watches) == 1
    assert out.splitlines() == [
        "o/r NEEDS_DECISION o/r              #1",
        "o/s NEEDS_DECISION o/s              #2",
        "o/r PRS_OPEN       o/r              #4",
        "",
        "o/s YOUR_ITEM     #7     do your item: Item 7 (2d 0h)",
        "o/s QUESTION      #2     answer the needs-decision question: Pick a port (1d 0h)",
        "o/r QUESTION      #1     answer the needs-decision question: Pick a name (5h)",
    ]


def test_1479_a_repo_whose_read_fails_gets_its_error_rows_and_the_others_print(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = overview_fake(failing={"o/s": ("clone", "GraphQL: Could not resolve to a Repository\nmore")})
    code, out = run_overview(fl, tmp_path, capsys, fake)
    assert code == 2
    assert out.splitlines() == [
        "o/r NEEDS_DECISION o/r              #1",
        "o/s REPO_ERROR     gh repo clone    GraphQL: Could not resolve to a Repository",
        "o/r PRS_OPEN       o/r              #4",
        "",
        "o/r QUESTION      #1     answer the needs-decision question: Pick a name (5h)",
        "o/s REPO_ERROR gh repo clone: GraphQL: Could not resolve to a Repository",
    ]
    assert sorted(c[3] for c in fake.calls if c[:3] == ["gh", "repo", "clone"]) == ["o/r", "o/s"]  # o/s's once


@dataclass
class Gated(FakeGh):
    """o/r's clone waits until o/s's last read has ended: o/s is read first, yet o/r prints first"""

    later: threading.Event = field(default_factory=threading.Event)

    def __call__(self, cmd: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        cmd = list(cmd)
        if cmd[:4] == ["gh", "repo", "clone", "o/r"]:
            assert self.later.wait(10), "o/s was never read while o/r waited: the repos aren't read concurrently"
        found = super().__call__(cmd, cwd)
        if cmd[:3] == ["gh", "api", "graphql"] and "name=s" in cmd and "pullRequests(" in cmd[4]:
            self.later.set()  # o/s's open pull requests: its last read
        return found


def test_1479_repos_are_read_concurrently_and_printed_in_the_fleet_files_order(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = overview_fake()
    fake = Gated(watch=base.watch, triage=base.triage, github=base.github)
    code, out = run_overview(fl, tmp_path, capsys, fake, "--jobs", "2", "--json")
    assert code == 1
    assert [c[3] for c in fake.calls if c[:3] == ["gh", "repo", "clone"]] == ["o/s", "o/r"]  # o/r's waited for o/s
    found = json.loads(out)
    assert [r["repo"] for r in found["report"]["repos"]] == ["o/r", "o/s"]
    assert [i["number"] for i in found["queue"]["items"]] == [7, 2, 1]


def test_1479_the_fleet_section_documents_the_overview(fl: ModuleType) -> None:
    skill = (SCRIPTS.parent / "SKILL.md").read_text(encoding="utf-8")
    assert "`scripts/fleet.py overview --fleet <file>" in skill
    assert "--jobs" in skill
