"""Spec 027: a goal's optional `  measure: <metric> <comparison> <target>` line, read by
`shipmill product check|show|ids`"""

import json
from pathlib import Path

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.product import DIRECTION, Comparison, Measure, Metric, Unit, check, read

WELL_FORMED = """\
# Acme

## Mission

Acme ships widgets.

## Users

- U-1: A widget buyer

## Goals

- G-1: Widgets reach buyers in a day
  measure: issue_to_release_median < 1d
- G-2: Buyers can track a widget
- G-3: People rarely touch the agents' work
  measure: human_touch <= 20%

## Non-goals

- N-1: Gadgets

## Quality bar

- Q-1: Every widget is tested
"""
G1_MEASURE = "  measure: issue_to_release_median < 1d\n"
GOALS = WELL_FORMED[WELL_FORMED.index("## Goals") : WELL_FORMED.index("## Non-goals")]
MOVED = WELL_FORMED.replace(GOALS, "## Goals\n\nSee [Goals](product/goals.md).\n\n")


def write(root: Path, text: str, path: Path = DIRECTION) -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return root


def moved(root: Path, goals: str = GOALS) -> Path:
    write(root, MOVED)
    return write(root, goals, Path("docs/product/goals.md"))


def run(root: Path, *args: str) -> int:
    return main(["--repo", str(root), "product", *args])


def test_s027_1_check_accepts_goals_with_and_without_a_measure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write(tmp_path, WELL_FORMED)
    assert check(root) == ()
    assert run(root, "check") == 0
    assert capsys.readouterr().out == f"{DIRECTION}: well formed, 6 items\n"
    goals = read(root).goals
    assert [g.measure is not None for g in goals] == [True, False, True]


def test_s027_1_check_accepts_measures_in_a_goals_section_moved_to_docs_product(tmp_path: Path) -> None:
    root = moved(tmp_path)
    assert check(root) == ()
    assert read(root) == read(write(tmp_path / "inline", WELL_FORMED))


@pytest.mark.parametrize(
    ("text", "metric", "comparison", "target", "unit"),
    [
        ("deploy_frequency >= 5/week", Metric.DEPLOY_FREQUENCY, Comparison.AT_LEAST, 5.0, Unit.PER_WEEK),
        ("lead_time_median < 36h", Metric.LEAD_TIME_MEDIAN, Comparison.LESS, 36.0, Unit.HOURS),
        ("lead_time_p90 <= 2.5d", Metric.LEAD_TIME_P90, Comparison.AT_MOST, 60.0, Unit.HOURS),
        ("change_failure_rate < 15%", Metric.CHANGE_FAILURE_RATE, Comparison.LESS, 0.15, Unit.RATIO),
        ("time_to_restore_median <= 4h", Metric.TIME_TO_RESTORE_MEDIAN, Comparison.AT_MOST, 4.0, Unit.HOURS),
        ("issue_to_release_median < 1d", Metric.ISSUE_TO_RELEASE_MEDIAN, Comparison.LESS, 24.0, Unit.HOURS),
        ("issue_to_release_p90 < 3d", Metric.ISSUE_TO_RELEASE_P90, Comparison.LESS, 72.0, Unit.HOURS),
        ("human_touch <= 20%", Metric.HUMAN_TOUCH, Comparison.AT_MOST, 0.2, Unit.RATIO),
        ("agent_share > 0%", Metric.AGENT_SHARE, Comparison.MORE, 0.0, Unit.RATIO),
        ("agent_share >= 100%", Metric.AGENT_SHARE, Comparison.AT_LEAST, 1.0, Unit.RATIO),
    ],
)
def test_s027_1_every_registry_metric_and_comparison_parses_in_its_unit(
    tmp_path: Path, text: str, metric: Metric, comparison: Comparison, target: float, unit: Unit
) -> None:
    measure = Measure.parse(text)
    assert (measure.metric, measure.comparison, measure.target, measure.unit) == (metric, comparison, target, unit)
    root = write(tmp_path, WELL_FORMED.replace(G1_MEASURE, f"  measure: {text}\n"))
    assert check(root) == ()
    assert read(root).goals[0].measure == measure


def test_s027_1_the_registry_is_the_spec_s_nine_metrics() -> None:
    assert {m.value: m.unit.value for m in Metric} == {
        "deploy_frequency": "per week",
        "lead_time_median": "hours",
        "lead_time_p90": "hours",
        "change_failure_rate": "ratio",
        "time_to_restore_median": "hours",
        "issue_to_release_median": "hours",
        "issue_to_release_p90": "hours",
        "human_touch": "ratio",
        "agent_share": "ratio",
    }


KNOWN = ", ".join(m.value for m in Metric)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            WELL_FORMED.replace(G1_MEASURE, "  measure: uptime < 1d\n"),
            f"docs/product.md:14: `uptime` is not a known metric; they are {KNOWN}",
            id="unknown metric",
        ),
        pytest.param(
            WELL_FORMED.replace(G1_MEASURE, "  measure: human_touch == 20%\n"),
            "docs/product.md:14: `==` is not a comparison; it is one of `<`, `<=`, `>`, `>=`",
            id="unknown comparison",
        ),
        pytest.param(
            WELL_FORMED.replace(G1_MEASURE, "  measure: issue_to_release_median < 20%\n"),
            "docs/product.md:14: `issue_to_release_median` takes a target in `<n>h` or `<n>d`, a non-negative"
            " number; got `20%`",
            id="ratio for an hours metric",
        ),
        pytest.param(
            WELL_FORMED.replace(G1_MEASURE, "  measure: human_touch <= 0.2\n"),
            "docs/product.md:14: `human_touch` takes a target in `<n>%`",
            id="no unit",
        ),
        pytest.param(
            WELL_FORMED.replace(G1_MEASURE, "  measure: deploy_frequency > 5d\n"),
            "docs/product.md:14: `deploy_frequency` takes a target in `<n>/week`",
            id="hours for a per-week metric",
        ),
        pytest.param(
            WELL_FORMED.replace(G1_MEASURE, "  measure: human_touch <= -5%\n"),
            "docs/product.md:14: `human_touch` takes a target in `<n>%`, a non-negative number; got `-5%`",
            id="negative target",
        ),
        pytest.param(
            WELL_FORMED.replace(G1_MEASURE, "  measure: human_touch <= 120%\n"),
            "docs/product.md:14: a percentage lies between 0 and 100; got `120%`",
            id="percentage above 100",
        ),
        pytest.param(
            WELL_FORMED.replace(G1_MEASURE, "  measure: human_touch<=20%\n"),
            "docs/product.md:14: a measure is `<metric> <comparison> <target>`, single spaces between",
            id="no spaces",
        ),
        pytest.param(
            WELL_FORMED.replace(G1_MEASURE, "  measure: human_touch  <= 20%\n"),
            "docs/product.md:14: a measure is `<metric> <comparison> <target>`, single spaces between",
            id="two spaces",
        ),
        pytest.param(
            WELL_FORMED.replace(G1_MEASURE, "    measure: human_touch <= 20%\n"),
            "docs/product.md:14: a measure line is `  measure: <metric> <comparison> <target>`, indented by two spaces",
            id="indented by four",
        ),
        pytest.param(
            WELL_FORMED.replace(G1_MEASURE, G1_MEASURE + "  measure: human_touch <= 20%\n"),
            "docs/product.md:15: a second measure line under G-1; a goal carries at most one",
            id="second measure line",
        ),
        pytest.param(
            WELL_FORMED.replace(G1_MEASURE, "\n" + G1_MEASURE),
            "docs/product.md:15: a measure line sits right under its goal's item line; this one is after a blank line",
            id="after a blank line",
        ),
        pytest.param(
            WELL_FORMED.replace("- N-1: Gadgets\n", "- N-1: Gadgets\n  measure: human_touch < 5%\n"),
            "docs/product.md:22: a measure line sits only under a goal; `## Non-goals` holds none",
            id="under a non-goal",
        ),
        pytest.param(
            WELL_FORMED.replace("- U-1: A widget buyer\n", "- U-1: A widget buyer\n  measure: human_touch < 5%\n"),
            "docs/product.md:10: a measure line sits only under a goal; `## Users` holds none",
            id="under a user",
        ),
        pytest.param(
            WELL_FORMED.replace("- Q-1: Every widget is tested\n", "- Q-1: Every widget is tested\n  measure: x\n"),
            "docs/product.md:26: a measure line sits only under a goal; `## Quality bar` holds none",
            id="under a quality-bar item",
        ),
        pytest.param(
            WELL_FORMED.replace("- G-2: Buyers can track a widget\n", "- G-2: Buyers can track\n  a widget\n"),
            "docs/product.md:16: not an item of the form `- G-<n>: <text>`: `  a widget`",
            id="any other indented line is still an error",
        ),
    ],
)
def test_s027_2_check_exits_1_naming_the_file_line_and_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, expected: str
) -> None:
    root = write(tmp_path, text)
    found = [str(p) for p in check(root)]
    assert len(found) == 1 and found[0].startswith(expected), found
    assert run(root, "check") == 1
    assert capsys.readouterr().out.splitlines() == found


def test_s027_2_a_broken_measure_in_a_moved_goals_section_names_that_file(tmp_path: Path) -> None:
    root = moved(tmp_path, GOALS.replace("human_touch <= 20%", "human_touch <= 101%"))
    assert [str(p) for p in check(root)] == ["docs/product/goals.md:7: a percentage lies between 0 and 100; got `101%`"]
    root = moved(tmp_path / "second", GOALS.replace(G1_MEASURE, G1_MEASURE * 2))
    assert [str(p) for p in check(root)] == [
        "docs/product/goals.md:5: a second measure line under G-1; a goal carries at most one"
    ]


def test_s027_2_a_measure_is_a_value_object_that_refuses_what_check_refuses() -> None:
    for bad in ("uptime < 1d", "human_touch = 20%", "human_touch <= 101%", "lead_time_median < 1w", ""):
        with pytest.raises(ReleaseError):
            Measure.parse(bad)


def test_s027_3_show_json_gives_every_goal_a_measure_key(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write(tmp_path, WELL_FORMED), "show", "--json") == 0
    record = json.loads(capsys.readouterr().out)
    assert record["goals"] == [
        {
            "id": "G-1",
            "text": "Widgets reach buyers in a day",
            "measure": {
                "metric": "issue_to_release_median",
                "comparison": "<",
                "target": 24.0,
                "unit": "hours",
                "text": "issue_to_release_median < 1d",
            },
        },
        {"id": "G-2", "text": "Buyers can track a widget", "measure": None},
        {
            "id": "G-3",
            "text": "People rarely touch the agents' work",
            "measure": {
                "metric": "human_touch",
                "comparison": "<=",
                "target": 0.2,
                "unit": "ratio",
                "text": "human_touch <= 20%",
            },
        },
    ]
    for key in ("users", "non_goals", "quality"):
        assert all("measure" not in item for item in record[key]), record[key]


def test_s027_3_show_json_of_a_per_week_measure_and_a_moved_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = moved(tmp_path, GOALS.replace("human_touch <= 20%", "deploy_frequency >= 5/week"))
    assert run(root, "show", "--section", "goals", "--json") == 0
    measure = json.loads(capsys.readouterr().out)["goals"][2]["measure"]
    assert measure == {
        "metric": "deploy_frequency",
        "comparison": ">=",
        "target": 5.0,
        "unit": "per week",
        "text": "deploy_frequency >= 5/week",
    }


def test_s027_3_the_text_output_prints_each_measure_line_under_its_goal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write(tmp_path, WELL_FORMED)
    assert run(root, "show") == 0
    assert capsys.readouterr().out == WELL_FORMED
    assert run(moved(tmp_path / "moved"), "show", "--section", "goals") == 0
    assert capsys.readouterr().out == GOALS.rstrip("\n") + "\n"


def test_s027_3_ids_stays_one_line_per_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write(tmp_path, WELL_FORMED), "ids") == 0
    assert capsys.readouterr().out.splitlines() == [
        "U-1: A widget buyer",
        "G-1: Widgets reach buyers in a day",
        "G-2: Buyers can track a widget",
        "G-3: People rarely touch the agents' work",
        "N-1: Gadgets",
        "Q-1: Every widget is tested",
    ]
