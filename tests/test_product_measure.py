"""Spec 027: a goal's optional `  measure: <metric> <comparison> <target>` line, read by
`shipmill product check|show|ids`"""

import json
import re
from pathlib import Path

import pytest

from shipmill import product
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.product import DIRECTION, Comparison, ItemId, Measure, Metric, Unit, check, read

from .test_direction_edit import repo

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
    for bad in (
        "uptime < 1d",
        "human_touch = 20%",
        "human_touch <= 101%",
        "lead_time_median < 1w",
        "",
        "human_touch < 9%\n",
    ):
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


def test_s027_5_retire_removes_the_goals_measure_line_with_its_item(tmp_path: Path) -> None:
    g1 = "- G-1: Widgets reach buyers in a day\n" + G1_MEASURE
    root = write(tmp_path, WELL_FORMED)
    assert run(root, "retire", "G-1") == 0
    assert (root / DIRECTION).read_text() == WELL_FORMED.replace(g1, "")
    assert check(root) == ()
    assert run(root, "retire", "G-2") == 0  # no measure: only its line goes; G-3 keeps its own
    assert [(g.id.number, g.measure is not None) for g in read(root).goals] == [(3, True)]
    root = moved(tmp_path / "moved")
    assert run(root, "retire", "G-1") == 0
    assert (root / "docs/product/goals.md").read_text() == GOALS.replace(g1, "")
    assert check(root) == ()


def test_s027_4_measure_writes_replaces_and_clears_only_the_goals_measure_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write(tmp_path, WELL_FORMED)
    g2 = "- G-2: Buyers can track a widget\n"
    assert run(root, "measure", "G-2", "lead_time_p90 <= 2.5d") == 0
    assert capsys.readouterr().out == "  measure: lead_time_p90 <= 2.5d\n"
    expected = WELL_FORMED.replace(g2, g2 + "  measure: lead_time_p90 <= 2.5d\n")
    assert (root / DIRECTION).read_text() == expected
    assert run(root, "measure", "G-1", "deploy_frequency >= 5/week") == 0
    expected = expected.replace(G1_MEASURE, "  measure: deploy_frequency >= 5/week\n")
    assert (root / DIRECTION).read_text() == expected
    assert run(root, "measure", "G-3", "--clear") == 0
    assert capsys.readouterr().out.splitlines()[-1] == "  measure: human_touch <= 20%"
    expected = expected.replace("  measure: human_touch <= 20%\n", "")
    assert (root / DIRECTION).read_text() == expected
    assert check(root) == ()
    assert [None if g.measure is None else g.measure.text for g in read(root).goals] == [
        "deploy_frequency >= 5/week",
        "lead_time_p90 <= 2.5d",
        None,
    ]
    assert run(root, "measure", "G-3", "--clear") == 0  # nothing to clear: nothing written
    assert capsys.readouterr().out == "G-3 has no measure line; nothing written\n"
    assert (root / DIRECTION).read_text() == expected


def test_s027_4_measure_edits_a_goals_section_moved_to_docs_product(tmp_path: Path) -> None:
    root = moved(tmp_path)
    assert run(root, "measure", "G-1", "issue_to_release_p90 < 3d") == 0
    assert run(root, "measure", "G-3", "--clear") == 0
    assert (root / DIRECTION).read_text() == MOVED
    goals = GOALS.replace("issue_to_release_median < 1d", "issue_to_release_p90 < 3d")
    assert (root / "docs/product/goals.md").read_text() == goals.replace("  measure: human_touch <= 20%\n", "")
    assert check(root) == ()


def test_s027_4_measure_keeps_crlf_endings_and_a_missing_final_newline(tmp_path: Path) -> None:
    text = WELL_FORMED.replace("\n", "\r\n")
    path = tmp_path / DIRECTION
    write(tmp_path, "")
    path.write_bytes(text.encode())
    assert run(tmp_path, "measure", "G-2", "agent_share > 50%") == 0
    g2 = b"- G-2: Buyers can track a widget\r\n"
    assert path.read_bytes() == text.encode().replace(g2, g2 + b"  measure: agent_share > 50%\r\n")
    root = moved(tmp_path / "moved", GOALS.rstrip("\n"))  # a moved file ends with its last goal
    goals = root / "docs/product/goals.md"
    assert run(root, "measure", "G-3", "--clear") == 0
    assert goals.read_text() == GOALS.rstrip("\n").replace("\n  measure: human_touch <= 20%", "")
    assert run(root, "measure", "G-3", "human_touch < 10%") == 0
    assert goals.read_text() == GOALS.rstrip("\n").replace("<= 20%", "< 10%")


def test_s027_4_measure_writes_atomically_keeping_a_symlink_and_permissions(tmp_path: Path) -> None:
    root = moved(tmp_path)
    goals = root / "docs/product/goals.md"
    goals.rename(root / "docs/product/real.md")
    goals.symlink_to("real.md")
    (root / "docs/product/real.md").chmod(0o640)
    assert run(root, "measure", "G-2", "human_touch < 10%") == 0
    assert goals.is_symlink()
    assert "  measure: human_touch < 10%" in (root / "docs/product/real.md").read_text()
    assert (root / "docs/product/real.md").stat().st_mode & 0o777 == 0o640
    assert sorted(p.name for p in (root / "docs/product").iterdir()) == ["goals.md", "real.md"]


@pytest.mark.parametrize(
    ("args", "error"),
    [
        pytest.param(("G-9", "human_touch < 10%"), "no G-9 in docs/product.md", id="unlisted goal"),
        pytest.param(("N-1", "human_touch < 10%"), "only a goal carries a measure", id="not a goal"),
        pytest.param(("goal", "human_touch < 10%"), "an item id is", id="not an id"),
        pytest.param(("G-2", "uptime < 1d"), "`uptime` is not a known metric", id="unknown metric"),
        pytest.param(("G-2", "human_touch <= 120%"), "a percentage lies between 0 and 100", id="above 100"),
        pytest.param(("G-2", "human_touch < 10%\n"), "the text is one line", id="trailing newline"),
        pytest.param(("G-2", "human_touch < 10%\nx"), "the text is one line", id="two lines"),
    ],
)
def test_s027_4_measure_exits_2_without_writing(tmp_path: Path, args: tuple[str, str], error: str) -> None:
    root = write(tmp_path, WELL_FORMED)
    with pytest.raises(ReleaseError, match=re.escape(error)):  # the CLI's entry point exits 2 on it
        run(root, "measure", *args)
    assert (root / DIRECTION).read_text() == WELL_FORMED


def test_s027_4_measure_refuses_a_direction_check_refuses(tmp_path: Path) -> None:
    broken = WELL_FORMED.replace(G1_MEASURE, "  measure: uptime < 1d\n")
    root = write(tmp_path, broken)
    with pytest.raises(ReleaseError, match="doesn't pass"):
        product.measure(root, ItemId.parse("G-2"), Measure.parse("human_touch < 10%"))
    with pytest.raises(ReleaseError, match="doesn't pass"):
        run(root, "measure", "G-1", "--clear")
    assert (root / DIRECTION).read_text() == broken


def test_s027_4_measure_takes_a_measure_or_clear_not_both(tmp_path: Path) -> None:
    root = write(tmp_path, WELL_FORMED)
    for args in (("G-1",), ("G-1", "human_touch < 10%", "--clear")):
        with pytest.raises(SystemExit) as exited:
            run(root, "measure", *args)
        assert exited.value.code == 2
    assert (root / DIRECTION).read_text() == WELL_FORMED


def test_s027_5_edit_keeps_the_goals_measure_line(tmp_path: Path) -> None:
    root = write(tmp_path, WELL_FORMED)
    assert run(root, "edit", "G-1", "Widgets reach buyers in hours") == 0
    expected = WELL_FORMED.replace("in a day\n", "in hours\n")
    assert (root / DIRECTION).read_text() == expected
    assert read(root).goals[0].measure == Measure.parse("issue_to_release_median < 1d")


def test_s027_5_add_goals_appends_after_the_last_goals_measure_line(tmp_path: Path) -> None:
    root = repo(tmp_path / "inline", {"docs/product.md": WELL_FORMED})
    assert run(root, "add", "goals", "Widgets ship weekly") == 0
    expected = WELL_FORMED.replace(
        "  measure: human_touch <= 20%\n", "  measure: human_touch <= 20%\n- G-4: Widgets ship weekly\n"
    )
    assert (root / DIRECTION).read_text() == expected
    assert check(root) == ()
    root = repo(tmp_path / "moved", {"docs/product.md": MOVED, "docs/product/goals.md": GOALS})
    assert run(root, "add", "goals", "Widgets ship weekly") == 0
    assert (root / "docs/product/goals.md").read_text() == GOALS.replace(
        "  measure: human_touch <= 20%\n", "  measure: human_touch <= 20%\n- G-4: Widgets ship weekly\n"
    )


def test_s027_13_setup_offers_a_registry_measure_per_goal_and_writes_only_the_maintainers() -> None:
    skill = " ".join((Path(__file__).parents[1] / "skills/shipmill-setup/SKILL.md").read_text().split())
    assert "For each goal you write, offer a measure from the registry of spec 027" in skill
    for metric in Metric:
        assert f"`{metric.value}`" in skill
    assert 'Write only the measures the maintainer gives, each with `$CR product measure G-n "' in skill
    assert "a goal they give no measure gets none" in skill


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
