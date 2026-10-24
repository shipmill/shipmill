"""Spec 038, #586: local triage reads a report labelled upstream as waiting outside, and the
watch and setup know it, without gh or the network"""

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.gate import Action, decide, parse_findings

from .test_triage_state import comment, first_page, forward, open_issue

SKILLS = Path(__file__).resolve().parents[1] / "skills"
TRIAGE = SKILLS / "github-issue-triage" / "scripts" / "triage_state.py"
WATCH = SKILLS / "github-ship-watch" / "scripts" / "watch_state.py"
REPO = ("o", "r")
HOME = "acme/product"
BOT = "shipmill-app[bot]"
QUESTION = "<!-- shipmill:needs-decision -->\n@amy which repo owns the index?"
NO_HOME = "no coordinator: waits for the maintainer"


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load("triage_state_upstream", TRIAGE)


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("watch_state_upstream", WATCH)


def said(body: str, who: str = "amy", association: str = "OWNER", bot: bool = False) -> dict[str, Any]:
    author = {"__typename": "Bot" if bot else "User", "login": who.removesuffix("[bot]") if bot else who}
    return {**comment(body), "author": author, "authorAssociation": association}


def report(
    *comments: dict[str, Any], labels: tuple[str, ...] = ("upstream",), author: str = "amy", association: str = "OWNER"
) -> dict[str, Any]:
    """Issue #5, opened by ``author``, with ``labels``"""
    item = open_issue(5, list(comments), labels=labels)
    item["author"] = {"__typename": "User", "login": author}
    item["authorAssociation"] = association
    return item


def node(ref: str, state: str = "OPEN", reason: str | None = None) -> dict[str, Any]:
    repo, _, number = ref.partition("#")
    return {"number": int(number), "state": state, "stateReason": reason, "repository": {"nameWithOwner": repo}}


def state_of(ts: ModuleType, item: dict[str, Any], home: str | None = None, trusted_only: bool = False) -> Any:
    gated = ts.gated(item, BOT, trusted_only, home)
    return gated or ts.classify_open(item, "Triage:", "postponed", {}, None, REPO, BOT)


# -- S-038-13 ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "item",
    [
        report(),  # untriaged: would read NEW
        report(comment("Triage: implement")),  # would read NEEDS_PR
        report(said(QUESTION, BOT, "NONE", bot=True), labels=("upstream", "needs-decision")),  # NEEDS_DECISION
        report(said(QUESTION, BOT, "NONE", bot=True), said("acme/api"), labels=("upstream", "needs-decision")),
        report(comment("Triage: implement"), labels=("upstream", "blocked")),  # BLOCKED
        report(comment("Triage: implement"), labels=("upstream", "postponed")),  # POSTPONED
        report(labels=("upstream", "human")),  # NO_ASSIGNEE
    ],
)
def test_s038_13_an_upstream_report_reads_upstream_whatever_else_it_would(ts: ModuleType, item: dict[str, Any]) -> None:
    assert state_of(ts, item)[0] == "UPSTREAM"
    assert state_of(ts, item, HOME)[0] == "UPSTREAM"
    assert "UPSTREAM" not in ts.ACTION


def test_s038_13_holds_and_children_never_move_an_upstream_report(ts: ModuleType) -> None:
    item = report(comment("Triage: implement"), comment("On hold: waits on #3"))
    item["body"] = "Depends on #3\n"
    item["blockedBy"] = forward([node("o/r#3")])
    item["subIssues"] = forward([node("acme/api#9", "CLOSED", "COMPLETED")])
    item["timelineItems"] = forward([{"willCloseTarget": True, "source": {"number": 8, "state": "OPEN"}}])
    assert state_of(ts, item) == ("UPSTREAM", NO_HOME)


def test_s038_13_untrusted_is_read_first(ts: ModuleType) -> None:
    item = report(author="eve", association="NONE")
    assert state_of(ts, item, HOME, trusted_only=True) == ("UNTRUSTED", "opened by @eve (none)")
    assert state_of(ts, item, HOME)[0] == "UPSTREAM"  # without --trusted-only, trust isn't read
    trusted = report(labels=("upstream", "needs-decision"))
    assert state_of(ts, trusted, HOME, trusted_only=True)[0] == "UPSTREAM"


FAKE_GH = """#!{python}
import os
print(open(os.environ["FAKE_GH_DATA"]).read())
"""


def run_triage(tmp_path: Path, nodes: list[dict[str, Any]], *args: str) -> subprocess.CompletedProcess[str]:
    """triage_state.py over a fake gh that answers every query with one first page"""
    fakes = tmp_path / "fakes"
    fakes.mkdir(exist_ok=True)
    gh = fakes / "gh"
    gh.write_text(FAKE_GH.format(python=sys.executable), encoding="utf-8")
    gh.chmod(0o700)
    data = tmp_path / "gh.json"
    data.write_text(json.dumps({"data": {"repository": first_page(nodes)}}), encoding="utf-8")
    env = {"PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]), "FAKE_GH_DATA": str(data)}
    cmd = [sys.executable, str(TRIAGE), "o/r", "--json", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)


def test_s038_13_a_repo_whose_only_open_issue_reads_upstream_exits_0(tmp_path: Path) -> None:
    proc = run_triage(tmp_path, [report()], "--home", HOME)
    assert proc.returncode == 0, proc.stderr
    assert [json.loads(line) for line in proc.stdout.splitlines()] == [
        {"number": 5, "state": "UPSTREAM", "title": "issue 5", "note": f"routed by {HOME}"}
    ]
    # the same issue without the label reads NEW, an action
    assert run_triage(tmp_path, [report(labels=())]).returncode == 1


# -- S-038-14 ------------------------------------------------------------------------------


def test_s038_14_the_note_names_the_coordinator_or_the_maintainer(ts: ModuleType) -> None:
    assert state_of(ts, report(), HOME) == ("UPSTREAM", "routed by acme/product")
    assert state_of(ts, report()) == ("UPSTREAM", "no coordinator: waits for the maintainer")


def test_s038_14_a_question_with_no_reply_asks_the_maintainer(ts: ModuleType) -> None:
    labels = ("upstream", "needs-decision")
    asked = report(said(QUESTION, BOT, "NONE", bot=True), labels=labels)
    assert state_of(ts, asked, HOME) == ("UPSTREAM", "routed by acme/product, asks the maintainer")
    assert state_of(ts, asked) == ("UPSTREAM", f"{NO_HOME}, asks the maintainer")
    # a trusted reply answers it: the report still waits outside, and no longer asks
    answered = report(said(QUESTION, BOT, "NONE", bot=True), said("acme/api owns it"), labels=labels)
    assert state_of(ts, answered, HOME) == ("UPSTREAM", "routed by acme/product")
    # an outsider's comment is no reply
    outsider = report(said(QUESTION, BOT, "NONE", bot=True), said("me!", "eve", "NONE"), labels=labels)
    assert state_of(ts, outsider, HOME)[1].endswith(", asks the maintainer")
    # a question without the needs-decision label asks nothing
    unlabelled = report(said(QUESTION, BOT, "NONE", bot=True))
    assert state_of(ts, unlabelled, HOME) == ("UPSTREAM", "routed by acme/product")


@pytest.mark.parametrize("home", ["acme", "acme/", "/product", "a/b/c", "acme/pro duct", "../x", "acme/..", ""])
def test_s038_14_a_malformed_home_exits_2(tmp_path: Path, home: str) -> None:
    proc = run_triage(tmp_path, [report()], "--home", home)
    assert proc.returncode == 2
    assert "--home must be owner/name" in proc.stderr


# -- S-038-15 ------------------------------------------------------------------------------


def line(number: int, state: str, note: str = "") -> str:
    return json.dumps({"number": number, "state": state, "title": "t", "note": note})


def test_s038_15_the_watch_passes_the_product_home_as_home(ws: ModuleType, tmp_path: Path) -> None:
    policy = tmp_path / "shipmill.toml"
    text = '[agents]\nprompt = "x"\n\n[product]\nhome = "acme/product"\n'
    assert ws.product_home(text, policy) == HOME
    assert ws.product_home_310(text, policy) == HOME
    cmd = ws.triage_command("o/r", BOT, True, ws.product_home(text, policy))
    assert cmd[-2:] == ["--home", HOME]
    # no [product], or a home repo's table (repos, no home): no --home, the command as before
    for plain in ('[agents]\nprompt = "x"\n', '[product]\nrepos = [\n  "acme/api",\n  "acme/web",\n]\n'):
        assert ws.product_home(plain, policy) is None
        assert ws.product_home_310(plain, policy) is None
    assert ws.triage_command("o/r", BOT, True) == [sys.executable, str(TRIAGE), "o/r", "--json"] + [
        "--bot-login",
        BOT,
        "--trusted-only",
    ]


@pytest.mark.parametrize(
    "text",
    [
        '[product]\nhome = "acme"\n',
        '[product]\nhome = "a/b/c"\n',
        "[product]\nhome = 7\n",
        'product = "acme/product"\n',
    ],
)
def test_s038_15_a_malformed_home_is_refused(ws: ModuleType, tmp_path: Path, text: str) -> None:
    with pytest.raises(ws.Refused) as refused:
        ws.product_home(text, tmp_path / "shipmill.toml")
    assert refused.value.code == 2
    with pytest.raises(ws.Refused):
        ws.product_home_310(text, tmp_path / "shipmill.toml")


@pytest.mark.parametrize("text", ['[[product]]\nhome = "acme/product"\n', '[product]\nhome.x = "acme/product"\n'])
def test_s038_15_a_home_tomllib_refuses_is_refused_on_310_too(ws: ModuleType, tmp_path: Path, text: str) -> None:
    with pytest.raises(ws.Refused):
        ws.product_home(text, tmp_path / "shipmill.toml")
    with pytest.raises(ws.Refused, match=r"\[product\]"):
        ws.product_home_310(text, tmp_path / "shipmill.toml")


@pytest.mark.parametrize(
    "text",
    ['[product\nhome = "acme/product"\n', '[product.x]\nhome = "acme/product"\n', 'product.home = "acme/product"\n'],
)
def test_s038_15_the_310_reader_refuses_a_form_it_cant_read(ws: ModuleType, tmp_path: Path, text: str) -> None:
    with pytest.raises(ws.Refused, match=r"\[product\]"):
        ws.product_home_310(text, tmp_path / "shipmill.toml")


def test_s038_15_an_upstream_report_is_listed_in_issues_open_only(ws: ModuleType) -> None:
    triage = "\n".join([line(5, "UPSTREAM", "routed by acme/product, asks the maintainer"), line(9, "BLOCKED")])
    rows = ws.intake("o/r", 0, triage, [], lambda n: [], BOT, True)
    assert [(r.state, r.detail) for r in rows] == [("ISSUES_OPEN", "BLOCKED #9; UPSTREAM #5")]
    assert not any(r.json()["agent"] for r in rows)
    # with an action beside it, the report stays out of ISSUES
    rows = ws.intake("o/r", 1, "\n".join([triage, line(12, "NEW")]), [], lambda n: [], BOT, True)
    assert [(r.state, r.detail) for r in rows] == [
        ("ISSUES", "NEW #12"),
        ("ISSUES_OPEN", "BLOCKED #9; UPSTREAM #5"),
    ]


def test_s038_15_the_gate_starts_no_session_for_a_lone_upstream_report(ws: ModuleType) -> None:
    rows = ws.intake("o/r", 0, line(5, "UPSTREAM", "routed by acme/product"), [], lambda n: [], BOT, True)
    printed = "\n".join(json.dumps(r.json(), sort_keys=True) for r in rows)
    now = dt.datetime(2026, 10, 24, 12, 0, tzinfo=dt.UTC)
    decision = decide(parse_findings(printed), [], None, now, dt.timedelta(hours=1))
    assert decision.action == Action.QUIET


# -- S-038-16 and S-038-25: holds on a report, and across repos ----------------------------


def waiting(body: str, blocked_by: list[dict[str, Any]]) -> dict[str, Any]:
    """Issue #7, triaged implement, holding on what its body and the forge name"""
    item = open_issue(7, [comment("Triage: implement")])
    item["body"] = body
    item["blockedBy"] = forward(blocked_by)
    item["subIssues"] = forward([])
    return item


@pytest.mark.parametrize("home", [None, HOME])
def test_s038_16_an_issue_holding_on_its_report_reads_blocked_then_unblocked(ts: ModuleType, home: str | None) -> None:
    def read(state: str, reason: str | None) -> Any:
        return state_of(ts, waiting("Depends on #5\n", [node("o/r#5", state, reason)]), home)

    assert read("OPEN", None) == ("BLOCKED", "o/r#5:open")
    assert read("CLOSED", "COMPLETED") == ("UNBLOCKED", "o/r#5:closed")
    state, note = read("CLOSED", "NOT_PLANNED")
    assert (state, note) == ("UNBLOCKED", "o/r#5:not_planned")
    assert "#5:not_planned" in note


@pytest.mark.parametrize("home", [None, HOME])
def test_s038_25_a_hold_on_another_repo_reads_as_spec_017_says(ts: ModuleType, home: str | None) -> None:
    item = waiting("Depends on other/lib#9\n", [])
    assert ts.gated(item, BOT, False, home) is None
    ref = ("other", "lib", 9)

    def read(states: dict[tuple[str, str, int], str]) -> Any:
        return ts.classify_open(item, "Triage:", "postponed", states, None, REPO, BOT)

    assert read({ref: "OPEN"}) == ("BLOCKED", "other/lib#9:open")
    assert read({}) == ("BLOCKED", "other/lib#9:?")  # unreadable counts as open
    assert read({ref: "UNKNOWN"}) == ("BLOCKED", "other/lib#9:unknown")
    assert read({ref: "CLOSED"}) == ("UNBLOCKED", "other/lib#9:closed")
    # a native relation naming another repo's issue holds the same way
    native = waiting("", [node("other/lib#9")])
    assert state_of(ts, native, home) == ("BLOCKED", "other/lib#9:open(native)")
    closed = waiting("", [node("other/lib#9", "CLOSED", "COMPLETED")])
    assert state_of(ts, closed, home) == ("UNBLOCKED", "other/lib#9:closed(native)")


# -- S-038-17 ------------------------------------------------------------------------------


def closed_report(closer: dict[str, Any] | None, reason: str = "COMPLETED") -> dict[str, Any]:
    return {
        "number": 5,
        "title": "Index missing on acme/api",
        "stateReason": reason,
        "body": "",
        "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": "upstream"}]},
        "comments": {"nodes": []},
        "refs": forward([]),
        "timelineItems": {"nodes": [{"createdAt": "2026-10-20T10:00:00Z", "actor": None, "closer": closer}]},
    }


@pytest.mark.parametrize(
    ("closer", "reason"),
    [
        (None, "COMPLETED"),  # by hand, no merged PR mentions it
        (None, "NOT_PLANNED"),
        ({"__typename": "PullRequest", "number": 8, "merged": False}, "COMPLETED"),
        ({"__typename": "Commit", "abbreviatedOid": "b3e999f", "message": "Quote: closes #5 mid-line"}, "COMPLETED"),
    ],
)
def test_s038_17_a_closed_upstream_report_is_never_a_suspect_close(
    ts: ModuleType, closer: dict[str, Any] | None, reason: str
) -> None:
    item = closed_report(closer, reason)
    assert ts.classify_closed(item, "release-blocker", "incident", BOT) is None
    assert ts.classify_closed(item, "release-blocker") is None
    # the same close of an issue without the label is suspect (a not-planned close never is)
    item["labels"]["nodes"] = []
    expected = None if reason == "NOT_PLANNED" else "SUSPECT_CLOSE"
    assert (ts.classify_closed(item, "release-blocker") or (None,))[0] == expected
