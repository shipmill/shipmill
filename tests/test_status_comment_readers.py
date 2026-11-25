"""Spec 090, The status comment: no reader reads it. triage_state.py, upstream_state.py,
watch_state.py (open_hold included), and pr_gate.py read the same state for an item with and
without a status comment holding every line they key on, wherever it sits in the thread
(S-090-6), and none of them dates or orders a comment by its updatedAt or lastEditedAt (S-090-7).
Every reader runs on GitHub's answers as fixtures; pr_gate.py runs end to end with a stand-in gh"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_pr_gate import (
    DIRECTION,
    HEAD_SHA,
    MAIN_READY,
    REVIEW,
    asked,
    at,
    checkout,
    headed,
    protected,
    relay,
    thread,
)
from .test_pr_gate import comment as pr_comment

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
SCRIPTS = SKILLS / "github-issue-triage" / "scripts"
READERS = {
    "triage_state.py": SCRIPTS / "triage_state.py",
    "upstream_state.py": SCRIPTS / "upstream_state.py",
    "watch_state.py": SKILLS / "github-ship-watch" / "scripts" / "watch_state.py",
    "pr_gate.py": SKILLS / "github-pr-triage" / "scripts" / "pr_gate.py",
}
REPO = ("o", "r")
BOT = "shipmill-o[bot]"
AGENT = "<!-- shipmill:agent -->"
STATUS_MARKER = "<!-- shipmill:status -->"
QUESTION = "<!-- shipmill:needs-decision -->\n@amy Decision needed: which flag?\n\n1. --x (recommended)\n2. --y"
DECIDED = "<!-- shipmill:decided zone=triage-verdict until=2026-10-21T10:00:00Z -->\n@amy Decided: close as a duplicate"
RELAY = "Decision by `@amy`, relayed by Claude Code\n\n1"
# Every line the readers key on, each on a line of the status text: a verdict, a hold sentence
# naming an open issue, a relay, an answer, a veto, a done report, and each first-line marker
KEYED = [
    "Triage: **implement**",
    "On hold: waits on #12.",
    "Blocked by o/r#13, waiting on #14",
    "Decision by @amy, relayed by Claude Code",
    "",
    "Answered in the session: 1. --x",
    "1",
    "own: veto",
    "veto",
    "Veto: keep it open",
    "done",
    "Done: my part is finished",
    "<!-- shipmill:needs-decision -->",
    "<!-- shipmill:decided zone=scope until=2026-10-21T10:00:00Z -->",
    "<!-- shipmill:veto-handled zone=scope -->",
    "<!-- shipmill:handoff -->",
    "<!-- shipmill:still-waits -->",
    "<!-- shipmill:check-failed -->",
    "<!-- shipmill:check-waiting -->",
    "@amy runs the check",
    "<!-- shipmill:verified -->",
    "<!-- shipmill:close-confirmed -->",
    "<!-- shipmill:withdrawn -->",
    "<!-- shipmill:reverted pr=3 revert=4 -->",
    "<!-- shipmill:relay-refused format -->",
    f"<!-- shipmill:head {HEAD_SHA} -->",
    "Revisit on: src/never.py",
]
STATUS = f"{STATUS_MARKER}\nUpdated 2026-10-20 12:00 UTC\n\n" + "\n".join(KEYED) + f"\n\n{AGENT}"
LATER = "2026-12-31T23:59:00Z"  # an edit after everything else in a thread


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load("status_comment_triage_state", READERS["triage_state.py"])


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("status_comment_watch_state", READERS["watch_state.py"])


@pytest.fixture(scope="module")
def us() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))  # it imports chains and triage_state, as when run from its folder
    try:
        return load("status_comment_upstream_state", READERS["upstream_state.py"])
    finally:
        sys.path.remove(str(SCRIPTS))


def author(login: str | None) -> dict[str, str] | None:
    """GraphQL's author: a Bot's login comes without "[bot]" """
    if login is None:
        return None
    if login.endswith("[bot]"):
        return {"__typename": "Bot", "login": login.removesuffix("[bot]")}
    return {"__typename": "User", "login": login}


def said(body: str, when: str, by: str = "amy", association: str = "OWNER") -> dict[str, Any]:
    return {"body": body, "createdAt": when, "author": author(by), "authorAssociation": association}


def by_bot(body: str, when: str) -> dict[str, Any]:
    """The App's comment, carrying the agent marker: GraphQL gives it no trusted association"""
    return said(f"{body}\n\n{AGENT}", when, BOT, "NONE")


def day(n: int) -> str:
    return f"2026-10-{n:02d}T10:00:00Z"


def issue(*comments: dict[str, Any], labels: tuple[str, ...] = (), **extra: Any) -> dict[str, Any]:
    """An open issue #7 as triage_state.py's query returns it, comments oldest first"""
    return {
        "number": 7,
        "title": "t",
        "body": "",
        "author": author("amy"),
        "authorAssociation": "OWNER",
        "labels": {"nodes": [{"name": n} for n in labels]},
        "assignees": {"nodes": [{"login": "amy"}]},
        "comments": {"nodes": list(comments)},
        "timelineItems": {"nodes": []},
        **extra,
    }


def placed(comments: list[dict[str, Any]], status: dict[str, Any]) -> Iterator[list[dict[str, Any]]]:
    """comments with the status comment at each place in the thread, first to last; its
    createdAt is its place's, as GitHub orders a thread by creation"""
    for at_ in range(len(comments) + 1):
        before = comments[at_ - 1]["createdAt"] if at_ else "2026-09-01T10:00:00Z"
        yield [*comments[:at_], {**status, "createdAt": before}, *comments[at_:]]


def with_status(item: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """item with the App's status comment at each place in its thread"""
    for nodes in placed(item["comments"]["nodes"], by_bot(STATUS.removesuffix(f"\n\n{AGENT}"), day(1))):
        yield {**item, "comments": {"nodes": nodes}}


STABLE = (dt.datetime(2026, 10, 15, tzinfo=dt.UTC), "v1.0.0")
HOLDS = {("o", "r", 12): "OPEN", ("o", "r", 13): "OPEN", ("o", "r", 14): "OPEN"}


def state(ts: ModuleType, item: dict[str, Any], bot_login: str | None, **kw: Any) -> tuple[str, str]:
    """As triage_state.py's main reads an open issue"""
    found: tuple[str, str] = ts.gated(item, bot_login, False) or ts.classify_open(
        item, "Triage:", "postponed", kw.get("states", {}), kw.get("stable"), REPO, bot_login, kw.get("closes")
    )
    return found


# The items S-090-6 reads, each with the state it reads without a status comment
ITEMS: dict[str, tuple[dict[str, Any], dict[str, Any], tuple[str, str]]] = {
    "new": (issue(said("Thanks for the report", day(2), "eve", "NONE")), {}, ("NEW", "")),
    "needs a pull request": (issue(by_bot("Triage: **implement**", day(2))), {}, ("NEEDS_PR", "")),
    "held on an open issue": (
        # the hold line beside the link it records (spec 041, #1645): a hold is a link
        issue(by_bot("Triage: **implement**\n\nOn hold: waits on #12.", day(2)), body="Depends on #12"),
        {"states": HOLDS},
        ("BLOCKED", "o/r#12:open"),
    ),
    "unblocked": (
        issue(by_bot("Triage: **implement**", day(2))),
        {"states": HOLDS},
        ("NEEDS_PR", ""),
    ),
    "waiting on a reply": (
        issue(by_bot("Triage: **implement**", day(2)), by_bot(QUESTION, day(3)), labels=("needs-decision",)),
        {},
        ("NEEDS_DECISION", "waits on a reply"),
    ),
    "answered": (
        issue(by_bot(QUESTION, day(3)), said("go with 1", day(4)), labels=("needs-decision",)),
        {},
        ("DECIDED", "answered by @amy"),
    ),
    "decided, not vetoed": (
        issue(by_bot("Triage: **implement**", day(2)), by_bot(DECIDED, day(3)), labels=("decided",)),
        {},
        ("NEEDS_PR", ""),
    ),
    "vetoed": (
        issue(by_bot(DECIDED, day(3)), said("Veto: keep it open", day(4)), labels=("decided",)),
        {},
        ("VETOED", "vetoed by @amy"),
    ),
    "relayed after the verdict": (
        issue(by_bot(QUESTION, day(2)), by_bot("Triage: **implement**", day(3)), by_bot(RELAY, day(4))),
        {},
        ("DECIDED", "answered by @amy, relayed"),
    ),
    "postponed before the stable tag": (
        issue(by_bot("Triage: **postponed** to the next minor", day(2)), labels=("postponed",)),
        {"stable": STABLE},
        ("REVISIT", "postponed before v1.0.0"),
    ),
    "a person's item to hand off": (
        issue(labels=("human",)),
        {},
        ("HANDOFF_DUE", "for @amy"),
    ),
    "a person's item handed off": (
        issue(by_bot("<!-- shipmill:handoff -->\n@amy it is yours", day(3)), labels=("human",)),
        {},
        ("WITH_PERSON", f"with @amy since {day(3)}"),
    ),
}


@pytest.mark.parametrize("bot_login", [BOT, None])
@pytest.mark.parametrize("name", list(ITEMS))
def test_s090_6_triage_state_reads_the_same_state_and_note_with_a_status_comment(
    ts: ModuleType, name: str, bot_login: str | None
) -> None:
    item, kw, expected = ITEMS[name]
    if bot_login is None:
        expected = state(ts, item, None, **kw)  # without --bot-login the App's comment reads as it does today
    assert state(ts, item, bot_login, **kw) == expected
    for placed_item in with_status(item):
        assert state(ts, placed_item, bot_login, **kw) == expected, placed_item["comments"]["nodes"]


def test_s090_6_a_status_comment_holds_nothing_wherever_it_sits(ts: ModuleType) -> None:
    """hold_refs skips a comment whose first line is the status marker: its "waits on #12" is a
    session's progress (spec 090), while the same line in any other comment holds"""
    plain = by_bot("Triage: **implement**", day(2))
    for item in with_status(issue(plain)):
        assert ts.hold_refs(item, REPO) == {}
    held = issue(plain, by_bot("On hold: waits on #12.", day(3)))
    assert set(ts.hold_refs(held, REPO)) == {("o", "r", 12)}
    for item in with_status(held):
        assert set(ts.hold_refs(item, REPO)) == {("o", "r", 12)}


@pytest.mark.parametrize("bot_login", [BOT, None])
@pytest.mark.parametrize(
    ("comments", "expected"),
    [
        ([], ("VERIFY_DUE", "children 1/1 closed: run its ## Check")),
        (
            [by_bot("<!-- shipmill:check-waiting -->\n`@bob` runs it", day(21))],
            ("WITH_PERSON", f"check waiting on @bob since {day(21)} children 1/1 closed"),
        ),
        (
            [by_bot("<!-- shipmill:check-failed -->\nthe page is blank", day(21))],
            ("CHECK_FAILED", f"check failed {day(21)} children 1/1 closed"),
        ),
    ],
)
def test_s090_6_a_parents_check_reads_the_same_with_a_status_comment(
    ts: ModuleType, comments: list[dict[str, Any]], expected: tuple[str, str], bot_login: str | None
) -> None:
    ends = [day(20)]
    if bot_login is None and comments:  # without --bot-login the App's marker is no trusted author's
        expected = ts.parent_check(comments, None, ends, "children 1/1 closed")
    assert ts.parent_check(comments, bot_login, ends, "children 1/1 closed") == expected
    status = by_bot(STATUS.removesuffix(f"\n\n{AGENT}"), day(1))
    for nodes in placed(comments, status):
        assert ts.parent_check(nodes, bot_login, ends, "children 1/1 closed") == expected
    # a status comment written after the newest close, where a check marker would count
    assert ts.parent_check([*comments, {**status, "createdAt": day(23)}], bot_login, ends, "children 1/1 closed") == (
        expected
    )


# -- upstream_state.py


def report(*comments: dict[str, Any], labels: tuple[str, ...] = ("upstream",), body: str = "") -> dict[str, Any]:
    return {
        "number": 3,
        "body": body,
        "labels": {"nodes": [{"name": n} for n in labels]},
        "comments": {"nodes": list(comments)},
    }


CHILD = ("acme", "api", 9)


@pytest.mark.parametrize(
    ("item", "kids", "expected"),
    [
        (report(), {}, ("ROUTE_DUE", "no children")),
        (
            report(by_bot(QUESTION, day(3)), labels=("upstream", "needs-decision")),
            {},
            ("ASKED", "waits on a reply"),
        ),
        (
            report(by_bot(QUESTION, day(3)), said("1", day(4)), labels=("upstream", "needs-decision")),
            {},
            ("ANSWERED", "answered by @amy"),
        ),
        (report(), {CHILD: ("OPEN", None)}, ("ROUTED", "children 0/1 closed acme/api#9:open")),
        (report(), {CHILD: ("CLOSED", day(20))}, ("CLOSE_DUE", "completed, children 1/1 closed acme/api#9:closed")),
        (
            report(body="Fix it\n\n## Check\n\n`curl` shows it\n"),
            {CHILD: ("CLOSED", day(20))},
            ("VERIFY_DUE", "children 1/1 closed acme/api#9:closed: run its ## Check"),
        ),
        (
            report(by_bot("<!-- shipmill:check-failed -->\nblank", day(21)), body="## Check\n\n`curl`\n"),
            {CHILD: ("CLOSED", day(20))},
            ("CHECK_FAILED", f"check failed {day(21)} children 1/1 closed acme/api#9:closed"),
        ),
    ],
)
def test_s090_6_upstream_state_reads_the_same_with_a_status_comment(
    us: ModuleType, item: dict[str, Any], kids: dict[Any, Any], expected: tuple[str, str]
) -> None:
    assert us.classify(item, kids, BOT) == expected
    for nodes in placed(item["comments"]["nodes"], by_bot(STATUS.removesuffix(f"\n\n{AGENT}"), day(1))):
        assert us.classify({**item, "comments": {"nodes": nodes}}, kids, BOT) == expected
    assert us.decision(item, BOT) == (expected if expected[0] in ("ASKED", "ANSWERED") else None)


# -- watch_state.py


def tuples(comments: list[dict[str, Any]], ts: ModuleType) -> list[tuple[str, str, str]]:
    """The comments as REST reads a pull request's: (login, author association, body)"""
    return [(ts.login(c["author"]), c["authorAssociation"], c["body"]) for c in comments]


@pytest.mark.parametrize(
    ("comments", "expected"),
    [
        ([], None),
        ([by_bot("On hold: waits on #12.", day(3))], "o/r#12"),
        ([by_bot("Rebased", day(3))], None),
    ],
)
def test_s090_6_open_hold_on_an_agents_draft_reads_the_same_with_a_status_comment(
    ts: ModuleType, ws: ModuleType, comments: list[dict[str, Any]], expected: str | None
) -> None:
    def holds(wanted: set[tuple[str, str, int]]) -> dict[tuple[str, str, int], str]:
        return {r: HOLDS.get(r, "CLOSED") for r in wanted}

    assert ws.open_hold(tuples(comments, ts), "o/r", 4, holds) == expected
    for nodes in placed(comments, by_bot(STATUS.removesuffix(f"\n\n{AGENT}"), day(1))):
        assert ws.open_hold(tuples(nodes, ts), "o/r", 4, holds) == expected


def no_prs(number: int) -> list[tuple[str, str, str]]:
    raise AssertionError(f"read the comments of #{number}")


@pytest.mark.parametrize("name", ["new", "needs a pull request", "held on an open issue", "waiting on a reply"])
def test_s090_6_watch_states_intake_rows_read_the_same_with_a_status_comment(
    ts: ModuleType, ws: ModuleType, name: str
) -> None:
    item, kw, _ = ITEMS[name]

    def rows(found: dict[str, Any]) -> dict[str, str]:
        line = json.dumps({"number": 7, "state": state(ts, found, BOT, **kw)[0], "title": "t", "note": ""})
        code = 1 if state(ts, found, BOT, **kw)[0] in ts.ACTION else 0
        return {r.state: r.detail for r in ws.intake("o/r", code, line, [], no_prs, BOT)}

    expected = rows(item)
    for placed_item in with_status(item):
        assert rows(placed_item) == expected


@pytest.mark.parametrize("answered", [False, True])
def test_s090_6_watch_state_reads_a_pull_requests_question_the_same_with_a_status_comment(
    ts: ModuleType, ws: ModuleType, answered: bool
) -> None:
    pr = {"number": 4, "isDraft": False, "isCrossRepository": False, "labels": [{"name": "needs-decision"}]}
    pr["headRefOid"] = f"{4:040x}"
    comments = [by_bot(QUESTION, day(3)), *([said("1", day(4))] if answered else [])]

    def rows(nodes: list[dict[str, Any]]) -> dict[str, str]:
        return {r.state: r.detail for r in ws.intake("o/r", 0, "", [pr], lambda n: tuples(nodes, ts), BOT)}

    expected = rows(comments)
    assert ("PRS_OPEN" if answered else "NEEDS_DECISION") in expected
    for nodes in placed(comments, by_bot(STATUS.removesuffix(f"\n\n{AGENT}"), day(1))):
        assert rows(nodes) == expected


# -- pr_gate.py, end to end


def gate_status(when: str, edited: str | None = None) -> dict[str, Any]:
    """The App's status comment on the pull request, as GraphQL lists it; edited adds a later
    updatedAt and lastEditedAt"""
    found = pr_comment(STATUS, when, login="shipmill-demo", association="NONE", bot=True)
    return {**found, "updatedAt": edited, "lastEditedAt": edited} if edited else found


@pytest.fixture
def directed(tmp_path: Path) -> Path:
    return checkout(tmp_path, {"docs/product.md": DIRECTION, "REVIEW.md": REVIEW})


PR_THREADS = {
    "asked": [asked()],
    "answered": [asked(), pr_comment("1", at(12))],
    "relayed": [asked(), relay("Decision by `@romamo`", "1")],
    "decided": [
        pr_comment(DECIDED.replace("@amy", "`@romamo`"), at(11), "shipmill-demo", "NONE", True),
        asked(at(11, 30)),
        pr_comment("1", at(12)),
    ],
}


@pytest.mark.parametrize("name", list(PR_THREADS))
def test_s090_6_pr_gate_reads_the_same_verdict_with_a_status_comment(tmp_path: Path, name: str) -> None:
    comments = PR_THREADS[name]
    outs = []
    where = [0, len(comments)] if name == "asked" else [0, 1, len(comments)]
    for index, at_ in enumerate([None, *where]):
        run = tmp_path / f"run{index}"
        run.mkdir()
        work = checkout(run, {"docs/product.md": DIRECTION, "REVIEW.md": REVIEW})
        nodes = list(comments)
        if at_ is not None:
            before = comments[at_ - 1]["createdAt"] if at_ else at(10, 30)
            nodes.insert(at_, gate_status(before))
        proc = protected(run, work, headed(files=("src/land.py",)), thread(*nodes))
        outs.append((proc.returncode, proc.stdout))
    expected = (5, None) if name == "asked" else (0, MAIN_READY)
    assert outs[0][0] == expected[0] and (expected[1] is None or outs[0][1] == expected[1]), outs[0]
    assert all(out == outs[0] for out in outs), outs


# -- S-090-7: no reader dates or orders a comment by its edit


def edited(comment: dict[str, Any]) -> dict[str, Any]:
    return {**comment, "updatedAt": LATER, "lastEditedAt": LATER}


@pytest.mark.parametrize("name", list(ITEMS))
def test_s090_7_a_later_edit_of_any_comment_leaves_triage_states_reading_as_it_was(ts: ModuleType, name: str) -> None:
    item, kw, expected = ITEMS[name]
    for placed_item in with_status(item):
        nodes = placed_item["comments"]["nodes"]
        for i in range(len(nodes)):
            changed = [edited(c) if j == i else c for j, c in enumerate(nodes)]
            assert state(ts, {**placed_item, "comments": {"nodes": changed}}, BOT, **kw) == expected


def test_s090_7_a_relay_after_the_verdict_still_reads_decided_when_the_verdict_is_edited_later(
    ts: ModuleType,
) -> None:
    question = by_bot(QUESTION, day(2))
    verdict = by_bot("Triage: **implement**", day(3))
    relayed = by_bot(RELAY, day(4))
    status = by_bot(STATUS.removesuffix(f"\n\n{AGENT}"), day(1))
    for nodes in ([question, verdict, relayed], [question, status, verdict, relayed]):
        item = issue(*[edited(c) if c is not relayed else c for c in nodes])
        assert state(ts, item, BOT) == ("DECIDED", "answered by @amy, relayed")
    # and a verdict that took the relay up reads as taken up, whenever the status was edited
    taken = issue(question, status, relayed, by_bot("Triage: **implement**", day(5)))
    assert state(ts, taken, BOT) == ("NEEDS_PR", "")
    assert state(ts, issue(*[edited(c) for c in taken["comments"]["nodes"]]), BOT) == ("NEEDS_PR", "")


def test_s090_7_a_postponed_verdict_edited_after_the_stable_tag_still_reads_revisit(ts: ModuleType) -> None:
    verdict = by_bot("Triage: **postponed** to the next minor", day(2))
    status = by_bot(STATUS.removesuffix(f"\n\n{AGENT}"), day(1))
    for nodes in ([edited(verdict)], [edited(status), edited(verdict)], [verdict, edited(status)]):
        item = issue(*nodes, labels=("postponed",))
        assert state(ts, item, BOT, stable=STABLE) == ("REVISIT", "postponed before v1.0.0")


def test_s090_7_a_hold_closed_before_the_verdict_stays_taken_up_when_the_verdict_is_edited_later(
    ts: ModuleType,
) -> None:
    """#1493: a hold that closed before the verdict was written holds nothing, whenever the
    verdict was last edited"""
    hold = by_bot("On hold: waits on #12.", day(2))
    verdict = by_bot("Triage: **implement**", day(5))
    kw = {"states": {("o", "r", 12): "CLOSED"}, "closes": {("o", "r", 12): day(4)}}
    for nodes in ([hold, verdict], [hold, edited(verdict)], [hold, by_bot(STATUS, day(3)), edited(verdict)]):
        assert state(ts, issue(*nodes), BOT, **kw) == ("NEEDS_PR", "")


def test_s090_7_upstream_and_watch_readers_ignore_a_later_edit(ts: ModuleType, us: ModuleType, ws: ModuleType) -> None:
    status = by_bot(STATUS.removesuffix(f"\n\n{AGENT}"), day(5))
    asked_ = by_bot(QUESTION, day(3))
    answer = said("1", day(4))
    item = report(edited(asked_), answer, edited(status), labels=("upstream", "needs-decision"))
    assert us.classify(item, {}, BOT) == ("ANSWERED", "answered by @amy")
    checked = report(edited(by_bot("<!-- shipmill:check-failed -->\nblank", day(19))), body="## Check\n\n`x`\n")
    # a check-failed comment written before the child closed stays before it, whenever it was edited
    assert us.classify(checked, {CHILD: ("CLOSED", day(20))}, BOT)[0] == "VERIFY_DUE"
    pr = {"number": 4, "isDraft": False, "isCrossRepository": False, "labels": [{"name": "needs-decision"}]}
    pr["headRefOid"] = f"{4:040x}"
    nodes = tuples([edited(asked_), answer, edited(status)], ts)
    rows = {r.state: r.detail for r in ws.intake("o/r", 0, "", [pr], lambda n: nodes, BOT)}
    assert "PRS_OPEN" in rows and "NEEDS_DECISION" not in rows


def test_s090_7_pr_gate_ignores_a_later_edit_of_the_question_and_the_status(tmp_path: Path, directed: Path) -> None:
    question = {**asked(), "updatedAt": LATER, "lastEditedAt": LATER}
    nodes = [gate_status(at(10, 30), LATER), question, pr_comment("1", at(12)), gate_status(at(13), LATER)]
    proc = protected(tmp_path, directed, headed(files=("src/land.py",)), thread(*nodes))
    assert (proc.returncode, proc.stdout) == (0, MAIN_READY), proc.stdout + proc.stderr


# The GraphQL selections of an item's comments: "comments(...) { ... nodes { <fields> } }"
COMMENT_NODES = re.compile(r"comments\([^)]*\)\s*\{.*?nodes\s*\{(?P<fields>[^}]*)", re.DOTALL)


@pytest.mark.parametrize("name", list(READERS))
def test_s090_7_no_reader_asks_github_for_a_comments_edit_time(name: str) -> None:
    text = READERS[name].read_text(encoding="utf-8")
    if name == "pr_gate.py":
        # save S-085-13 (D-106): edited_since reads lastEditedAt once, and only allowance calls it
        assert text.count('.get("lastEditedAt")') == 1
        assert text.count("edited_since(") == 2
        assert "any(edited_since(c, issue, opened) for c in counting)" in text
    else:
        assert "lastEditedAt" not in text
    selections = [m["fields"] for m in COMMENT_NODES.finditer(text)]
    assert all("updatedAt" not in fields for fields in selections), selections
