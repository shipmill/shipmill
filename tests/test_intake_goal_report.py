"""intake_state.py --plans reads spec 027's goal report (#1764): a goal the report reads stalled
gets a `stalled` plan, and a goal whose measure it reads met gets no `no-work` plan"""

import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_intake_plans import BOT, GOALS, PLANS_NOW, SCRIPT, Fake, issue, plan, triaged, undated


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    spec = importlib.util.spec_from_file_location("intake_state_goal_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def goal_entry(goal: str, status: str = "no measure", *, stalled: bool = False) -> dict[str, Any]:
    """One goal of `retro.py gather --goals --json`'s report, the keys intake reads and some it doesn't"""
    return {"id": goal, "text": "t", "status": status, "stalled": stalled, "weeks_unserved": 3 if stalled else 0}


def gathered(*entries: dict[str, Any]) -> dict[str, Any]:
    """`retro.py gather --goals --json`'s output around the goals' entries"""
    goals = {"direction": True, "goals": list(entries)}
    return {"window": {}, "metrics": [], "refused": [], "reworked": [], "goals": goals}


def everyone(**special: dict[str, Any]) -> dict[str, Any]:
    """The report for GOALS: each goal neither met nor stalled, but the ones given"""
    return gathered(*(special.get(g.replace("-", "_"), goal_entry(g)) for g, _ in GOALS))


def due(
    ist: ModuleType,
    fake: Fake,
    report: dict[str, Any],
    *,
    wip: int | None = None,
    room: int = 1,
    goals: Sequence[tuple[str | None, ...]] = GOALS,
    reads: list[int] | None = None,
) -> dict[str, tuple[str, str]]:
    """Each goal's plan row as (state, note), the report read from the parsed gather output"""

    def read_report() -> Any:
        if reads is not None:
            reads.append(1)
        return ist.parse_goal_report(json.dumps(report))

    intake = ist.fetch(
        "o/r",
        label="opportunity",
        accepted="planned",
        marker="Triage:",
        skip=set(ist.SKIP_LABELS),
        categories=None,
        autonomy="propose",
        run=fake,
    )
    found = ist.fetch_plans(
        "o/r",
        intake,
        now=PLANS_NOW,
        goals=lambda: [ist.Goal(*g) for g in goals],
        marker="Triage:",
        bot_login=BOT,
        wip=wip,
        room=lambda limit: room,
        run=fake,
        report=read_report,
    )
    return {r.goal: (r.state, undated(r.note)) for r in found if r.kind == "goal"}


def test_s028_19_a_goal_the_report_reads_stalled_gets_a_stalled_plan(ist: ModuleType) -> None:
    report = everyone(G_2=goal_entry("G-2", stalled=True))
    assert due(ist, Fake(), report) == {
        "G-1": ("PLAN_DUE", "no-work"),
        "G-2": ("PLAN_DUE", "stalled"),
        "G-3": ("PLAN_DUE", "no-work"),
    }


def test_s028_19_stalled_is_read_for_a_served_or_declined_goal_too(ist: ModuleType) -> None:
    """Stalled counts the work that closed, so open work serving the goal doesn't stop it, and
    only a stalled report or a request proposes a plan again after a decline (spec 028)"""
    served = issue(5, triaged("Triage: **feature**. Serves: G-1."))
    declined = plan(20, "G-3", state="CLOSED", reason="NOT_PLANNED")
    report = everyone(G_1=goal_entry("G-1", stalled=True), G_3=goal_entry("G-3", stalled=True))
    assert due(ist, Fake([served], plans=[declined]), report) == {
        "G-1": ("PLAN_DUE", "stalled"),
        "G-2": ("PLAN_DUE", "no-work"),
        "G-3": ("PLAN_DUE", "stalled"),
    }


def test_s028_19_an_open_plan_a_request_or_a_measure_still_decide_first(ist: ModuleType) -> None:
    open_plan = plan(20, "G-1")
    request = issue(25, title="Plan G-2", labels=("goal-plan",), association="OWNER")
    report = gathered(*(goal_entry(g, stalled=True) for g, _ in GOALS))
    goals = [("G-1", "a", "goal"), ("G-2", "b", "goal"), ("G-3", "c", "measure")]
    assert due(ist, Fake([open_plan, request], plans=[open_plan]), report, goals=goals) == {
        "G-2": ("PLAN_DUE", "requested in #25"),
    }


def test_s028_4_a_stalled_plan_waits_for_room_as_no_work_does(ist: ModuleType) -> None:
    report = everyone(G_2=goal_entry("G-2", stalled=True))
    assert due(ist, Fake(), report, wip=2, room=0) == {
        "G-1": ("PLAN_WAITS", "no-work; waits for room"),
        "G-2": ("PLAN_WAITS", "stalled; waits for room"),
        "G-3": ("PLAN_WAITS", "no-work; waits for room"),
    }


def test_s028_20_a_goal_the_report_reads_met_gets_no_no_work_plan(ist: ModuleType) -> None:
    report = everyone(G_1=goal_entry("G-1", "met"), G_3=goal_entry("G-3", "not met"))
    assert due(ist, Fake(), report) == {"G-2": ("PLAN_DUE", "no-work"), "G-3": ("PLAN_DUE", "no-work")}
    assert due(ist, Fake(), report, wip=1, room=0) == {
        "G-2": ("PLAN_WAITS", "no-work; waits for room"),
        "G-3": ("PLAN_WAITS", "no-work; waits for room"),
    }


def test_s028_20_a_met_goal_still_reads_a_request(ist: ModuleType) -> None:
    request = issue(25, title="Plan G-1", labels=("goal-plan",), association="OWNER")
    report = everyone(G_1=goal_entry("G-1", "met"))
    assert due(ist, Fake([request]), report)["G-1"] == ("PLAN_DUE", "requested in #25")


def test_the_report_is_read_once_and_only_when_a_goal_reaches_the_automatic_triggers(ist: ModuleType) -> None:
    reads: list[int] = []
    due(ist, Fake(), everyone(), reads=reads)
    assert reads == [1]
    reads.clear()
    ended = [("G-1", "a", "goal", "met"), ("G-2", "b", "measure"), ("G-3", "c", None, "dropped")]
    assert due(ist, Fake(), everyone(), goals=ended, reads=reads) == {}
    assert reads == []


def test_a_goal_the_report_leaves_out_exits_2(ist: ModuleType) -> None:
    with pytest.raises(SystemExit) as caught:
        due(ist, Fake(), gathered(goal_entry("G-1"), goal_entry("G-2")))
    assert caught.value.code == 2


@pytest.mark.parametrize(
    "printed",
    [
        "not json",
        json.dumps([]),
        json.dumps({"window": {}}),  # gathered without --goals
        json.dumps({"goals": {"direction": False}}),  # no docs/product.md in the checkout
        json.dumps({"goals": {"direction": True, "goals": {}}}),
        json.dumps(gathered({"id": "G-1", "status": "met"})),  # no stalled
        json.dumps(gathered(goal_entry("G-1", "done"))),  # no such status
        json.dumps(gathered({**goal_entry("G-1"), "stalled": "yes"})),
        json.dumps(gathered({**goal_entry("G-1"), "id": "goal one"})),
        json.dumps(gathered(goal_entry("G-1"), goal_entry("G-1", "met"))),  # one goal twice
    ],
)
def test_a_report_that_cant_be_read_exits_2(ist: ModuleType, printed: str) -> None:
    with pytest.raises(SystemExit) as caught:
        ist.parse_goal_report(printed)
    assert caught.value.code == 2


def test_the_report_is_retro_gathers(ist: ModuleType, tmp_path: Path) -> None:
    """The default reader runs retro.py gather --goals --json on the checkout, with the --bot-login
    as --bot, and reads its output; a gather that fails exits 2 naming it"""
    stub = tmp_path / "retro.py"
    printed = json.dumps(gathered(goal_entry("G-1", "met"), goal_entry("G-2", stalled=True)))
    expected = ["gather", "o/r", "--goals", "--checkout", str(tmp_path), "--json", "--bot", "b[bot]"]
    stub.write_text(f"import sys\nassert sys.argv[1:] == {expected!r}, sys.argv\nprint({printed!r})\n")
    found = ist.retro_report("o/r", "b[bot]", tmp_path, stub)()
    assert {g: (r.met, r.stalled) for g, r in found.items()} == {"G-1": (True, False), "G-2": (False, True)}
    stub.write_text("import sys\nsys.stderr.write('error: not at origin/HEAD\\n')\nsys.exit(2)\n")
    with pytest.raises(SystemExit) as caught:
        ist.retro_report("o/r", None, tmp_path, stub)()
    assert caught.value.code == 2


def test_the_reader_runs_ship_watchs_retro(ist: ModuleType) -> None:
    assert SCRIPT.parents[2] / "github-ship-watch" / "scripts" / "retro.py" == ist.RETRO
    assert ist.RETRO.is_file()
