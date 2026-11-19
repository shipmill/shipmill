"""github-ship-watch's maintainer queue (spec S-069): fleet.py queue, from a fake gh"""

import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
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
) -> dict[str, Any]:
    bot = author.endswith("[bot]")
    return {
        "__typename": "PullRequest" if pr else "Issue",
        "number": number,
        "title": title,
        "url": f"https://github.com/o/r/{'pull' if pr else 'issues'}/{number}",
        "state": state,
        "createdAt": created or ago(days=30),
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
    """Answers the clone, watch_state.py, gh api user, and gh api graphql, recording each call"""

    watch: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    github: dict[str, dict[int, dict[str, Any]]] = field(default_factory=dict)
    failing: dict[str, tuple[str, str]] = field(default_factory=dict)  # repo: (step, stderr)
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        cmd = list(cmd)
        self.calls.append(cmd)
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
            return proc(0)
        if step == "watch_state.py":
            rows = self.watch.get(repo, [])
            return proc(0, "".join(json.dumps(r) + "\n" for r in rows))
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
    assert out.splitlines() == ["o/r QUESTION   #5     answer the needs-decision question: Pick a name (2d 3h)"]
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
        "o/r PROMOTION  #20    approve the promotion: Ready to promote v1.2.0 to production (5h)",
        "o/r TO_MERGE   #12    merge the pull request: Fix the thing (12m)",
    ]
    graphql = [c for c in fake.calls if c[:3] == ["gh", "api", "graphql"]]
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
        "o/s QUESTION   #9     answer the needs-decision question: Oldest (3d 4h)",
        "o/r QUESTION   #2     answer the needs-decision question: Tied (1d 0h)",  # a tie: the fleet file's order
        "o/s QUESTION   #8     answer the needs-decision question: Tied too (1d 0h)",
        "o/r QUESTION   #1     answer the needs-decision question: Newest (40m)",
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


def test_s069_10_a_failed_repo_is_one_repo_error_line_and_the_rest_print(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for step, named in [("watch_state.py", "watch_state.py"), ("graphql", "gh api graphql")]:
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
            "o/r QUESTION   #1     answer the needs-decision question: Fine (1h)",
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
    others = [c for c in fake.calls if c[0] != "gh"]
    assert all(c[1] == str(fl.WATCH_STATE) for c in others)  # the watch reads only (D-55)


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
