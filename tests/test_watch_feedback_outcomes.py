"""The watch reading product intake's lines under [agents] outcomes (spec 101): the autonomy
line's outcomes key, and a HELD request, without the network"""

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
NOW = dt.datetime(2026, 11, 26, 12, 0, tzinfo=dt.timezone.utc)  # noqa: UP017 (the script runs under 3.10 too)


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    spec = importlib.util.spec_from_file_location("watch_state_outcomes", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


def ago(hours: float) -> str:
    return (NOW - dt.timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def request(number: int, state: str, handed: str | None, note: str = "issue") -> dict[str, Any]:
    """A request's line as intake_state.py --json prints it (spec 074)"""
    found = {"number": number, "kind": "issue", "state": state, "title": "t", "thumbs": 0, "members": [], "note": note}
    return found | {"author": "amy", "association": "OWNER", "handed": handed}


def output(first: dict[str, Any], *rows: dict[str, Any]) -> str:
    return "\n".join(json.dumps(r, sort_keys=True) for r in (first, *rows)) + "\n"


OUTCOMES = {"limit": 3, "in_flight": 3, "room": 0}


def test_s101_10_the_autonomy_line_may_carry_the_outcomes(ws: ModuleType) -> None:
    assert ws.intake_level(output({"autonomy": "propose", "outcomes": OUTCOMES})) == "propose"
    assert ws.intake_level(output({"autonomy": "observe", "outcomes": {"limit": 3, "in_flight": 1, "room": 2}}))
    assert ws.intake_level(output({"autonomy": "propose"})) == "propose"  # without a limit, as before
    for bad in (
        {"limit": 3, "in_flight": 3},  # no room
        {"limit": 0, "in_flight": 0, "room": 0},  # a limit of at least 1
        {"limit": 3, "in_flight": 5, "room": -2},  # the room never below 0
        {"limit": 3, "in_flight": 1, "room": 1},  # the room is N - K
        {"limit": True, "in_flight": 0, "room": 1},
        "3",
    ):
        with pytest.raises(ws.Refused, match="not its autonomy line"):
            ws.intake_level(output({"autonomy": "propose", "outcomes": bad}))
    with pytest.raises(ws.Refused, match="not its autonomy line"):
        ws.intake_level(output({"autonomy": "propose", "outcomes": OUTCOMES, "other": 1}))


def test_s101_10_a_held_request_makes_no_feedback_due_until_it_reads_new_feedback_again(ws: ModuleType) -> None:
    first = {"autonomy": "propose", "outcomes": OUTCOMES}
    held = request(7, "HELD", ago(48), note="held since 2026-11-24")
    found = ws.feedback_rows(output(first, held), "o/r", NOW)
    assert found.rows == []
    # room came back: the held request reads NEW_FEEDBACK again with its hand-off time kept
    room = {"autonomy": "propose", "outcomes": {"limit": 3, "in_flight": 2, "room": 1}}
    again = request(7, "NEW_FEEDBACK", ago(48), note="held since 2026-11-24")
    fresh = request(8, "NEW_FEEDBACK", ago(2))  # handed over less than 24 hours ago: no row yet
    found = ws.feedback_rows(output(room, again, fresh), "o/r", NOW)
    assert [(r.state, r.detail) for r in found.rows] == [("FEEDBACK_DUE", "NEW_FEEDBACK #7")]
