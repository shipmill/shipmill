"""The watch's PLANS row lists a held plan whose re-check is due, and never a plan still held
(spec 098, #1729), without gh or the network"""

import datetime as dt
import json
from types import ModuleType

import pytest

from shipmill.gate import Action, decide, parse_findings

from .test_intake_plan_hold import Held
from .test_intake_plans import GOALS, open_plan, owner
from .test_watch_plans import BOT, INTAKE_STATE, NOW, WATCH_STATE, intake_lines, load, plan_row


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load(WATCH_STATE, "watch_state_plan_hold")


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    return load(INTAKE_STATE, "intake_state_watch_hold")


def held_line(ist: ModuleType, number: int, state: str, note: str, met_at: str | None) -> str:
    """intake_state.py's own --json line for a held plan, as the watch reads it"""
    hold = ("release", met_at)
    row = ist.PlanRow("G-1", state, "Plan for G-1", note, number, "plan", BOT, "NONE", hold=hold)
    return json.dumps(ist.plan_json(row), sort_keys=True)


def test_s098_15_the_plans_row_lists_plan_hold_met_as_an_action(ws: ModuleType, ist: ModuleType) -> None:
    met = held_line(ist, 27, "PLAN_HOLD_MET", "hold met: v1.2.0; re-check due", "2026-10-02T00:00:00Z")
    still = held_line(ist, 28, "PLAN_HELD", "until release", None)
    text = intake_lines(plan_row(22, "PLAN_ACCEPTED", note="not filed: W-2"), met, still)
    (row,) = ws.plans_rows(text, "o/r", BOT).rows
    assert row.detail == "PLAN_ACCEPTED #22; PLAN_HOLD_MET #27"  # #28, held, is in no row
    assert row.fix == "/shipmill:product-intake o/r" and row.json()["agent"] is True
    assert ws.plans_waiting(text, "o/r", BOT) == []  # neither waits on the maintainer yet
    assert set(ws.PLAN_ACTION) == ist.PLAN_ACTION  # the watch's actions are intake's
    assert "PLAN_HELD" in ws.PLAN_STATES and "PLAN_HELD" not in ws.PLAN_ACTION


def test_s098_15_a_held_plan_alone_makes_no_plans_row(ws: ModuleType, ist: ModuleType) -> None:
    text = intake_lines(held_line(ist, 28, "PLAN_HELD", "until release", None))
    assert ws.plans_rows(text, "o/r", BOT).rows == []


def test_s098_15_shipmill_gate_starts_a_session_for_plan_hold_met(ws: ModuleType, ist: ModuleType) -> None:
    met = held_line(ist, 27, "PLAN_HOLD_MET", "hold met: v1.2.0; re-check due", "2026-10-02T00:00:00Z")
    (row,) = ws.plans_rows(intake_lines(met), "o/r", BOT).rows
    findings = parse_findings(json.dumps(row.json(), sort_keys=True))
    decision = decide(findings, [], None, NOW, dt.timedelta(hours=6))
    assert decision.action is Action.LAUNCH and [f.detail for f in decision.work] == ["PLAN_HOLD_MET #27"]


def plan_lines(ist: ModuleType, fake: Held) -> list[str]:
    """intake_state.py --plans --json's plan and goal lines for these issues, on the hold's day"""
    intake = ist.fetch(
        "o/r",
        label="opportunity",
        accepted="planned",
        marker="Triage:",
        skip=set(ist.SKIP_LABELS),
        categories=None,
        autonomy="propose",
        run=fake,
    )
    found = ist.fetch_plans(
        "o/r",
        intake,
        goals=lambda: [ist.Goal(i, t) for i, t in GOALS],
        marker="Triage:",
        bot_login=BOT,
        wip=None,
        room=lambda limit: 1,
        run=fake,
        filing=lambda issue, plan: ("PLAN_ACCEPTED", "unfiled"),
        now=dt.datetime(2026, 10, 2, 12, tzinfo=dt.UTC),
    )
    return [json.dumps(ist.plan_json(r), sort_keys=True) for r in found]


def test_s098_10_a_goal_whose_only_open_plan_is_held_reads_no_plan_due(ws: ModuleType, ist: ModuleType) -> None:
    unplanned = [json.loads(line) for line in plan_lines(ist, Held())]
    assert {(r["goal"], r["state"]) for r in unplanned} == {(g, "PLAN_DUE") for g, _ in GOALS}  # the trigger holds
    lines = plan_lines(ist, Held(plans=[open_plan(20, owner("hold until release", 10))]))
    read = [json.loads(line) for line in lines]
    (plan,) = [r for r in read if r["kind"] == "plan"]
    assert (plan["number"], plan["state"], plan["goal"]) == (20, "PLAN_HELD", "G-1")
    assert ("G-1", "PLAN_DUE") not in {(r["goal"], r["state"]) for r in read if r["kind"] == "goal"}
    (row,) = ws.plans_rows(intake_lines(*lines), "o/r", BOT).rows  # the other goals' PLAN_DUE, never #20
    assert "#20" not in row.detail and "PLAN_HELD" not in row.detail


def test_s098_10_shipmill_gate_starts_no_session_for_a_held_plan(ws: ModuleType, ist: ModuleType) -> None:
    text = intake_lines(held_line(ist, 28, "PLAN_HELD", "until 2026-12-15", None))
    rows = [*ws.plans_rows(text, "o/r", BOT).rows, *ws.plans_waiting(text, "o/r", BOT)]
    assert rows == []  # no PLANS row and no PLAN_OPEN row: nothing waits on an agent or the maintainer
    findings = parse_findings("".join(json.dumps(r.json(), sort_keys=True) + "\n" for r in rows))
    assert decide(findings, [], None, NOW, dt.timedelta(hours=6)).action is Action.QUIET


def test_s098_15_a_rechecked_plan_waits_on_the_maintainer_again(ws: ModuleType, ist: ModuleType) -> None:
    text = intake_lines(held_line(ist, 27, "PLAN_OPEN", "hold met: v1.2.0", "2026-10-02T00:00:00Z"))
    assert ws.plans_rows(text, "o/r", BOT).rows == []
    (waiting,) = ws.plans_waiting(text, "o/r", BOT)
    assert waiting.detail == "#27"
