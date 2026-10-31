"""A needs-decision answer relayed from a session (needs-decision.md, Answered in the session):
the App posts `Decision by @<login>, relayed by <agent>` with the agent marker and removes the
label. The watch, triage, and the gate's walk read it as answered, not as a question still to
ask, on an upgrade issue, a direction issue, and any other issue"""

import datetime as dt
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.findings import Finding
from shipmill.walk import Changes, Handed, Swept, walk

from .test_direction_rows import BOT as DIRECTION_BOT
from .test_direction_rows import QUESTION as DIRECTION_QUESTION
from .test_direction_rows import issue as direction_issue
from .test_direction_rows import pending, rows
from .test_gate_walk import NEW, Source
from .test_needs_decision import QUESTION, REPO, comment, issue
from .test_needs_decision import load as load_module
from .test_ship_watch import BOT, Upgrades, upgrade_issue
from .test_ship_watch import QUESTION as UPGRADE_QUESTION

SKILLS = Path(__file__).resolve().parents[1] / "skills"
AGENT = "\n\n<!-- shipmill:agent -->"
SPAN = f"Decision by `@romamo`, relayed by Claude Code\n\nAnswered in the session: 1{AGENT}"
BARE = f"Decision by @romamo, relayed by Claude Code\n\nAnswered in the session: 1{AGENT}"  # before D-61
NOW = dt.datetime(2026, 10, 31, 12, 0, tzinfo=dt.UTC)


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load_module("triage_state_relayed", SKILLS / "github-issue-triage" / "scripts" / "triage_state.py")


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load_module("watch_state_relayed", SKILLS / "github-ship-watch" / "scripts" / "watch_state.py")


# -- upgrade issues ----------------------------------------------------------------------------


@pytest.mark.parametrize("relay", [SPAN, BARE], ids=["code-span", "bare"])
def test_a_relay_with_the_label_off_reads_answered_on_an_upgrade_issue(ws: ModuleType, relay: str) -> None:
    thread = [(BOT, "NONE", UPGRADE_QUESTION), (BOT, "NONE", relay)]
    upgrades = Upgrades(ws, [upgrade_issue(ws, 12)], comments={12: thread})
    assert upgrades.pending == [("#12", "changelog-fragments: answered; take up the answer")]
    assert upgrades.found.waiting == []


@pytest.mark.parametrize(
    "thread",
    [
        [(BOT, "NONE", SPAN)],  # no question before it
        [(BOT, "NONE", SPAN), (BOT, "NONE", UPGRADE_QUESTION)],  # asked again after it
        [(BOT, "NONE", UPGRADE_QUESTION), ("mallory", "NONE", SPAN)],  # not the App's
        [(BOT, "NONE", UPGRADE_QUESTION), (BOT, "NONE", f"Triage: see {SPAN}")],  # not its first line
    ],
    ids=["no-question", "asked-again", "outsider", "quoted"],
)
def test_no_relay_after_the_question_still_reads_ask(ws: ModuleType, thread: list[tuple[str, str, str]]) -> None:
    upgrades = Upgrades(ws, [upgrade_issue(ws, 12)], comments={12: thread})
    assert upgrades.pending == [("#12", "changelog-fragments: ask the maintainer (upgrade = propose)")]


def test_a_relay_with_the_label_still_on_waits_for_the_label_to_come_off(ws: ModuleType) -> None:
    thread = [(BOT, "NONE", UPGRADE_QUESTION), (BOT, "NONE", SPAN)]
    upgrades = Upgrades(ws, [upgrade_issue(ws, 12, labels=("needs-decision",))], comments={12: thread})
    assert upgrades.found.rows == [] and upgrades.found.waiting == [12]


# -- direction issues --------------------------------------------------------------------------


@pytest.mark.parametrize("relay", [SPAN, BARE], ids=["code-span", "bare"])
def test_a_relay_with_the_label_off_reads_answered_on_a_direction_issue(ws: ModuleType, relay: str) -> None:
    thread = [(DIRECTION_BOT, "NONE", DIRECTION_QUESTION), (DIRECTION_BOT, "NONE", relay)]
    direction = rows(ws, found=[direction_issue(12)], prs=[], comments=thread)
    assert pending(direction) == [("#12", "answered; take up the answer")]
    assert direction.rows[0].detail == "no docs/product.md on origin/main; #12 has the maintainer's answer"


def test_a_relay_by_anyone_but_the_app_asks_on_a_direction_issue(ws: ModuleType) -> None:
    thread = [(DIRECTION_BOT, "NONE", DIRECTION_QUESTION), ("amy", "NONE", SPAN)]
    direction = rows(ws, found=[direction_issue(12)], prs=[], comments=thread)
    assert pending(direction) == [("#12", "ask the maintainer")]


# -- any other issue ---------------------------------------------------------------------------


def state(ts: ModuleType, item: dict[str, Any], bot_login: str | None = BOT) -> tuple[str, str]:
    """As triage_state.py's main reads an open issue"""
    found: tuple[str, str] = ts.gated(item, bot_login, False) or ts.classify_open(
        item, "Triage:", "postponed", {}, None, REPO, bot_login
    )
    return found


VERDICT = comment("Triage: clarify. Waits on your decision below", BOT, "NONE")


@pytest.mark.parametrize("relay", [SPAN, BARE], ids=["code-span", "bare"])
def test_a_relay_with_the_label_off_reads_decided(ts: ModuleType, relay: str) -> None:
    item = issue(VERDICT, comment(QUESTION, BOT, "NONE"), comment(relay, BOT, "NONE"), labels=())
    assert state(ts, item) == ("DECIDED", "answered by @romamo, relayed")
    assert "DECIDED" in ts.ACTION


def test_a_triage_comment_after_the_relay_took_it_up(ts: ModuleType) -> None:
    taken = comment("Triage: implement, on `@romamo`'s answer", BOT, "NONE")
    item = issue(VERDICT, comment(QUESTION, BOT, "NONE"), comment(SPAN, BOT, "NONE"), taken, labels=())
    assert state(ts, item) == ("NEEDS_PR", "")


def test_without_bot_login_nothing_is_a_relay(ts: ModuleType) -> None:
    item = issue(VERDICT, comment(QUESTION), comment(SPAN, "amy", "OWNER"), labels=())
    assert state(ts, item, None) == ("TRIAGED", "")


def test_a_relay_with_the_label_on_still_waits(ts: ModuleType) -> None:
    item = issue(VERDICT, comment(QUESTION, BOT, "NONE"), comment(SPAN, BOT, "NONE"))
    assert state(ts, item) == ("NEEDS_DECISION", "waits on a reply")


def test_an_open_pull_request_reads_in_progress_over_a_relay(ts: ModuleType) -> None:
    item = issue(VERDICT, comment(QUESTION, BOT, "NONE"), comment(SPAN, BOT, "NONE"), labels=())
    item["timelineItems"] = {
        "nodes": [
            {
                "willCloseTarget": True,
                "isCrossRepository": False,
                "source": {"number": 30, "state": "OPEN", "title": "Fix", "body": ""},
            }
        ]
    }
    assert state(ts, item)[0] == "IN_PROGRESS"


# -- the gate's tiers --------------------------------------------------------------------------


def line(number: int, state: str, note: str) -> str:
    return json.dumps({"number": number, "state": state, "title": "t", "note": note})


def test_tier_6_reads_a_relayed_decided_that_tier_4_never_reads(ws: ModuleType) -> None:
    triage = "\n".join([line(4, "DECIDED", "answered by @amy"), line(7, "DECIDED", "answered by @romamo, relayed")])
    found = [ws.Row("ISSUES", "o/r", "DECIDED #4 #7; NEW #5", "fix")]
    assert [r.detail for r in ws.split_issues(found, decided=False)] == ["NEW #5"]
    assert [(r.state, r.detail, r.fix) for r in ws.relayed_rows(found, triage)] == [("ISSUES", "DECIDED #7", "fix")]
    # an issue the intake left out of ISSUES (an upgrade or direction issue, an untrusted one) stays out
    assert ws.relayed_rows([ws.Row("ISSUES", "o/r", "NEW #5", "fix")], triage) == []


def test_the_walk_hands_a_decided_item_from_tier_6s_own_read() -> None:
    relayed = Finding("ISSUES", "o/r", "DECIDED #7", True, (), "triage")
    walked = walk(
        Source(tiers={6: [NEW, relayed]}),
        Changes("sig"),
        Swept(NOW, (), None),
        Handed(),
        NOW,
        dt.timedelta(hours=24),
        False,
    )
    assert (walked.item, walked.tier) == (relayed, 6)


def test_the_sweeps_rows_count_in_their_own_tier_only() -> None:
    swept = Finding("UPGRADE_PENDING", "#12", "x: answered; take up the answer", True, (), "watch")
    source = Source(tiers={6: [NEW]})
    walked = walk(source, Changes("sig"), Swept(NOW, (swept,), None), Handed(), NOW, dt.timedelta(hours=24), False)
    assert (walked.item, walked.tier) == (swept, 5)
