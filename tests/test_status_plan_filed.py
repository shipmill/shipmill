"""#1724: an accepted goal plan whose kept existing items all have another parent gets no
children (D-114), so intake_state.py reads it PLAN_FILED at once. The watch carries it as a
report-only PLAN_FILED row, and `shipmill status --item` (and queue) reads that plan as
waiting on those open items, then on product intake once they close (PLAN_DONE), never on
the maintainer; without gh or the network"""

import datetime as dt
import json
from types import ModuleType

import pytest

from shipmill.errors import ReleaseError
from shipmill.gate import Action, decide, parse_findings
from shipmill.item_status import Holder as ItemHolder
from shipmill.item_status import Ref, Who, explain
from shipmill.status import Issue, Row

from .test_status_item import NONE, whos
from .test_status_picture import REPO, facts
from .test_status_plan_waits import BOT, INTAKE_STATE, intake_lines, load
from .test_watch_plans import WATCH_STATE

NOW = dt.datetime(2026, 10, 20, 12, tzinfo=dt.UTC)
UNANSWERED = "triaged as plan: waits on the maintainer's answer to the plan"
# intake_state.py's own note for it (tests/test_intake_plans.py's D-114 test locks the note)
ELSEWHERE = "nothing to file; another parent: #212, #213"


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load(WATCH_STATE, "watch_state_status_plan_filed")


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    return load(INTAKE_STATE, "intake_state_status_plan_filed")


def plan_line(ist: ModuleType, number: int, state: str, note: str, author: str = BOT, **kw: object) -> str:
    """intake_state.py's own --json line for a plan issue, as the watch reads it"""
    row = ist.PlanRow("G-1", state, "Plan for G-1", note, number, "plan", author, "NONE", **kw)
    return json.dumps(ist.plan_json(row), sort_keys=True)


def filed_line(ist: ModuleType, number: int = 40, note: str = ELSEWHERE, author: str = BOT) -> str:
    return plan_line(ist, number, "PLAN_FILED", note, author, kept=("W-1", "W-2"), dropped=())


def rows_for(ws: ModuleType, text: str) -> list[Row]:
    """The watch's plan rows, as `shipmill status` parses its --json lines"""
    found = [*ws.plans_rows(text, REPO, BOT).rows, *ws.plans_waiting(text, REPO, BOT), *ws.plans_filed(text, REPO, BOT)]
    return [Row(r.state, r.subject, r.detail, bool(r.json()["agent"]), r.fix) for r in found]


def test_1724_the_watch_carries_an_unlinked_filed_plan_report_only(ws: ModuleType, ist: ModuleType) -> None:
    text = intake_lines(
        filed_line(ist),
        filed_line(ist, 41, "filed: #301; another parent: #214; dropped: W-3"),
        filed_line(ist, 42, "filed: #301, #302"),  # its items are its children: in no row
    )
    (row,) = ws.plans_filed(text, REPO, BOT)
    assert (row.state, row.subject) == ("PLAN_FILED", REPO)
    assert row.detail == "#40(another parent: #212, #213); #41(another parent: #214)"
    assert (row.action, row.json()["agent"], row.fix) == (False, False, None)
    # S-096-13 stands: the PLANS row lists no filed plan, so no session starts for one
    assert ws.plans_rows(text, REPO, BOT).rows == []
    assert "PLAN_FILED" not in ws.ACTION and "PLAN_FILED" not in ws.AGENT
    assert "PLAN_FILED" not in ws.SWEPT and all("PLAN_FILED" not in s for s in ws.TIERS.values())
    findings = parse_findings(json.dumps(row.json(), sort_keys=True) + "\n")
    assert decide(findings, [], None, NOW, dt.timedelta(hours=6)).action is Action.QUIET
    # an --item read keeps it for the plan it names, never for the items it waits on
    assert ws.item_row(row, 40) and ws.item_row(row, 41)
    assert not ws.item_row(row, 212) and not ws.item_row(row, 4)


def test_1724_the_plan_filed_row_trusts_a_plan_as_plan_open_does(ws: ModuleType, ist: ModuleType) -> None:
    outsider = intake_lines(filed_line(ist, author="drive-by"))
    assert ws.plans_filed(outsider, REPO, BOT) == []
    with pytest.raises(ws.Refused, match="malformed plan row"):
        ws.plans_filed(intake_lines(filed_line(ist, note="another parent: #212, x")), REPO, BOT)


def test_1724_an_accepted_plan_waits_on_its_open_item_with_another_parent(ws: ModuleType, ist: ModuleType) -> None:
    rows = rows_for(ws, intake_lines(filed_line(ist)))
    plan, other = Issue(40, "TRIAGED", verdict="plan"), Issue(212, "NEEDS_PR")
    found = facts(*rows, issues=[plan, other])  # #213 is closed: triage_state.py reads no line for it
    assert whos(found, 40) == [
        ("triaged as plan and accepted: waits on #212, an item with another parent, closing", Who.EVENT)
    ]
    (condition,) = explain(found, Ref("40", 40, None), lambda _: NONE, None).conditions
    assert condition.holder is ItemHolder.POSTPONED  # as a plan moving through its children (S-094-4)
    assert condition.clears == f"#212 closing; {found.command} status --item 212 says what holds it"
    # both open: each a condition of its own
    both = facts(*rows, issues=[plan, other, Issue(213, "TRIAGED", verdict="feature")])
    assert [reason for reason, _ in whos(both, 40)] == [
        "triaged as plan and accepted: waits on #212, an item with another parent, closing",
        "triaged as plan and accepted: waits on #213, an item with another parent, closing",
    ]
    assert whos(facts(issues=[plan]), 40) == [(UNANSWERED, Who.MAINTAINER)]  # no watch rows: as before


def test_1724_once_its_work_closed_the_plan_waits_on_product_intake(ws: ModuleType, ist: ModuleType) -> None:
    done = plan_line(ist, 40, "PLAN_DONE", "work closed: W-1 #212 completed, W-2 #213 completed")
    rows = rows_for(ws, intake_lines(done))
    assert [(r.state, r.detail) for r in rows] == [("PLANS", "PLAN_DONE #40")]
    found = facts(*rows, issues=[Issue(40, "TRIAGED", verdict="plan")])
    assert whos(found, 40) == [
        ("triaged as plan and its work closed: waits on product intake to post its outcome", Who.AGENT)
    ]


def test_1724_an_unreadable_plan_filed_row_is_refused() -> None:
    bad = Row("PLAN_FILED", REPO, "#40 another parent #212", False, None)
    with pytest.raises(ReleaseError, match="PLAN_FILED"):
        whos(facts(bad, issues=[Issue(40, "TRIAGED", verdict="plan")]), 40)
