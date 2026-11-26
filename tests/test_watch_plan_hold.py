"""The watch's PLANS row lists a held plan whose re-check is due, and never a plan still held
(spec 098, #1729), without gh or the network"""

import datetime as dt
import json
from types import ModuleType

import pytest

from shipmill.gate import Action, decide, parse_findings

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


def test_s098_15_a_rechecked_plan_waits_on_the_maintainer_again(ws: ModuleType, ist: ModuleType) -> None:
    text = intake_lines(held_line(ist, 27, "PLAN_OPEN", "hold met: v1.2.0", "2026-10-02T00:00:00Z"))
    assert ws.plans_rows(text, "o/r", BOT).rows == []
    (waiting,) = ws.plans_waiting(text, "o/r", BOT)
    assert waiting.detail == "#27"
