"""product-intake's skill gives GOAL_OVERDUE's step and PLAN_DONE's goal check (spec 106, S-106-6)"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "skills" / "product-intake"
SKILL = (ROOT / "SKILL.md").read_text(encoding="utf-8")
PLAN = (ROOT / "references" / "plan.md").read_text(encoding="utf-8")


def step(text: str, start: str) -> str:
    return next(line for line in text.splitlines() if line.startswith(start))


def test_s106_6_the_skill_gives_goal_overdues_step() -> None:
    overdue = step(SKILL, "**GOAL_OVERDUE: ask about a goal past its horizon")
    for words in (
        "labelled `goal-review`",
        "`<!-- shipmill:goal-overdue G-<n> by=<horizon> -->`",
        "extend (a new horizon), rewrite (a new check), or drop (with a reason)",
        "which only the maintainer merges (D-34)",
        "needs-decision protocol",
    ):
        assert words in overdue, words


def test_s106_6_plan_done_gives_the_goal_check_and_the_met_pull_request() -> None:
    done = step(SKILL, "3. For a goal of kind goal, give the outcome its `Goal check:` line")
    for words in (
        "`holds`, `fails`, or `can't be run by an agent`",
        "adds `. Met: <today>`",
        "a standing measure in its place",
        "only the maintainer merges it (D-34)",
    ):
        assert words in done, words
    assert "Goal check: {holds, fails, or can't be run by an agent}" in PLAN


def test_s106_4_the_skill_lists_the_goal_rows() -> None:
    rows = step(SKILL, "`--goals` adds a row per goal (spec 106)")
    for state in ("GOAL_PROPOSED", "GOAL_WRITTEN", "GOAL_PLANNED", "GOAL_MET", "GOAL_DROPPED", "GOAL_OVERDUE"):
        assert state in rows, state
