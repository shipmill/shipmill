"""product-intake's skill gives an accepted opportunity's goal states and a replaced plan's
step (spec 106, S-106-22 to S-106-24, S-106-10)"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "skills" / "product-intake"
SKILL = (ROOT / "SKILL.md").read_text(encoding="utf-8")
PLAN = (ROOT / "references" / "plan.md").read_text(encoding="utf-8")


def row(state: str) -> str:
    return next(line for line in SKILL.splitlines() if line.startswith(f"| {state} |"))


def test_s106_24_the_skill_gives_the_goal_questions() -> None:
    assert "`accept G-<n>` and `accept new goal`" in row("NEEDS_GOAL") and "file nothing" in row("NEEDS_GOAL")
    proposal = row("GOAL_PROPOSAL_DUE")
    assert "labelled `goal-proposal`" in proposal and "--child" in proposal


def test_s106_23_an_opportunity_item_files_no_issue() -> None:
    step = next(line for line in SKILL.splitlines() if line.startswith("1. Open its issue from plan.md"))
    assert "A `feature` item whose text starts `#<n>`" in step
    assert "files no issue" in step and "label the opportunity `project`" in step and "sub-issue" in step
    assert "proposes that opportunity as a `feature` item whose text starts `#<n>`" in PLAN


def test_s106_10_the_skill_gives_the_replaced_plans_step() -> None:
    assert "`<!-- shipmill:plan-replaced #<new> -->`" in row("PLAN_REPLACED")
    assert "keeps the open plan's Work items it still proposes and names the ones it drops under Notes" in PLAN
    assert "ACCEPTED_INTO" in row("ACCEPTED_INTO")
