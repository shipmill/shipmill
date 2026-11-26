"""Spec 105: `shipmill product goal` and `shipmill product held` rewrite a goal into the goal form
or the measure form, and `product add goals` and `product edit` refuse a malformed goal's text"""

import re
from pathlib import Path

import pytest

from shipmill import product
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.lineedit import LineText
from shipmill.product import DIRECTION, Horizon, ItemId, check

from .test_direction_edit import repo

GOALS = """\
- G-1: Widgets reach buyers in a day. Check: the p90 is under a day. By: 2026-12-31
- G-2: Held: widgets arrive whole. Threshold: its measure line. Source: the weekly metrics
  measure: change_failure_rate <= 5%
- G-3: Widgets are cheap
- G-4: Buyers come back
  measure: human_touch <= 20%
"""


def direction(goals: str = GOALS) -> str:
    head = "# Acme\n\n## Mission\n\nAcme ships widgets.\n\n## Users\n\n- U-1: A buyer\n\n"
    return f"{head}## Goals\n\n{goals}\n## Non-goals\n\n## Quality bar\n\n- Q-1: Tested\n"


WELL_FORMED = direction()
MOVED = WELL_FORMED.replace(f"## Goals\n\n{GOALS}", "## Goals\n\nSee [Goals](product/goals.md).\n")
MOVED_GOALS = f"## Goals\n\n{GOALS}"  # docs/product/goals.md


def write(root: Path, text: str = WELL_FORMED, path: Path = DIRECTION) -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return root


def run(root: Path, *args: str) -> int:
    return main(["--repo", str(root), "product", *args])


@pytest.mark.parametrize(
    ("goal", "before", "after"),
    [
        pytest.param(
            "G-1",
            "Widgets reach buyers in a day. Check: the p90 is under a day. By: 2026-12-31",
            "Widgets reach buyers in a day. Check: ci is green. By: 2026-12-31",
            id="a goal keeps its outcome",
        ),
        pytest.param(
            "G-3", "Widgets are cheap", "Widgets are cheap. Check: ci is green. By: 2026-12-31", id="kind none"
        ),
    ],
)
def test_s105_6_goal_rewrites_a_goal_of_kind_goal_or_none_keeping_its_outcome(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], goal: str, before: str, after: str
) -> None:
    root = write(tmp_path)
    assert run(root, "goal", goal, "--check", "ci is green", "--by", "2026-12-31") == 0
    assert capsys.readouterr().out == f"- {goal}: {after}\n"
    assert (root / DIRECTION).read_text() == WELL_FORMED.replace(f"- {goal}: {before}\n", f"- {goal}: {after}\n")
    assert check(root) == ()


def test_s105_6_goal_takes_a_release_horizon_and_a_check_holding_a_period(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write(tmp_path)
    assert run(root, "goal", "G-3", "--check", "a. b", "--by", "v1.2.0") == 0
    assert capsys.readouterr().out == "- G-3: Widgets are cheap. Check: a. b. By: v1.2.0\n"
    record = product.read(root).goals[2].form
    assert isinstance(record, product.GoalForm) and record.check == "a. b" and record.by.release == "v1.2.0"


def test_s105_6_goal_edits_a_goals_section_moved_to_docs_product(tmp_path: Path) -> None:
    root = write(write(tmp_path, MOVED), MOVED_GOALS, Path("docs/product/goals.md"))
    assert run(root, "goal", "G-3", "--check", "ci", "--by", "0.7.0") == 0
    assert (root / DIRECTION).read_text() == MOVED
    moved = (root / "docs/product/goals.md").read_text()
    assert moved == MOVED_GOALS.replace(
        "- G-3: Widgets are cheap\n", "- G-3: Widgets are cheap. Check: ci. By: 0.7.0\n"
    )
    assert check(root) == ()


@pytest.mark.parametrize(
    ("args", "error"),
    [
        pytest.param(("G-2", "--by", "2026-12-31"), "G-2 is a measure", id="a measure"),
        pytest.param(("G-4", "--by", "2026-12-31"), "product measure G-4 --clear", id="a measure line"),
        pytest.param(("G-3", "--by", "Q4"), "a horizon is a date", id="quarter"),
        pytest.param(("G-3", "--by", "2026-13-01"), "`2026-13-01` is not a calendar date", id="bad date"),
        pytest.param(("G-3", "--by", "2026-12-31."), "a horizon is a date", id="final period"),
        pytest.param(("G-9", "--by", "2026-12-31"), "no G-9 in docs/product.md", id="unknown goal"),
        pytest.param(("Q-1", "--by", "2026-12-31"), "Q-1 is not a G-n id", id="not a goal"),
    ],
)
def test_s105_6_goal_exits_2_without_writing(tmp_path: Path, args: tuple[str, ...], error: str) -> None:
    root = write(tmp_path)
    with pytest.raises(ReleaseError, match=re.escape(error)):  # the CLI's entry point exits 2 on it
        run(root, "goal", *args, "--check", "ci")
    assert (root / DIRECTION).read_text() == WELL_FORMED


def test_s105_6_goal_on_a_measure_line_names_a_held_command_that_runs(tmp_path: Path) -> None:
    root = write(tmp_path)
    with pytest.raises(ReleaseError, match=r"product held G-4 --threshold <threshold> --source <source>`"):
        product.goal(root, ItemId.parse("G-4"), LineText("ci"), Horizon.parse("0.7.0"))
    assert (root / DIRECTION).read_text() == WELL_FORMED


def test_s105_6_goal_on_a_measure_names_product_edit(tmp_path: Path) -> None:
    root = write(tmp_path)
    with pytest.raises(ReleaseError, match=r"product edit G-2 "):
        product.goal(root, ItemId.parse("G-2"), LineText("ci"), Horizon.parse("0.7.0"))
    assert (root / DIRECTION).read_text() == WELL_FORMED


@pytest.mark.parametrize(
    ("goal", "before", "after"),
    [
        pytest.param(
            "G-2",
            "Held: widgets arrive whole. Threshold: its measure line. Source: the weekly metrics",
            "Held: widgets arrive whole. Threshold: under 5%. Source: shipmill metrics",
            id="a measure keeps its statement",
        ),
        pytest.param(
            "G-3",
            "Widgets are cheap",
            "Held: Widgets are cheap. Threshold: under 5%. Source: shipmill metrics",
            id="kind none",
        ),
        pytest.param(
            "G-4",
            "Buyers come back",
            "Held: Buyers come back. Threshold: under 5%. Source: shipmill metrics",
            id="kind none with a measure line",
        ),
    ],
)
def test_s105_7_held_rewrites_a_goal_of_kind_measure_or_none_keeping_its_statement_and_measure_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], goal: str, before: str, after: str
) -> None:
    root = write(tmp_path)
    assert run(root, "held", goal, "--threshold", "under 5%", "--source", "shipmill metrics") == 0
    assert capsys.readouterr().out == f"- {goal}: {after}\n"
    written = (root / DIRECTION).read_text()
    assert written == WELL_FORMED.replace(f"- {goal}: {before}\n", f"- {goal}: {after}\n")
    assert "  measure: change_failure_rate <= 5%\n" in written and "  measure: human_touch <= 20%\n" in written
    assert check(root) == ()


def test_s105_7_held_edits_a_goals_section_moved_to_docs_product(tmp_path: Path) -> None:
    root = write(write(tmp_path, MOVED), MOVED_GOALS, Path("docs/product/goals.md"))
    assert run(root, "held", "G-4", "--threshold", "a fifth", "--source", "metrics") == 0
    assert (root / DIRECTION).read_text() == MOVED
    moved = (root / "docs/product/goals.md").read_text()
    held = "- G-4: Held: Buyers come back. Threshold: a fifth. Source: metrics\n"
    assert moved == MOVED_GOALS.replace("- G-4: Buyers come back\n", held)
    assert check(root) == ()


def test_s105_8_edit_in_a_moved_goals_section_names_that_file(tmp_path: Path) -> None:
    root = write(write(tmp_path, MOVED), MOVED_GOALS, Path("docs/product/goals.md"))
    with pytest.raises(ReleaseError, match=r"\n  docs/product/goals\.md:6: G-3: a horizon is a date"):
        run(root, "edit", "G-3", "Cheap. Check: ci. By: Q4")
    assert (root / "docs/product/goals.md").read_text() == MOVED_GOALS


@pytest.mark.parametrize(
    ("args", "error"),
    [
        pytest.param(("G-1",), "G-1 is a goal", id="a goal"),
        pytest.param(("G-9",), "no G-9 in docs/product.md", id="unknown goal"),
        pytest.param(("U-1",), "U-1 is not a G-n id", id="not a goal"),
    ],
)
def test_s105_7_held_exits_2_without_writing(tmp_path: Path, args: tuple[str, ...], error: str) -> None:
    root = write(tmp_path)
    with pytest.raises(ReleaseError, match=re.escape(error)):
        run(root, "held", *args, "--threshold", "t", "--source", "s")
    assert (root / DIRECTION).read_text() == WELL_FORMED


def test_s105_7_held_on_a_goal_names_product_edit(tmp_path: Path) -> None:
    root = write(tmp_path)
    with pytest.raises(ReleaseError, match=r"product edit G-1 "):
        product.held(root, ItemId.parse("G-1"), LineText("t"), LineText("s"))


def test_s105_7_held_refuses_a_threshold_holding_a_goals_label(tmp_path: Path) -> None:
    root = write(tmp_path)
    with pytest.raises(ReleaseError, match="both a goal's labels"):
        run(root, "held", "G-3", "--threshold", "a. Check: b", "--source", "s")
    assert (root / DIRECTION).read_text() == WELL_FORMED


MALFORMED = [
    pytest.param("Fast. Check: p90", id="no by"),
    pytest.param("Fast. By: 2026-12-31", id="no check"),
    pytest.param("Fast. Check: p90. By: Q4", id="quarter"),
    pytest.param("Held: fast. Threshold: a day", id="no source"),
    pytest.param("Held: fast. Threshold: a day. Source: m. By: 2026-12-31", id="both forms"),
]


def check_says(tmp_path: Path, text: str, line: int) -> str:
    """What `product check` prints for the goal's text written as G-3, on that line"""
    written = WELL_FORMED.replace("- G-3: Widgets are cheap\n", f"- G-3: {text}\n")
    found = [str(p) for p in check(write(tmp_path / "checked", written))]
    assert len(found) == 1 and found[0].startswith(f"docs/product.md:{line}: G-3: "), found
    return found[0]


@pytest.mark.parametrize("text", MALFORMED)
def test_s105_8_edit_refuses_a_malformed_goal_with_checks_message(tmp_path: Path, text: str) -> None:
    root = write(tmp_path / "repo")
    said = check_says(tmp_path, text, 16)
    with pytest.raises(ReleaseError) as refused:
        run(root, "edit", "G-3", text)
    assert f"\n  {said}" in str(refused.value) and "nothing was written" in str(refused.value)
    assert (root / DIRECTION).read_text() == WELL_FORMED


@pytest.mark.parametrize("text", MALFORMED)
def test_s105_8_add_goals_refuses_a_malformed_goal_with_checks_message(tmp_path: Path, text: str) -> None:
    root = repo(tmp_path / "repo", {str(DIRECTION): WELL_FORMED})
    with pytest.raises(ReleaseError) as refused:
        run(root, "add", "goals", text)
    message = str(refused.value)
    assert f"\n  docs/product.md:19: G-5: {check_says(tmp_path, text, 16).split(': G-3: ', 1)[1]}" in message
    assert "nothing was written" in message
    assert (root / DIRECTION).read_text() == WELL_FORMED


def test_s105_8_edit_refuses_a_goal_form_over_a_measure_line(tmp_path: Path) -> None:
    root = write(tmp_path)
    with pytest.raises(ReleaseError, match=r"docs/product.md:18: G-4 is a goal, which ends on its check"):
        run(root, "edit", "G-4", "Buyers come back. Check: half do. By: 2026-12-31")
    assert (root / DIRECTION).read_text() == WELL_FORMED


def test_s105_8_add_and_edit_still_write_a_well_formed_goal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = repo(tmp_path, {str(DIRECTION): WELL_FORMED})
    assert run(root, "add", "goals", "Held: it stays up. Threshold: 99%. Source: the probe") == 0
    assert run(root, "edit", "G-3", "Cheap. Check: under a dollar. By: 0.7.0") == 0
    assert capsys.readouterr().out.splitlines() == [
        "- G-5: Held: it stays up. Threshold: 99%. Source: the probe",
        "- G-3: Cheap. Check: under a dollar. By: 0.7.0",
    ]
    assert check(root) == ()
