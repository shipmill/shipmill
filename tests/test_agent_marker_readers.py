"""Spec 050, The readers: triage_state.py and watch_state.py tell an agent's comment from a
person's decision by the agent marker, never by its author alone (S-050-8 to S-050-10)"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
REPO = ("o", "r")
BOT = "shipmill-o[bot]"
AGENT = "<!-- shipmill:agent -->"
QUESTION = "<!-- shipmill:needs-decision -->\n@amy Decision needed: which flag?\n\n1. --x (recommended)\n2. --y"
DECIDED = "<!-- shipmill:decided zone=triage-verdict until=2026-10-21T10:00:00Z -->\n@amy Decided: close as a duplicate"
HANDLED = "<!-- shipmill:veto-handled zone=triage-verdict -->\nReopened it, as the veto asks"
VETO = "Veto: keep it open, it is not a duplicate"


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load("agent_marker_triage_state", SKILLS / "github-issue-triage" / "scripts" / "triage_state.py")


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("agent_marker_watch_state", SKILLS / "github-ship-watch" / "scripts" / "watch_state.py")


def marked(body: str) -> str:
    """A body as `shipmill gh` writes it: the text, a blank line, and the agent marker last"""
    return f"{body}\n\n{AGENT}"


def author(login: str | None) -> dict[str, str] | None:
    """GraphQL's author: a Bot's login comes without "[bot]", a deleted account's is null"""
    if login is None:
        return None
    if login.endswith("[bot]"):
        return {"__typename": "Bot", "login": login.removesuffix("[bot]")}
    return {"__typename": "User", "login": login}


def comment(body: str, by: str | None = "amy", association: str = "OWNER") -> dict[str, Any]:
    return {"body": body, "createdAt": "2026-10-20T10:00:00Z", "author": author(by), "authorAssociation": association}


def bot(body: str) -> dict[str, Any]:
    """The App's comment: GraphQL gives it no trusted association"""
    return comment(body, by=BOT, association="NONE")


def issue(*comments: dict[str, Any], labels: tuple[str, ...] = ("needs-decision",)) -> dict[str, Any]:
    """An open issue as triage_state.py's query returns it, comments oldest first"""
    return {
        "number": 7,
        "title": "t",
        "body": "",
        "author": author("amy"),
        "authorAssociation": "OWNER",
        "labels": {"nodes": [{"name": n} for n in labels]},
        "comments": {"nodes": list(comments)},
        "timelineItems": {"nodes": []},
    }


def state(ts: ModuleType, item: dict[str, Any], bot_login: str | None = None) -> tuple[str, str]:
    """As triage_state.py's main reads an open issue"""
    found: tuple[str, str] = ts.gated(item, bot_login, False) or ts.classify_open(
        item, "Triage:", "postponed", {}, None, REPO, bot_login
    )
    return found


def no_prs(number: int) -> list[tuple[str, str, str]]:
    raise AssertionError(f"read the comments of #{number}")


def watch(ts: ModuleType, ws: ModuleType, item: dict[str, Any], bot_login: str | None = None) -> dict[str, str]:
    """watch_state.py's intake rows for a repo whose only issue is ``item``, from triage_state.py's
    line and exit code for it, as its main prints them"""
    found = state(ts, item, bot_login)[0]
    line = json.dumps({"number": item["number"], "state": found, "title": "t", "note": ""})
    code = 1 if found in ts.ACTION else 0
    return {r.state: r.detail for r in ws.intake("o/r", code, line, [], no_prs, bot_login)}


# -- the marker


@pytest.mark.parametrize(
    "body",
    [
        AGENT,
        marked("Triage: implement"),
        f"First line\n   {AGENT}   \nmore text after it",  # any line, stripped
        "<!-- shipmill:agent via=gh -->",  # an attribute reads the same
        "text\r\n<!-- shipmill:agent via=gh session=s1 -->\r\n",
        "<!-- shipmill:agent-->",
    ],
)
def test_s050_8_a_body_carries_the_agent_marker_on_any_line(ts: ModuleType, body: str) -> None:
    assert ts.by_agent(body)


@pytest.mark.parametrize(
    "body",
    [
        "",
        "1",
        "<!-- shipmill:agents -->",  # a look-alike kind
        "<!-- shipmill:agentX -->",
        "<!-- shipmill:agent:x -->",
        f"> {AGENT}",  # quoted
        f"see `{AGENT}`",  # inside a line
        "<!-- shipmill:needs-decision -->",
        "<!-- shipmill:handoff -->",
    ],
)
def test_s050_8_a_look_alike_or_inline_marker_is_no_agent_marker(ts: ModuleType, body: str) -> None:
    assert not ts.by_agent(body)


# -- S-050-8: without --bot-login, an agent's comment is no reply


def test_s050_8_agent_comments_after_the_question_leave_it_waiting(ts: ModuleType) -> None:
    triaged = comment(marked("Triage: implement"))
    shipped = comment(marked("Shipped in v1.2.0"), association="MEMBER")
    via = comment("Linked the spec\n<!-- shipmill:agent via=gh -->", association="COLLABORATOR")
    item = issue(comment(QUESTION), triaged, shipped, via)
    assert ts.gated(item, None, False) == ("NEEDS_DECISION", "waits on a reply")
    # the person's reply, without the marker, decides it
    item["comments"]["nodes"].append(comment("go with 2", by="bob", association="COLLABORATOR"))
    assert ts.gated(item, None, False) == ("DECIDED", "answered by @bob")
    # and an agent comment after the reply leaves it decided, by the person
    item["comments"]["nodes"].append(comment(marked("Working on it")))
    assert ts.gated(item, None, False) == ("DECIDED", "answered by @bob")


def test_s050_8_a_question_carrying_the_agent_marker_is_still_a_question(ts: ModuleType) -> None:
    # the needs-decision marker is read as before: an agent asks on purpose
    item = issue(comment(marked(QUESTION)))
    assert ts.gated(item, None, False) == ("NEEDS_DECISION", "waits on a reply")
    item["comments"]["nodes"].append(comment("1"))
    assert ts.gated(item, None, False) == ("DECIDED", "answered by @amy")


def test_s050_8_watch_state_lists_the_waiting_issue_in_needs_decision_and_the_answered_one_in_issues(
    ts: ModuleType, ws: ModuleType
) -> None:
    waiting = issue(comment(QUESTION), comment(marked("Triage: implement")))
    rows = watch(ts, ws, waiting)
    assert rows["NEEDS_DECISION"] == "#7" and "ISSUES" not in rows
    answered = issue(comment(QUESTION), comment(marked("Triage: implement")), comment("go with 1"))
    rows = watch(ts, ws, answered)
    assert rows["ISSUES"] == "DECIDED #7" and "NEEDS_DECISION" not in rows


def test_s050_8_watch_state_reads_a_pull_requests_question_the_same_way(ws: ModuleType) -> None:
    pr = {"number": 4, "isDraft": False, "isCrossRepository": False, "labels": [{"name": "needs-decision"}]}
    pr["headRefOid"] = f"{4:040x}"
    waiting = [("amy", "OWNER", QUESTION), ("amy", "OWNER", marked("Rebased on main"))]
    rows = {r.state: r.detail for r in ws.intake("o/r", 0, "", [pr], lambda n: waiting)}
    assert rows["NEEDS_DECISION"] == "#4" and "PRS_OPEN" not in rows
    answered = [*waiting, ("amy", "OWNER", "1")]
    rows = {r.state: r.detail for r in ws.intake("o/r", 0, "", [pr], lambda n: answered)}
    assert rows["PRS_OPEN"] == "#4" and "NEEDS_DECISION" not in rows


# -- S-050-9: a marked veto, and a deleted author


@pytest.mark.parametrize("bot_login", [None, BOT])
def test_s050_9_a_veto_carrying_the_agent_marker_is_no_veto(ts: ModuleType, bot_login: str | None) -> None:
    decision = bot(DECIDED) if bot_login else comment(DECIDED, association="MEMBER")
    for association in ("OWNER", "MEMBER", "COLLABORATOR"):
        quoted = comment(marked(VETO), association=association)
        assert state(ts, issue(decision, quoted, labels=("decided",)), bot_login)[0] != "VETOED"
        with_attribute = comment(f"{VETO}\n<!-- shipmill:agent via=gh -->", association=association)
        assert state(ts, issue(decision, with_attribute, labels=("decided",)), bot_login)[0] != "VETOED"
    # the person's unmarked veto still counts
    assert state(ts, issue(decision, comment(VETO), labels=("decided",)), bot_login) == ("VETOED", "vetoed by @amy")


@pytest.mark.parametrize("bot_login", [None, BOT])
@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_s050_9_a_deleted_authors_comment_is_neither_a_reply_nor_a_veto(
    ts: ModuleType, bot_login: str | None, association: str
) -> None:
    asked = bot(QUESTION) if bot_login else comment(QUESTION)
    ghost = comment("go with 1", by=None, association=association)
    assert ts.gated(issue(asked, ghost), bot_login, False) == ("NEEDS_DECISION", "waits on a reply")
    decision = bot(DECIDED) if bot_login else comment(DECIDED, association="MEMBER")
    vetoing = comment(VETO, by=None, association=association)
    assert state(ts, issue(decision, vetoing, labels=("decided",)), bot_login)[0] != "VETOED"
    # GitHub's REST spelling of a deleted account, as watch_state.py's pull request comments read it
    assert not ts.replies(("ghost", association, "1"), bot_login)
    assert not ts.vetoes(("Ghost", association, VETO), bot_login)
    assert ts.waits_on_decision([("amy", "OWNER", QUESTION), ("ghost", association, "1")], None)
    assert ts.vetoed([("amy", "OWNER", DECIDED), ("ghost", association, VETO)], None) is None


def test_s050_9_a_closed_decided_issue_reports_no_marked_or_deleted_authors_veto(ts: ModuleType) -> None:
    for veto in (comment(marked(VETO)), comment(VETO, by=None, association="COLLABORATOR")):
        data = {"vetoable": {"nodes": [{"number": 9, "title": "t", "comments": {"nodes": [bot(DECIDED), veto]}}]}}
        assert ts.closed_rows({**data, "closed": {"nodes": []}}, 20, "release-blocker", "incident", BOT) == []


# -- S-050-10: with --bot-login, nothing changes


# The reply and veto cases test_needs_decision.py and test_vetoed.py read with --bot-login:
# the comments after the triage line, and the state each reads
REPLY_CASES: list[tuple[list[tuple[str, str, str]], str]] = [
    ([("bot", "NONE", QUESTION)], "NEEDS_DECISION"),
    ([("bot", "NONE", QUESTION), ("amy", "OWNER", "1")], "DECIDED"),
    ([("bot", "NONE", QUESTION), ("bob", "MEMBER", "1")], "DECIDED"),
    ([("bot", "NONE", QUESTION), ("bob", "COLLABORATOR", "go with 1")], "DECIDED"),
    ([("bot", "NONE", QUESTION), ("bot", "MEMBER", "Still waiting")], "NEEDS_DECISION"),
    ([("bot", "NONE", QUESTION), ("amy", "OWNER", "1"), ("bot", "MEMBER", "Still waiting")], "DECIDED"),
    ([("bot", "NONE", QUESTION), ("amy", "OWNER", "1"), ("bot", "NONE", QUESTION)], "NEEDS_DECISION"),
    ([("bot", "NONE", QUESTION), ("eve", "CONTRIBUTOR", "1")], "NEEDS_DECISION"),
    ([("bot", "NONE", QUESTION), ("eve", "NONE", QUESTION)], "NEEDS_DECISION"),
    ([("bot", "NONE", QUESTION), ("bob", "MEMBER", QUESTION)], "NEEDS_DECISION"),
    ([("bot", "NONE", "Decision needed: which flag?"), ("amy", "OWNER", "1")], "NEEDS_DECISION"),
    ([("amy", "OWNER", "parking"), ("amy", "OWNER", "still parked")], "NEEDS_DECISION"),
]
VETO_CASES: list[tuple[list[tuple[str, str, str]], str]] = [
    ([("bot", "NONE", DECIDED)], "NEEDS_PR"),
    ([("bot", "NONE", DECIDED), ("amy", "COLLABORATOR", VETO)], "VETOED"),
    ([("bot", "NONE", DECIDED), ("amy", "OWNER", "veto, see the thread")], "VETOED"),
    ([("bot", "NONE", DECIDED), ("amy", "MEMBER", "VETO")], "VETOED"),
    ([("bot", "NONE", DECIDED), ("amy", "COLLABORATOR", "\n\nVeto.")], "VETOED"),
    ([("bot", "NONE", DECIDED), ("eve", "CONTRIBUTOR", "veto")], "NEEDS_PR"),
    ([("bot", "NONE", DECIDED), ("amy", "OWNER", "I would veto this one")], "NEEDS_PR"),
    ([("bot", "NONE", DECIDED), ("bot", "MEMBER", "Veto")], "NEEDS_PR"),
    ([("bot", "NONE", DECIDED), ("amy", "COLLABORATOR", VETO), ("bot", "NONE", HANDLED)], "NEEDS_PR"),
    ([("bot", "NONE", DECIDED), ("amy", "COLLABORATOR", VETO), ("eve", "NONE", HANDLED)], "VETOED"),
    (
        [("bot", "NONE", DECIDED), ("amy", "COLLABORATOR", VETO), ("bot", "NONE", HANDLED), ("amy", "OWNER", "Veto")],
        "VETOED",
    ),
    ([("amy", "COLLABORATOR", VETO), ("bot", "NONE", DECIDED)], "NEEDS_PR"),
]


def history(rows: list[tuple[str, str, str]], mark_bot: bool) -> list[dict[str, Any]]:
    """The comments of a case, the App's carrying the agent marker or not"""
    found = [bot(marked("Triage: implement") if mark_bot else "Triage: implement")]
    for who, association, body in rows:
        if who == "bot":
            found.append(comment(marked(body) if mark_bot else body, by=BOT, association=association))
        else:
            found.append(comment(body, by=who, association=association))
    return found


@pytest.mark.parametrize(("rows", "expected"), REPLY_CASES)
def test_s050_10_with_bot_login_every_reply_case_reads_the_same(
    ts: ModuleType, rows: list[tuple[str, str, str]], expected: str
) -> None:
    for mark_bot in (False, True):
        assert state(ts, issue(*history(rows, mark_bot)), BOT)[0] == expected, mark_bot


@pytest.mark.parametrize(("rows", "expected"), VETO_CASES)
def test_s050_10_with_bot_login_every_veto_case_reads_the_same(
    ts: ModuleType, rows: list[tuple[str, str, str]], expected: str
) -> None:
    for mark_bot in (False, True):
        assert state(ts, issue(*history(rows, mark_bot), labels=("decided",)), BOT)[0] == expected, mark_bot


def test_s050_10_a_trusted_persons_comment_after_the_apps_question_still_reads_decided(ts: ModuleType) -> None:
    item = issue(bot(marked("Triage: implement")), bot(marked(QUESTION)), comment("go with 1", by="bob"))
    assert ts.gated(item, BOT, False) == ("DECIDED", "answered by @bob")
    # the App's relay of an answer given in a session is the App's, never a reply; the label's
    # removal moves the item, as today
    relay = bot(marked("Decision by @amy, relayed by shipmill-o[bot]: go with 1"))
    item = issue(bot(marked(QUESTION)), relay)
    assert ts.gated(item, BOT, False) == ("NEEDS_DECISION", "waits on a reply")
    item["labels"]["nodes"] = []
    assert state(ts, item, BOT)[0] != "NEEDS_DECISION"
