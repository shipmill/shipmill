"""fleet.py queue leaves out a held plan and times a re-checked one from its hold's met_at
(spec 098, #1732), without gh or the network"""

import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_fleet_queue import BOT, FakeGh, ago, comment, intake_line, item, load_script, run_queue


@pytest.fixture(scope="module")
def fl() -> ModuleType:
    return load_script("fleet")


def held_line(number: int, state: str, note: str, met_at: str | None) -> dict[str, Any]:
    """intake_state.py --plans --json's line of a plan with a hold"""
    return {**intake_line(number, state, "plan"), "note": note, "hold": {"until": "release", "met_at": met_at}}


def revisions(days: int) -> list[dict[str, Any]]:
    return [comment("<!-- shipmill:plan-revised rev=1 -->\nnew plan", BOT, "NONE", ago(days=days))]


def plan_item(number: int, revised_days: int) -> dict[str, Any]:
    return item(
        number, f"Plan {number}", author=BOT, association="NONE", comments=revisions(revised_days), created=ago(days=40)
    )


def test_s098_11_a_held_or_hold_met_plan_is_no_row(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = [
        {"autonomy": "propose"},
        held_line(30, "PLAN_HELD", "until release", None),
        held_line(31, "PLAN_HOLD_MET", "hold met: v1.2.0; re-check due", ago(days=2)),
    ]
    fake = FakeGh(intake={"o/r": lines}, github={"o/r": {30: plan_item(30, 20), 31: plan_item(31, 20)}})
    code, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert (code, out.splitlines()) == (0, ["nothing waits on the maintainer"])
    assert not any("issueOrPullRequest" in arg for c in fake.calls for arg in c)  # neither is read
    assert fl.intake_items("\n".join(json.dumps(r) for r in lines), "o/r") == {}


def test_s098_11_a_rechecked_plan_waits_since_the_later_of_its_revision_and_met_at(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = [
        {"autonomy": "propose"},
        held_line(30, "PLAN_OPEN", "hold met: v1.2.0", ago(days=3)),  # met after its revision 20 days ago
        held_line(31, "PLAN_OPEN", "hold met: v1.1.0", ago(days=9)),  # revised after its hold was met
        intake_line(32, "PLAN_OPEN", "plan"),  # never held
    ]
    github = {"o/r": {30: plan_item(30, 20), 31: plan_item(31, 5), 32: plan_item(32, 7)}}
    code, out = run_queue(fl, tmp_path, capsys, FakeGh(intake={"o/r": lines}, github=github), "--bot-login", BOT)
    assert code == 1
    assert out.splitlines() == [
        "o/r PLAN          #32    answer the goal plan: Plan 32 (7d 0h)",
        "o/r PLAN          #31    answer the goal plan: Plan 31 (5d 0h)",  # its revision, the later
        "o/r PLAN          #30    answer the goal plan: Plan 30 (3d 0h)",  # its hold's met_at, the later
    ]


def test_s098_11_a_hold_not_met_or_malformed_on_a_plan_open_line(fl: ModuleType) -> None:
    unmet = held_line(30, "PLAN_OPEN", "", None)
    assert fl.plan_holds_met(json.dumps(unmet), "o/r") == {}
    for hold in ({"until": "release"}, "release", {"until": "release", "met_at": 5}):
        with pytest.raises(fl.Refused, match=re.escape("intake_state.py for o/r printed a plan whose hold")):
            fl.plan_holds_met(json.dumps({**unmet, "hold": hold}), "o/r")


def test_s098_11_a_plan_given_its_met_at_waits_since_the_later_of_the_two(fl: ModuleType) -> None:
    found = fl.queue_item("o/r", fl.PLAN, plan_item(30, 20), BOT, fl.WS.TRIAGE.timestamp(ago(days=3)))
    assert found is not None and found.since == fl.WS.TRIAGE.timestamp(ago(days=3))
    early = fl.queue_item("o/r", fl.PLAN, plan_item(30, 2), BOT, fl.WS.TRIAGE.timestamp(ago(days=3)))
    assert early is not None and early.since == fl.WS.TRIAGE.timestamp(ago(days=2))
