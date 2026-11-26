"""`shipmill gate` starts a session for each of spec 106's PLANS actions, as for any PLANS row
(S-106-26), and `status --item` hands a goal id to the watch; without gh or the network"""

import json
from pathlib import Path
from types import ModuleType

import pytest

from shipmill.gate import Action, StateRead, decide, parse_findings, watch_command

from .test_gate import DAY, NOW, OBSERVE
from .test_status_plan_waits import BOT, INTAKE_STATE, load
from .test_watch_goal_states import spec106_lines
from .test_watch_plans import WATCH_STATE

ACTIONS = (
    "GOAL_OVERDUE",
    "PLAN_REPLACED",
    "PROJECT_START_DUE",
    "PROJECT_IDLE",
    "PROJECT_STOP_DUE",
    "GOAL_PROPOSAL_DUE",
    "NEEDS_GOAL",
)


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load(WATCH_STATE, "watch_state_gate_goal_states")


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    return load(INTAKE_STATE, "intake_state_gate_goal_states")


def test_s106_26_the_gate_starts_a_session_for_each_spec_106_action(ws: ModuleType, ist: ModuleType) -> None:
    (row,) = ws.plans_rows(spec106_lines(ist), "o/r", BOT).rows
    assert {part.split(" ")[0] for part in row.detail.split("; ")} == set(ACTIONS)
    assert set(ACTIONS) <= set(ws.PLANS_ACTION)
    # each action alone makes a PLANS row the gate launches on, whatever the land level (spec 046)
    for state in ACTIONS:
        alone = ws.Row("PLANS", "o/r", f"{state} {'G-2' if state == 'GOAL_OVERDUE' else '#5'}", row.fix)
        (finding,) = parse_findings(json.dumps(alone.json(), sort_keys=True))
        assert decide([finding], [], None, NOW, DAY, OBSERVE).action is Action.LAUNCH, state


def test_s106_25_status_hands_a_goal_id_to_the_watch(tmp_path: Path) -> None:
    cmd = watch_command("o/r", tmp_path, StateRead(), host=False, item="G-3")
    assert cmd[cmd.index("--item") + 1] == "G-3"
