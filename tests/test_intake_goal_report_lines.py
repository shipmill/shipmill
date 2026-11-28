"""intake_state.py --plans --goals --json prints a `goal-report` line per goal of the direction,
read from the one spec 027 report its triggers read (spec 110, S-110-1 and S-110-2)"""

import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_intake_goal_report import gathered, goal_entry
from .test_intake_plans import BOT, PLANS_NOW, SCRIPT, Fake


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    spec = importlib.util.spec_from_file_location("intake_state_goal_report_lines", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# The direction: a goal of kind goal, a standing measure, a goal of no kind, and two ended goals
DIRECTION: list[tuple[str | None, ...]] = [
    ("G-1", "Releases go out on their own", "measure"),
    ("G-2", "Agents keep a quality bar", "goal"),
    ("G-3", "People hear", None),
    ("G-5", "Old goal", "goal", "met"),
    ("G-6", "Dropped goal", None, "dropped"),
]

REPORT = gathered(
    {**goal_entry("G-1", "met"), "value_text": "p90 1.2 d", "met_weeks": 4},
    {**goal_entry("G-2", "not met"), "value_text": "7%"},
    goal_entry("G-3", stalled=True),
    {**goal_entry("G-5", "no data"), "value_text": "no data"},
    goal_entry("G-6"),
)


def run_plans(
    ist: ModuleType,
    report: Any,
    *,
    direction: Sequence[tuple[str | None, ...]] = DIRECTION,
    readings: list[Any] | None = None,
) -> list[Any]:
    """fetch_plans as main runs it with --plans --goals: the plan rows, the readings filled in"""
    intake = ist.fetch(
        "o/r",
        label="opportunity",
        accepted="planned",
        marker="Triage:",
        skip=set(ist.SKIP_LABELS),
        categories=None,
        autonomy="propose",
        run=Fake(),
    )
    found: list[Any] = ist.fetch_plans(
        "o/r",
        intake,
        now=PLANS_NOW,
        goals=lambda: [ist.Goal(*g) for g in direction],
        marker="Triage:",
        bot_login=BOT,
        wip=None,
        room=lambda limit: 1,
        run=Fake(),
        report=report,
        readings=readings,
    )
    return found


def counting(ist: ModuleType, printed: str, calls: list[int]) -> Any:
    """A scripted report reader: counts its runs, then parses what retro.py gather printed"""

    def read() -> Any:
        calls.append(1)
        return ist.parse_goal_report(printed)

    return read


def json_lines(ist: ModuleType, readings: list[Any]) -> list[dict[str, Any]]:
    shown = ist.Shown("propose", None, None, (), [], [], [], [], readings)
    return [json.loads(line) for line in ist.output(shown, True)]


def test_s110_1_a_goal_report_line_per_goal_in_the_directions_order(ist: ModuleType) -> None:
    readings: list[Any] = []
    run_plans(ist, counting(ist, json.dumps(REPORT), []), readings=readings)
    lines = [line for line in json_lines(ist, readings) if line.get("kind") == "goal-report"]
    assert lines == [
        {
            "kind": "goal-report",
            "goal": "G-1",
            "goal_kind": "measure",
            "status": "met",
            "value_text": "p90 1.2 d",
            "met_weeks": 4,
            "stalled": False,
            "weeks_unserved": 0,
            "ended": None,
        },
        {
            "kind": "goal-report",
            "goal": "G-2",
            "goal_kind": "goal",
            "status": "not met",
            "value_text": "7%",
            "met_weeks": 0,
            "stalled": False,
            "weeks_unserved": 0,
            "ended": None,
        },
        {
            "kind": "goal-report",
            "goal": "G-3",
            "goal_kind": None,
            "status": "no measure",
            "value_text": None,
            "met_weeks": 0,
            "stalled": True,
            "weeks_unserved": 3,
            "ended": None,
        },
        {
            "kind": "goal-report",
            "goal": "G-5",
            "goal_kind": "goal",
            "status": "no data",
            "value_text": "no data",
            "met_weeks": 0,
            "stalled": False,
            "weeks_unserved": 0,
            "ended": "met",
        },
        {
            "kind": "goal-report",
            "goal": "G-6",
            "goal_kind": None,
            "status": "no measure",
            "value_text": None,
            "met_weeks": 0,
            "stalled": False,
            "weeks_unserved": 0,
            "ended": "dropped",
        },
    ]


def test_s110_1_the_lines_and_the_stalled_trigger_read_one_report_per_run(ist: ModuleType) -> None:
    calls: list[int] = []
    readings: list[Any] = []
    found = run_plans(ist, counting(ist, json.dumps(REPORT), calls), readings=readings)
    assert {r.goal: r.note for r in found if r.kind == "goal"}["G-3"] == "stalled"  # the trigger read it
    assert [g.id for g, _ in readings] == ["G-1", "G-2", "G-3", "G-5", "G-6"]
    assert calls == [1]


def test_s110_1_the_report_is_read_once_even_when_no_trigger_reads_it(ist: ModuleType) -> None:
    """Every goal ended or a measure: the triggers read no report, the lines still read it, once"""
    calls: list[int] = []
    readings: list[Any] = []
    direction = [("G-1", "a", "measure"), ("G-5", "b", "goal", "met")]
    report = gathered(goal_entry("G-1", "met"), goal_entry("G-5"))
    assert run_plans(ist, counting(ist, json.dumps(report), calls), direction=direction, readings=readings) == []
    assert [g.id for g, _ in readings] == ["G-1", "G-5"]
    assert calls == [1]


def test_s110_1_no_lines_without_docs_product_md(ist: ModuleType) -> None:
    """No direction, no goals: no plan rows, no report read, and no goal-report line"""
    calls: list[int] = []
    readings: list[Any] = []
    assert run_plans(ist, counting(ist, json.dumps(REPORT), calls), direction=[], readings=readings) == []
    assert readings == []
    assert calls == []
    assert json_lines(ist, readings) == [{"autonomy": "propose"}]


def test_s110_1_the_text_output_prints_no_goal_report_line(ist: ModuleType) -> None:
    readings: list[Any] = []
    run_plans(ist, counting(ist, json.dumps(REPORT), []), readings=readings)
    shown = ist.Shown("propose", None, None, (), [], [], [], [], readings)
    assert ist.output(shown, False) == ["intake autonomy: propose"]
    assert len(ist.output(shown, True)) == 1 + len(DIRECTION)


def test_s110_1_without_readings_the_lines_ask_nothing_of_the_run(ist: ModuleType) -> None:
    """--plans alone (or --goals alone) passes no readings: the report stays read only when a
    trigger needs it, as #1764 has it"""
    calls: list[int] = []
    direction = [("G-1", "a", "measure"), ("G-5", "b", "goal", "met")]
    report = gathered(goal_entry("G-1"), goal_entry("G-5"))
    assert run_plans(ist, counting(ist, json.dumps(report), calls), direction=direction) == []
    assert calls == []


def test_the_watch_reads_past_a_goal_report_line(ist: ModuleType) -> None:
    """watch_state.py's readers of intake's lines leave the new kind alone until #1839 reads it"""
    readings: list[Any] = []
    run_plans(ist, counting(ist, json.dumps(REPORT), []), readings=readings)
    ws = ist.watch_module()
    for line in ist.output(ist.Shown("propose", None, None, (), [], [], [], [], readings), True)[1:]:
        assert ws.plan_line(line) is None
        assert ws.goal_line(line) is None
        assert ws.feedback_line(line) is None


@pytest.mark.parametrize(
    "entry",
    [
        {k: v for k, v in goal_entry("G-1").items() if k != "value_text"},
        {k: v for k, v in goal_entry("G-1").items() if k != "met_weeks"},
        {k: v for k, v in goal_entry("G-1").items() if k != "weeks_unserved"},
        {**goal_entry("G-1"), "value_text": "7%"},  # a value for no measure
        {**goal_entry("G-1", "met"), "value_text": 7},
        {**goal_entry("G-1", "met"), "met_weeks": -1},
        {**goal_entry("G-1", "met"), "met_weeks": True},
        {**goal_entry("G-1", "met"), "weeks_unserved": "3"},
    ],
)
def test_s110_2_a_line_the_report_doesnt_carry_exits_2(ist: ModuleType, entry: dict[str, Any]) -> None:
    with pytest.raises(SystemExit) as caught:
        ist.parse_goal_report(json.dumps(gathered(entry)))
    assert caught.value.code == 2


def test_s110_2_a_report_that_cant_be_read_exits_2_and_prints_no_no_data_line(
    ist: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gather fails while every goal has ended, so no trigger would read it: the run still
    exits 2 naming the gather, and no goal-report line stands in for it"""
    stub = tmp_path / "retro.py"
    stub.write_text("import sys\nsys.stderr.write('error: not at origin/HEAD\\n')\nsys.exit(2)\n")
    readings: list[Any] = []
    direction = [("G-1", "a", "measure"), ("G-5", "b", "goal", "met")]
    with pytest.raises(SystemExit) as caught:
        run_plans(ist, ist.retro_report("o/r", BOT, tmp_path, stub), direction=direction, readings=readings)
    assert caught.value.code == 2
    err = capsys.readouterr().err
    assert "retro.py gather --goals failed with exit 2" in err
    assert "not at origin/HEAD" in err
    assert readings == []


def test_s110_2_a_goal_the_report_leaves_out_exits_2(ist: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    direction = [("G-1", "a", "measure"), ("G-5", "b", "goal", "met")]
    readings: list[Any] = []
    with pytest.raises(SystemExit) as caught:
        run_plans(
            ist, counting(ist, json.dumps(gathered(goal_entry("G-1"))), []), direction=direction, readings=readings
        )
    assert caught.value.code == 2
    assert "reported no G-5" in capsys.readouterr().err
    assert readings == []
