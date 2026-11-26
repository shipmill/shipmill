"""intake_state.py --plans reads no trigger for a goal the direction records as met or dropped
(spec 106, S-106-3), its `state` read strictly from `product show --json`"""

from types import ModuleType

import pytest

from .test_intake_plans import Fake, due, issue, ist

__all__ = ["ist"]  # the module fixture

ENDED: list[tuple[str, str, str | None, str | None]] = [
    ("G-1", "Ship. Check: c. By: 2026-12-31. Met: 2026-12-20", "goal", "met"),
    ("G-2", "Glow. Check: g. By: 0.7.0. Dropped: 2026-12-01: no paint", "goal", "dropped"),
    ("G-3", "Track. Check: t. By: 2026-12-31", "goal", None),
]


def test_s106_3_a_met_or_dropped_goal_reads_no_trigger(ist: ModuleType) -> None:
    assert due(ist, Fake(), goals=ENDED) == {"G-3": ("PLAN_DUE", "no-work")}
    assert due(ist, Fake(), goals=ENDED, wip=2, room=0) == {"G-3": ("PLAN_WAITS", "no-work; waits for room")}
    # not even a request's
    requests = [issue(25 + i, title=f"Plan G-{i}", labels=("goal-plan",), association="OWNER") for i in (1, 2)]
    assert due(ist, Fake(requests), goals=ENDED) == {"G-3": ("PLAN_DUE", "no-work")}


def test_s106_3_the_goals_state_is_read_strictly(ist: ModuleType) -> None:
    text = '{"goals": [{"id": "G-1", "text": "Ship", "kind": "goal", "state": "met"}, {"id": "G-2", "text": "x"}]}'
    assert ist.parse_goals(text) == [ist.Goal("G-1", "Ship", "goal", "met"), ist.Goal("G-2", "x", None, None)]
    for bad in ('"done"', '"Met"', "1", "[]"):
        with pytest.raises(SystemExit):
            ist.parse_goals('{"goals": [{"id": "G-1", "text": "Ship", "kind": "goal", "state": ' + bad + "}]}")
