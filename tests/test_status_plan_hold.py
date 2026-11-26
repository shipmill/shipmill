"""`shipmill status` and `shipmill status --item` follow a held goal plan (spec 098, #1734):
no WAITS ON YOU reason while it is held or its re-check is due, and its holder is postponed,
then the agent, then the maintainer again; without gh or the network"""

import json
from types import ModuleType

import pytest

from shipmill.errors import ReleaseError
from shipmill.item_status import Holder as ItemHolder
from shipmill.item_status import Ref, Who, explain
from shipmill.status import Issue, Row, Verdict, report
from shipmill.status_summary import Holder, split

from .test_status_item import NONE, whos
from .test_status_picture import REPO, facts
from .test_status_plan_waits import BOT, INTAKE_STATE, intake_lines, load
from .test_watch_plans import WATCH_STATE

URL = f"https://github.com/{REPO}"
HELD = "held until release"
MET = "triaged as plan and held, and its hold was met: waits on product intake to re-check it"
UNANSWERED = "triaged as plan: waits on the maintainer's answer to the plan"


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load(WATCH_STATE, "watch_state_status_plan_hold")


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    return load(INTAKE_STATE, "intake_state_status_plan_hold")


def held_line(ist: ModuleType, number: int, state: str, note: str, until: str, met_at: str | None) -> str:
    """intake_state.py's own --json line for a held plan, as the watch reads it"""
    row = ist.PlanRow("G-1", state, "Plan for G-1", note, number, "plan", BOT, "NONE", hold=(until, met_at))
    return json.dumps(ist.plan_json(row), sort_keys=True)


def lines_for(ist: ModuleType) -> str:
    """One plan in each of the three states a hold gives it"""
    return intake_lines(
        held_line(ist, 27, "PLAN_HELD", "until release", "release", None),
        held_line(ist, 28, "PLAN_HOLD_MET", "hold met: v1.2.0; re-check due", "release", "2026-10-02T00:00:00Z"),
        held_line(ist, 29, "PLAN_OPEN", "hold met: 2026-10-01", "2026-10-01", "2026-10-01T00:00:00Z"),
    )


def rows_for(ws: ModuleType, ist: ModuleType) -> list[Row]:
    """The watch's rows for these plans, as `shipmill status` parses its --json lines"""
    text = lines_for(ist)
    found = [*ws.plans_rows(text, REPO, BOT).rows, *ws.plans_waiting(text, REPO, BOT), *ws.plans_held(text, REPO, BOT)]
    return [Row(r.state, r.subject, r.detail, bool(r.json()["agent"]), r.fix) for r in found]


def test_s098_12_status_waits_on_you_only_for_the_rechecked_plan(ws: ModuleType, ist: ModuleType) -> None:
    rows = [r for r in rows_for(ws, ist) if r.state != "PLAN_HELD"]  # the full report has no PLAN_HELD row
    assert [(r.state, r.detail) for r in rows] == [("PLANS", "PLAN_HOLD_MET #28"), ("PLAN_OPEN", "#29")]
    found = report(facts(*(r for r in rows if r.state == "PLAN_OPEN")))
    assert found.verdict is Verdict.WAITS
    assert [r.text for r in found.reasons] == [f"goal plan #29 {URL}/issues/29 waits on your answer"]
    held_only = intake_lines(held_line(ist, 27, "PLAN_HELD", "until release", "release", None))
    met_only = intake_lines(held_line(ist, 28, "PLAN_HOLD_MET", "hold met: v1.2.0; re-check due", "release", "x"))
    assert ws.plans_waiting(held_only, REPO, BOT) == ws.plans_waiting(met_only, REPO, BOT) == []


def test_s098_13_a_held_plans_holder_is_postponed_then_the_agent_then_you(ws: ModuleType, ist: ModuleType) -> None:
    plans = [ist_issue(n) for n in (27, 28, 29)]
    found = facts(*rows_for(ws, ist), issues=plans)
    assert whos(found, 27) == [(HELD, Who.EVENT)]
    assert whos(found, 28) == [(MET, Who.AGENT)]
    assert whos(found, 29) == [(UNANSWERED, Who.MAINTAINER)]  # re-checked: as an unanswered plan
    summary = split(found, lambda _: NONE, None)
    assert summary.issues[Holder.NOBODY] == (27,)  # the summary counts a postponed item as nobody's
    assert summary.issues[Holder.AGENT] == (28,) and summary.issues[Holder.MAINTAINER] == (29,)
    assert whos(facts(issues=plans), 27) == [(UNANSWERED, Who.MAINTAINER)]  # no watch rows: as before


def test_s098_13_the_held_condition_is_cleared_by_an_event(ws: ModuleType, ist: ModuleType) -> None:
    found = facts(*rows_for(ws, ist), issues=[ist_issue(27)])
    (held,) = explain(found, Ref("27", 27, None), lambda _: NONE, None).conditions
    assert held.reason == HELD and held.who is Who.EVENT and held.holder is ItemHolder.POSTPONED
    assert held.clears == "the hold's condition met (release), then product intake re-checks the plan"


def test_s098_13_the_plan_held_row_is_read_for_an_item_only(ws: ModuleType, ist: ModuleType) -> None:
    text = intake_lines(
        held_line(ist, 27, "PLAN_HELD", "until release", "release", None),
        held_line(ist, 30, "PLAN_HELD", "until o/r#12", "o/r#12", None),
    )
    (row,) = ws.plans_held(text, REPO, BOT)
    assert (row.state, row.detail, row.action, row.json()["agent"]) == (
        "PLAN_HELD",
        "#27 until release; #30 until o/r#12",
        False,
        False,
    )
    assert ws.item_row(row, 27) and ws.item_row(row, 30) and not ws.item_row(row, 12)
    assert "PLAN_HELD" not in ws.SWEPT and all("PLAN_HELD" not in s for s in ws.TIERS.values())
    # an outsider's held plan is trusted only as PLAN_OPEN trusts one (D-16)
    outsider = ist.PlanRow(
        "G-1", "PLAN_HELD", "t", "until release", 31, "plan", "drive-by", "NONE", hold=("release", None)
    )
    assert ws.plans_held(intake_lines(json.dumps(ist.plan_json(outsider))), REPO, BOT) == []


def test_s098_13_an_unreadable_held_plan_is_refused(ws: ModuleType, ist: ModuleType) -> None:
    line = held_line(ist, 27, "PLAN_HELD", "until release", "release", None).replace('"release"', '"next week"')
    with pytest.raises(ws.Refused, match="malformed held plan"):
        ws.plans_held(intake_lines(line), REPO, BOT)
    bad = Row("PLAN_HELD", REPO, "#27 until next week", False, None)
    with pytest.raises(ReleaseError, match="PLAN_HELD"):
        whos(facts(bad, issues=[ist_issue(27)]), 27)


def ist_issue(number: int) -> Issue:
    """A goal plan's issue as triage_state.py reads it"""
    return Issue(number, "TRIAGED", verdict="plan")
