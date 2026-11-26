"""Spec 106: a goal of kind goal ends met or dropped, the maintainer's record in the direction:
`. Met: <date>` or `. Dropped: <date>: <reason>` after its horizon. `product check` refuses a
malformed end, `product show --json` gives `state` and `ended`, and `product met` and `product
drop` write the sentence"""

import datetime as dt
import json
from pathlib import Path

import pytest

from shipmill.errors import ReleaseError
from shipmill.product import DIRECTION, GoalEnd, GoalForm, check, read_goal

from .test_product_kinds import GOALS, direction, run, write

MET = "- G-1: Widgets reach buyers in a day. Check: the p90 is under a day. By: 2026-12-31. Met: 2026-12-20"
DROPPED = (
    "- G-2: Buyers can track a widget. Check: `track` names its van. By: 0.7.0. Dropped: 2026-12-01: no vans. By: then"
)


# -- S-106-1 --------------------------------------------------------------------------------


def test_s106_1_check_accepts_a_met_or_dropped_goal(tmp_path: Path) -> None:
    root = write(tmp_path, direction(f"{MET}\n{DROPPED}\n"))
    assert check(root) == ()
    met = read_goal(MET.removeprefix("- G-1: "))
    assert isinstance(met, GoalForm) and met.end == GoalEnd(dt.date(2026, 12, 20), None)
    assert met.by.text == "2026-12-31" and str(met) == MET.removeprefix("- G-1: ")
    dropped = read_goal(DROPPED.removeprefix("- G-2: "))
    assert isinstance(dropped, GoalForm) and dropped.end is not None
    assert (dropped.end.state, dropped.end.reason, dropped.by.text) == ("dropped", "no vans. By: then", "0.7.0")


@pytest.mark.parametrize(
    ("goal", "rule"),
    [
        pytest.param(
            "- G-1: Held: whole. Threshold: all. Source: m. Met: 2026-12-20",
            "only a goal of kind goal ends met or dropped",
            id="measure",
        ),
        pytest.param("- G-1: Widgets are cheap. Met: 2026-12-20", "only a goal of kind goal ends", id="kind none"),
        pytest.param("- G-1: A. Check: b. By: 2026-12-31. Met: 2026-13-01", "is not a calendar date", id="bad date"),
        pytest.param("- G-1: A. Check: b. By: 2026-12-31. Met: soon", "is no date `YYYY-MM-DD`", id="no date"),
        pytest.param(
            "- G-1: A. Check: b. By: 2026-12-31. Met: 2026-12-20 and more", "is no date", id="text after the date"
        ),
        pytest.param("- G-1: A. Check: b. By: 2026-12-31. Dropped: 2026-12-01:  ", "names its reason", id="no reason"),
        pytest.param(
            "- G-1: A. Check: b. By: 2026-12-31. Dropped: 2026-12-01", "names its reason", id="no reason part"
        ),
        pytest.param(
            "- G-1: A. Check: b. By: 2026-12-31. Met: 2026-12-20. Dropped: 2026-12-21: x",
            "ends met or dropped, not both",
            id="both",
        ),
    ],
)
def test_s106_1_check_refuses_a_malformed_end_naming_the_goal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], goal: str, rule: str
) -> None:
    root = write(tmp_path, direction(goal + "\n"))
    found = [str(p) for p in check(root)]
    assert len(found) == 1 and found[0].startswith("docs/product.md:13: G-1: "), found
    assert rule in found[0], found
    assert run(root, "check") == 1  # as every refused line (spec 024, and #1747 for spec 105)
    assert capsys.readouterr().out.splitlines() == found


# -- S-106-2 --------------------------------------------------------------------------------


def test_s106_2_show_json_gives_every_goal_its_state_and_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write(tmp_path, direction(f"{MET}\n{DROPPED}\n" + GOALS.split("\n", 2)[2]))
    assert run(root, "show", "--section", "goals", "--json") == 0
    goals = json.loads(capsys.readouterr().out)["goals"]
    assert [(g["id"], g["state"], g["ended"]) for g in goals] == [
        ("G-1", "met", "2026-12-20"),
        ("G-2", "dropped", "2026-12-01"),
        ("G-3", None, None),  # a measure
        ("G-4", None, None),
        ("G-5", None, None),  # a goal of kind none
    ]
    assert goals[0]["by"] == {"date": "2026-12-31"} and goals[0]["check"] == "the p90 is under a day"


def test_s106_2_product_met_and_drop_write_the_sentence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = write(tmp_path, direction(GOALS))
    assert run(root, "met", "G-1", "--on", "2026-12-20") == 0
    assert capsys.readouterr().out == f"{MET}\n"
    today = dt.datetime.now(dt.UTC).date().isoformat()
    assert run(root, "drop", "G-2", "--reason", "no vans") == 0
    dropped = f"- G-2: Buyers can track a widget. Check: `track` names its van. By: 0.7.0. Dropped: {today}: no vans"
    assert capsys.readouterr().out == f"{dropped}\n"
    text = (root / DIRECTION).read_text(encoding="utf-8")
    assert MET in text.splitlines() and dropped in text.splitlines()
    assert check(root) == ()  # the id stays, and the direction still reads


@pytest.mark.parametrize(
    ("args", "refusal"),
    [
        pytest.param(("met", "G-3"), "G-3 is a standing measure", id="measure"),
        pytest.param(("drop", "G-5", "--reason", "x"), "G-5 is a goal of kind none", id="kind none"),
        pytest.param(("met", "G-9"), "no G-9 in", id="unknown"),
        pytest.param(("met", "U-1"), "U-1 is not a G-n id", id="not a goal"),
        pytest.param(("met", "G-1", "--on", "2026-02-30"), "is not a calendar date", id="bad date"),
        pytest.param(("drop", "G-1", "--reason", "  "), "the text is one line, not empty", id="empty reason"),
    ],
)
def test_s106_2_met_and_drop_refuse_a_measure_and_an_unknown_goal(
    tmp_path: Path, args: tuple[str, ...], refusal: str
) -> None:
    root = write(tmp_path, direction(GOALS))
    before = (root / DIRECTION).read_text(encoding="utf-8")
    with pytest.raises(ReleaseError, match=refusal):
        run(root, *args)
    assert (root / DIRECTION).read_text(encoding="utf-8") == before


def test_s106_2_a_goal_already_ended_is_refused(tmp_path: Path) -> None:
    root = write(tmp_path, direction(f"{MET}\n{DROPPED}\n"))
    before = (root / DIRECTION).read_text(encoding="utf-8")
    with pytest.raises(ReleaseError, match="G-1 is already met on 2026-12-20; nothing was written"):
        run(root, "drop", "G-1", "--reason", "late")
    with pytest.raises(ReleaseError, match="G-2 is already dropped on 2026-12-01"):
        run(root, "met", "G-2")
    assert (root / DIRECTION).read_text(encoding="utf-8") == before


def test_s106_2_product_goal_keeps_an_ended_goals_record(tmp_path: Path) -> None:
    """spec 105's `product goal` rewrites a goal's check and horizon; on an ended goal it would
    drop the maintainer's record, so it is refused"""
    root = write(tmp_path, direction(f"{MET}\n"))
    before = (root / DIRECTION).read_text(encoding="utf-8")
    with pytest.raises(ReleaseError, match="G-1 is met on 2026-12-20, the maintainer's record"):
        run(root, "goal", "G-1", "--check", "faster", "--by", "2027-01-31")
    assert (root / DIRECTION).read_text(encoding="utf-8") == before
