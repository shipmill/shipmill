"""Spec 105: a goal of the direction is a goal (`<outcome>. Check: <check>. By: <horizon>`), a
standing measure (`Held: <statement>. Threshold: <threshold>. Source: <source>`), or of neither
kind; `shipmill product check` refuses a malformed one and `product show --json` gives its fields"""

import datetime as dt
import json
from pathlib import Path

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.product import (
    DIRECTION,
    GoalForm,
    GoalKind,
    Horizon,
    MeasureForm,
    Section,
    check,
    read,
    read_goal,
    read_home,
)

ROOT = Path(__file__).resolve().parents[1]

GOALS = """\
- G-1: Widgets reach buyers in a day. Check: the p90 is under a day. By: 2026-12-31
- G-2: Buyers can track a widget. Check: `track` names its van. By: 0.7.0
- G-3: Held: widgets arrive whole. Threshold: its measure line. Source: the weekly metrics
  measure: change_failure_rate <= 5%
- G-4: Held: buyers come back. Threshold: half of them. Source: the shop's ledger
- G-5: Widgets are cheap
"""


def direction(goals: str) -> str:
    head = "# Acme\n\n## Mission\n\nAcme ships widgets.\n\n## Users\n\n- U-1: A buyer\n\n"
    return f"{head}## Goals\n\n{goals}\n## Non-goals\n\n## Quality bar\n\n- Q-1: Tested\n"


def write(root: Path, text: str) -> Path:
    target = root / DIRECTION
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return root


def run(root: Path, *args: str) -> int:
    return main(["--repo", str(root), "product", *args])


def test_s105_1_check_passes_each_kind_with_and_without_a_measure_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write(tmp_path, direction(GOALS))
    assert check(root) == ()
    assert run(root, "check") == 0
    assert capsys.readouterr().out == f"{DIRECTION}: well formed, 7 items\n"
    kinds = [None if item.form is None else item.form.kind for item in read(root).goals]
    assert kinds == [GoalKind.GOAL, GoalKind.GOAL, GoalKind.MEASURE, GoalKind.MEASURE, None]


def test_s105_1_this_repos_direction_as_merged_passes_with_its_kinds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """docs/product.md as merged on 2026-11-26 (#1690), kept as a fixture: G-1, G-2, and G-5 are
    measures, the rest goals"""
    merged = (ROOT / "tests" / "fixtures" / "product-2026-11-26.md").read_text(encoding="utf-8")
    root = write(tmp_path, merged)
    assert check(root) == ()
    assert run(root, "check") == 0
    assert capsys.readouterr().out == f"{DIRECTION}: well formed, 23 items\n"
    kinds = {str(item.id): None if item.form is None else item.form.kind for item in read(root).goals}
    measures = {"G-1", "G-2", "G-5"}
    assert kinds == {f"G-{n}": GoalKind.MEASURE if f"G-{n}" in measures else GoalKind.GOAL for n in range(1, 9)}
    assert check(ROOT) == ()  # and as it stands now


FORM = "a goal is `<outcome>. Check: <check>. By: <YYYY-MM-DD or X.Y.Z>`"
HELD = "a measure is `Held: <statement>. Threshold: <threshold>. Source: <source>`"


@pytest.mark.parametrize(
    ("goal", "rule"),
    [
        pytest.param("- G-1: Fast. Check: p90 under a day", "`. Check: ` with no `. By: ` after it", id="no by"),
        pytest.param("- G-1: Fast. By: 2026-12-31", "`. By: ` with no `. Check: ` before it", id="no check"),
        pytest.param(
            "- G-1: Fast. By: 2026-12-31. Check: p90", "`. Check: ` with no `. By: ` after it", id="by before check"
        ),
        pytest.param("- G-1: . Check: p90. By: 2026-12-31", "its outcome is empty", id="empty outcome"),
        pytest.param("- G-1: Fast. Check:  . By: 2026-12-31", "its check is empty", id="empty check"),
        # a line's trailing spaces are not read, so an empty horizon leaves `. By:` unlabelled
        pytest.param("- G-1: Fast. Check: p90. By:  ", "`. Check: ` with no `. By: ` after it", id="empty horizon"),
        pytest.param("- G-1: Fast. Check: p90. By: 2026-13-01", "a horizon is a date", id="bad date"),
        pytest.param("- G-1: Fast. Check: p90. By: Q4", "a horizon is a date", id="quarter"),
        pytest.param("- G-1: Fast. Check: p90. By: 2026-12-31.", "a horizon is a date", id="final period"),
        pytest.param("- G-1: Fast. Check: p90. By: 0.7", "a horizon is a date", id="short version"),
    ],
)
def test_s105_2_check_refuses_a_malformed_goal_naming_file_line_and_goal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], goal: str, rule: str
) -> None:
    root = write(tmp_path, direction(goal + "\n"))
    found = [str(p) for p in check(root)]
    assert len(found) == 1, found
    assert found[0].startswith(f"docs/product.md:13: G-1: {rule}"), found
    assert found[0].endswith(FORM), found
    assert run(root, "check") == 1  # as every refused line (spec 024)
    assert capsys.readouterr().out.splitlines() == found


@pytest.mark.parametrize(
    ("goal", "rule"),
    [
        pytest.param("- G-1: Held: fast", "`Held: ` with no `. Threshold: ` and then `. Source: `", id="bare"),
        pytest.param(
            "- G-1: Held: fast. Threshold: a day", "`Held: ` with no `. Threshold: ` and then `. Source: `", id="no src"
        ),
        pytest.param(
            "- G-1: Held: fast. Source: metrics", "`Held: ` with no `. Threshold: ` and then `. Source: `", id="no thr"
        ),
        pytest.param(
            "- G-1: Held: fast. Source: metrics. Threshold: a day",
            "`Held: ` with no `. Threshold: ` and then `. Source: `",
            id="out of order",
        ),
        pytest.param("- G-1: Held: . Threshold: a day. Source: m", "its statement is empty", id="empty statement"),
        pytest.param("- G-1: Held: fast. Threshold:  . Source: m", "its threshold is empty", id="empty threshold"),
        pytest.param(
            "- G-1: Held: fast. Threshold: a day. Source:  ",
            "`Held: ` with no `. Threshold: ` and then `. Source: `",
            id="empty source",
        ),
    ],
)
def test_s105_2_check_refuses_a_malformed_measure_naming_file_line_and_goal(
    tmp_path: Path, goal: str, rule: str
) -> None:
    root = write(tmp_path, direction(goal + "\n"))
    found = [str(p) for p in check(root)]
    assert len(found) == 1, found
    assert found[0].startswith(f"docs/product.md:13: G-1: {rule}"), found
    assert found[0].endswith(HELD), found
    assert run(root, "check") == 1


@pytest.mark.parametrize(
    "goal",
    [
        "- G-1: Held: fast. Threshold: a day. Source: m. By: 2026-12-31",
        "- G-1: Fast. Check: p90. Source: metrics. By: 2026-12-31",
        "- G-1: Fast. Threshold: a day. Check: p90. By: 2026-12-31",
    ],
)
def test_s105_2_check_refuses_a_text_with_both_forms_labels(tmp_path: Path, goal: str) -> None:
    root = write(tmp_path, direction(goal + "\n"))
    found = [str(p) for p in check(root)]
    assert len(found) == 1, found
    assert found[0].startswith("docs/product.md:13: G-1: the text holds both a goal's labels"), found
    assert FORM in found[0] and HELD in found[0], found
    assert run(root, "check") == 1


def test_s105_2_check_refuses_a_measure_line_under_a_goal_of_kind_goal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    goals = "- G-1: Fast. Check: p90. By: 2026-12-31\n  measure: issue_to_release_p90 < 2d\n"
    root = write(tmp_path, direction(goals))
    found = [str(p) for p in check(root)]
    assert len(found) == 1, found
    assert found[0].startswith("docs/product.md:14: G-1 is a goal, which ends on its check"), found
    assert "Held: <statement>" in found[0]
    assert run(root, "check") == 1
    assert capsys.readouterr().out.splitlines() == found


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("Fast. Check: p90. By:  ", "its horizon is empty"),
        ("Held: fast. Threshold: a day. Source:  ", "its source is empty"),
        ("Fast. Check: p90. By: 2026-13-01", "`2026-13-01` is not a calendar date"),
        ("Fast. Check: p90. By: 2026-02-29", "`2026-02-29` is not a calendar date"),
    ],
)
def test_s105_2_read_goal_refuses_an_empty_part_and_an_invalid_date(text: str, rule: str) -> None:
    with pytest.raises(ReleaseError, match=rule):
        read_goal(text)


def test_s105_2_only_goals_are_read_for_kinds(tmp_path: Path) -> None:
    text = direction(GOALS).replace("- Q-1: Tested", "- Q-1: Tested. Check: ci. By: Q4")
    assert check(write(tmp_path, text)) == ()


def test_s105_2_show_refuses_a_malformed_goal(tmp_path: Path) -> None:
    root = write(tmp_path, direction("- G-1: Fast. Check: p90. By: Q4\n"))
    with pytest.raises(ReleaseError, match=r"docs/product.md:13: G-1: a horizon is a date"):
        run(root, "show", "--json")


def test_s105_3_a_period_and_a_space_inside_the_outcome_or_check_reads_whole() -> None:
    form = read_goal("A. B. Check: C. D. By: 2026-12-31")
    assert form == GoalForm("A. B", "C. D", Horizon.parse("2026-12-31"))
    assert str(form) == "A. B. Check: C. D. By: 2026-12-31"
    measure = read_goal("Held: A. B. Threshold: C. D. Source: E. F")
    assert measure == MeasureForm("A. B", "C. D", "E. F")
    later = read_goal("A. Check: C. By: then. By: v1.2.0")  # split at the last `. By: `
    assert isinstance(later, GoalForm) and later.check == "C. By: then" and later.by.release == "v1.2.0"


def test_s105_3_a_form_built_from_parts_that_dont_read_back_is_refused() -> None:
    with pytest.raises(ReleaseError, match="doesn't read back"):
        GoalForm("A. Check: B", "C", Horizon.parse("0.7.0"))
    with pytest.raises(ReleaseError, match="its check is empty"):
        GoalForm("A", " ", Horizon.parse("0.7.0"))
    with pytest.raises(ReleaseError, match="both a goal's labels"):
        MeasureForm("A", "B. Check: C", "D")
    with pytest.raises(ReleaseError, match="a horizon is"):
        Horizon("Q4", None)


NULLS = {
    "outcome": None,
    "check": None,
    "by": None,
    "past": None,
    "held": None,
    "threshold": None,
    "source": None,
    "state": None,
    "ended": None,
}


def test_s105_4_show_json_gives_every_goal_its_kinds_fields(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = write(tmp_path, direction(GOALS))
    assert run(root, "show", "--json", "--section", "goals") == 0
    goals = json.loads(capsys.readouterr().out)["goals"]
    today = dt.datetime.now(dt.UTC).date()
    measure = {"metric": "change_failure_rate", "comparison": "<=", "target": 0.05, "unit": "ratio"}
    assert goals == [
        {
            "id": "G-1",
            "text": "Widgets reach buyers in a day. Check: the p90 is under a day. By: 2026-12-31",
            "measure": None,
            "serves": [],
        }
        | NULLS
        | {
            "kind": "goal",
            "outcome": "Widgets reach buyers in a day",
            "check": "the p90 is under a day",
            "by": {"date": "2026-12-31"},
            "past": today > dt.date(2026, 12, 31),
        },
        {
            "id": "G-2",
            "text": "Buyers can track a widget. Check: `track` names its van. By: 0.7.0",
            "measure": None,
            "serves": [],
        }
        | NULLS
        | {
            "kind": "goal",
            "outcome": "Buyers can track a widget",
            "check": "`track` names its van",
            "by": {"release": "0.7.0"},
        },
        {
            "id": "G-3",
            "text": "Held: widgets arrive whole. Threshold: its measure line. Source: the weekly metrics",
            "measure": measure | {"text": "change_failure_rate <= 5%"},
            "serves": [],
        }
        | NULLS
        | {
            "kind": "measure",
            "held": "widgets arrive whole",
            "threshold": "its measure line",
            "source": "the weekly metrics",
        },
        {
            "id": "G-4",
            "text": "Held: buyers come back. Threshold: half of them. Source: the shop's ledger",
            "measure": None,
            "serves": [],
        }
        | NULLS
        | {"kind": "measure", "held": "buyers come back", "threshold": "half of them", "source": "the shop's ledger"},
        {"id": "G-5", "text": "Widgets are cheap", "measure": None, "serves": [], "kind": None} | NULLS,
    ]


def test_s105_4_other_items_and_the_text_output_are_as_before(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write(tmp_path, direction(GOALS))
    assert run(root, "show", "--json", "--section", "users") == 0
    assert json.loads(capsys.readouterr().out) == {"users": [{"id": "U-1", "text": "A buyer"}]}
    assert run(root, "show", "--section", "goals") == 0
    assert capsys.readouterr().out == f"## Goals\n\n{GOALS}"


def test_s105_4_a_components_product_goals_read_the_same_way() -> None:
    """Spec 071: the home's direction is read by the same grammar, its goals' kinds included"""
    home = read_home("acme/home", lambda path: direction(GOALS) if path == str(DIRECTION) else None)
    record = home.record([Section.GOALS], today=dt.date(2027, 1, 1))
    assert [goal["kind"] for goal in record["goals"]] == ["goal", "goal", "measure", "measure", None]
    assert record["goals"][0]["past"] is True
    with pytest.raises(ReleaseError, match=r"acme/home:docs/product.md:13: G-1: a horizon is a date"):
        read_home("acme/home", lambda path: direction("- G-1: Fast. Check: p90. By: Q4\n"))


@pytest.mark.parametrize(
    ("today", "past"),
    [(dt.date(2026, 12, 30), False), (dt.date(2026, 12, 31), False), (dt.date(2027, 1, 1), True)],
)
def test_s105_5_a_date_horizon_is_past_once_the_date_has_ended(tmp_path: Path, today: dt.date, past: bool) -> None:
    assert Horizon.parse("2026-12-31").past(today) is past
    goal = read(write(tmp_path, direction(GOALS))).goals[0]
    assert goal.record(today=today)["past"] is past


def test_s105_5_past_is_null_for_a_release_a_measure_and_a_goal_of_no_kind(tmp_path: Path) -> None:
    assert Horizon.parse("v1.2.0").past(dt.date(2099, 1, 1)) is None
    goals = read(write(tmp_path, direction(GOALS))).goals
    later = dt.date(2099, 1, 1)
    assert [goal.record(today=later)["past"] for goal in goals] == [True, None, None, None, None]
