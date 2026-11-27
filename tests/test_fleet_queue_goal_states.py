"""fleet.py queue shows a PLAN_OVERDUE plan as an overdue PLAN row and a NEEDS_GOAL opportunity
as an OPPORTUNITY row (spec 106, S-106-26), without gh or the network"""

import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_fleet_queue import BOT, FakeGh, ago, comment, intake_line, item, load_script, run_queue, watch_row


@pytest.fixture(scope="module")
def fl() -> ModuleType:
    return load_script("fleet")


def overdue(number: int, answer_by: str = "2026-11-20") -> dict[str, Any]:
    return {**intake_line(number, "PLAN_OVERDUE", "plan"), "note": f"answer by {answer_by}", "answer_by": answer_by}


def plan_item(number: int) -> dict[str, Any]:
    revised = [comment("<!-- shipmill:plan-revised rev=1 -->\nnew plan", BOT, "NONE", ago(days=9))]
    return item(number, f"Plan {number}", author=BOT, association="NONE", comments=revised, created=ago(days=20))


def test_s106_26_an_overdue_plan_and_an_opportunity_needing_a_goal_are_rows(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines: list[dict[str, Any]] = [
        {"autonomy": "propose"},
        overdue(30),
        {**intake_line(31, "NEEDS_GOAL"), "note": "names no goal: answer `accept G-<n>` or `accept new goal`"},
        intake_line(32, "ACCEPTED_INTO"),  # its goal's plan takes it: no row
        intake_line(33, "GOAL_PROPOSAL_DUE"),  # a session's: no row
    ]
    github = {
        "o/r": {
            30: plan_item(30),
            31: item(31, "Opportunity 31", author=BOT, association="NONE", created=ago(days=4)),
        }
    }
    code, out = run_queue(fl, tmp_path, capsys, FakeGh(intake={"o/r": lines}, github=github), "--bot-login", BOT)
    assert code == 1
    assert out.splitlines() == [
        "o/r PLAN          #30    answer the goal plan, answer due 2026-11-20, overdue: Plan 30 (9d 0h)",
        "o/r OPPORTUNITY   #31    accept or decline the opportunity, name the goal it serves:"
        " accept G-<n> or accept new goal: Opportunity 31 (4d 0h)",
    ]
    code, out = run_queue(
        fl, tmp_path, capsys, FakeGh(intake={"o/r": lines}, github=github), "--bot-login", BOT, "--json"
    )
    items = json.loads(out)["items"]
    assert [(i["kind"], i["number"], i["asked"]) for i in items] == [
        ("PLAN", 30, "answer the goal plan, answer due 2026-11-20, overdue"),
        (
            "OPPORTUNITY",
            31,
            "accept or decline the opportunity, name the goal it serves: accept G-<n> or accept new goal",
        ),
    ]


def test_s106_26_a_question_on_the_plan_keeps_its_own_phrase(
    fl: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines: list[dict[str, Any]] = [{"autonomy": "propose"}, overdue(30)]
    question = comment("<!-- shipmill:needs-decision -->\nWhich one?", BOT, "NONE", ago(days=2))
    asked = item(30, "Plan 30", author=BOT, association="NONE", labels=["needs-decision"], comments=[question])
    watch = {"o/r": [watch_row("NEEDS_DECISION", "o/r", "#30")]}
    fake = FakeGh(watch=watch, intake={"o/r": lines}, github={"o/r": {30: asked}})
    _, out = run_queue(fl, tmp_path, capsys, fake, "--bot-login", BOT)
    assert out.splitlines()[0].startswith("o/r QUESTION      #30    answer the needs-decision question: Plan 30")


def test_s106_26_an_overdue_plan_without_its_date_is_refused(fl: ModuleType) -> None:
    line = {**intake_line(30, "PLAN_OVERDUE", "plan"), "answer_by": None}
    with pytest.raises(fl.Refused, match="overdue plan without its answer_by"):
        fl.intake_notes(json.dumps(line), "o/r")
