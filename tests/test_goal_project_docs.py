"""docs/flow.md and the skills' references give spec 106's states, labels, and markers
(S-106-27), the same ones intake_state.py reads"""

from pathlib import Path

import pytest

from .test_status_plan_waits import INTAKE_STATE, load

ROOT = Path(__file__).resolve().parents[1]
FLOW = (ROOT / "docs" / "flow.md").read_text(encoding="utf-8")
PLAN = (ROOT / "skills" / "product-intake" / "references" / "plan.md").read_text(encoding="utf-8")
WATCH = (ROOT / "skills" / "github-ship-watch" / "SKILL.md").read_text(encoding="utf-8")
LABELS = ("project", "held", "focus", "goal-proposal", "goal-review")
MARKERS = (
    "<!-- shipmill:goal-overdue G-<n> by=<horizon> -->",
    "<!-- shipmill:plan-replaced #<new> -->",
    "<!-- shipmill:project-stopped -->",
)


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start : end if end != -1 else len(text)]


@pytest.mark.parametrize("where", [FLOW, PLAN], ids=["flow", "plan.md"])
def test_s106_27_the_labels_and_markers_are_documented(where: str) -> None:
    for label in LABELS:
        assert f"| `{label}` |" in where, label
    for marker in MARKERS:
        assert f"`{marker}`" in where, marker


def test_s106_27_flow_gives_each_state() -> None:
    lifecycle = section(FLOW, "## Goals, plans, and projects")
    for state in ("proposed", "written", "planned", "met", "dropped"):
        assert f"| {state} |" in lifecycle, state
    for state in ("held", "active", "in focus", "closing", "closed", "stopped"):
        assert f"| {state} |" in lifecycle, state
    for state in (
        "GOAL_OVERDUE",
        "PLAN_OVERDUE",
        "PLAN_REPLACED",
        "PROJECT_START_DUE",
        "PROJECT_IDLE",
        "PROJECT_STOP_DUE",
        "ACCEPTED_INTO",
        "GOAL_PROPOSAL_DUE",
        "NEEDS_GOAL",
    ):
        assert state in lifecycle, state
    assert "shipmill status --item G-3" in lifecycle and "`[agents] projects = N`" in lifecycle
    for waits in ("`plan #P overdue`", "`a free slot: K of N active`", "`held by the maintainer`"):
        assert waits in lifecycle


def test_s106_27_the_documented_names_are_the_ones_intake_reads() -> None:
    ist = load(INTAKE_STATE, "intake_state_goal_project_docs")
    assert LABELS[:3] == (ist.PROJECT_LABEL, ist.PROJECT_HELD_LABEL, ist.PROJECT_FOCUS_LABEL)
    assert LABELS[3:] == (ist.GOAL_PROPOSAL_LABEL, ist.GOAL_REVIEW_LABEL)
    assert ist.OVERDUE_MARKER.fullmatch("<!-- shipmill:goal-overdue G-3 by=2026-12-31 -->") is not None
    assert ist.REPLACED_MARKER.fullmatch("<!-- shipmill:plan-replaced #12 -->") is not None
    assert MARKERS[2] == ist.STOP_RECORD
    for state in ("GOAL_OVERDUE", "PLAN_REPLACED", "PROJECT_START_DUE", "PROJECT_IDLE", "PROJECT_STOP_DUE"):
        assert state in WATCH, state  # the watch's PLANS row names each action it starts a session for


def test_s106_31_flow_names_both_closing_cases() -> None:
    lifecycle = section(FLOW, "## Goals, plans, and projects")
    (row,) = [line for line in lifecycle.splitlines() if line.startswith("| closing |")]
    assert "its check issue closed with the head still open" in row
    assert "someone other than the builder, who runs the check" in row
    assert "an agent: triage reads the head UNBLOCKED and a gate session closes it" in row
