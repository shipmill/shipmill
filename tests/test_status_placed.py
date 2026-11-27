"""#1824: every state watch_state.py can print has a deliberate place in the `shipmill status`
summary: PLACED (another line says it, or it is silent on purpose) or OTHER_ROWS (shown on the
"other" line on purpose, S-009-13), never both and never neither, so a new state can't slip
under "other" as an unknown reading. The states are read from watch_state.py's source, its
`Row(...)` calls, without running it"""

import ast
from pathlib import Path

import pytest

from shipmill.status import OTHER_ROWS, PLACED, Row

from .test_status_picture import facts, lines

WATCH = Path(__file__).resolve().parents[1] / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
# the Row calls whose state is neither a string nor a module constant naming one, by their
# source, each with the states it can carry, as literals or the module constants holding them
VARIABLE = {
    "item['state']": ("MILESTONE_STATES",),  # milestone_rows: `shipmill milestones --json`'s rows
    "state": ("GOAL_STATE", "PLAN_STATE", "PROJECT_STATE"),  # item_states, an --item read's rows
    "row.state": ("ISSUES",),  # asked_issues: an ISSUES row less the relayed numbers
}


def strings(node: ast.expr) -> tuple[str, ...] | None:
    """A string, or a tuple of strings, as the source writes it; None for anything else"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, ast.Tuple) and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
        return tuple(str(e.value) for e in node.elts if isinstance(e, ast.Constant))
    return None


def constants(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    """The module's top-level names bound to a string or a tuple of strings"""
    found: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = strings(node.value)
            if value is not None:
                found[node.targets[0].id] = value
    return found


def resolved(name: str, known: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """A VARIABLE entry's state: a module constant's strings, or the literal state itself"""
    return known.get(name, (name,))


def emitted() -> frozenset[str]:
    """Every state a Row(...) call in watch_state.py can print; a call whose state this can't
    read, and VARIABLE doesn't name, fails"""
    tree = ast.parse(WATCH.read_text(encoding="utf-8"))
    known = constants(tree)
    found: set[str] = set()
    variable: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Row"):
            continue
        arg = node.args[0] if node.args else next(k.value for k in node.keywords if k.arg == "state")
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            found.add(arg.value)
        elif isinstance(arg, ast.Name) and len(known.get(arg.id, ())) == 1:
            found.add(known[arg.id][0])
        else:
            source = ast.unparse(arg)
            assert source in VARIABLE, f"watch_state.py:{node.lineno} Row({source}, ...): name its states in VARIABLE"
            variable.add(source)
            found.update(s for name in VARIABLE[source] for s in resolved(name, known))
    assert variable == set(VARIABLE), f"VARIABLE names calls watch_state.py no longer has: {set(VARIABLE) - variable}"
    return frozenset(found)


def test_1824_every_watch_state_is_placed_or_left_to_other_on_purpose() -> None:
    states = emitted()
    neither = sorted(states - PLACED - OTHER_ROWS)
    assert not neither, f"place each in PLACED or name it in OTHER_ROWS with why: {neither}"
    assert not PLACED & OTHER_ROWS


def test_1824_both_lists_name_only_states_watch_state_prints() -> None:
    states = emitted()
    assert not OTHER_ROWS - states
    assert not PLACED - states


def test_1824_the_collector_reads_every_kind_of_call() -> None:
    states = emitted()
    assert {"PLANS", "BOT_OK"} <= states  # a literal
    assert {"VETOED", "BASE_RED", "DEPLOYMENTS_FORBIDDEN", "PLAN_FILED"} <= states  # a module constant
    assert {"MILESTONE_WAITING", "MILESTONE_MISSING", "GOAL_STATE", "PROJECT_STATE"} <= states  # a variable
    assert {"WORK_BRANCH_STALE", "HOLD", "GATE_IDLE", "RUNS_ACTIVE"} <= states  # a call over several lines


@pytest.mark.parametrize("state", sorted(OTHER_ROWS))
def test_1824_a_row_left_to_other_shows_there(state: str) -> None:
    text = lines(facts(Row(state, "x", "y", False, "the fix")))
    assert any(line.startswith("  other") and f"{state} x y" in line for line in text)


@pytest.mark.parametrize("state", ["AGENT_DRAFT_HELD", "PLAN_HELD", "GOAL_STATE"])
def test_1824_a_placed_row_never_shows_under_other(state: str) -> None:
    text = lines(facts(Row(state, "x", "y", False)))
    assert not any(line.startswith("  other") for line in text)
