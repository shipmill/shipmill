"""Spec 041, #715: chains.py show marks a cycle and a malformed Depends on line; link
refuses a link that would close a cycle, before any write"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from .test_chains import COORDINATOR, Forge, link, run_link
from .test_chains_show import GATED, UNGATED, shown
from .test_chains_show import Forge as ShowForge
from .test_chains_show import show as run_show

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "github-issue-triage" / "scripts"


@pytest.fixture(scope="module")
def ch() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))  # chains imports triage_state, as when run from its folder
    try:
        spec = importlib.util.spec_from_file_location("chains_cycles", SCRIPTS / "chains.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


@pytest.fixture
def forge(ch: ModuleType) -> ShowForge:
    return ShowForge(ch)


def text(ch: ModuleType, forge: ShowForge, capsys: pytest.CaptureFixture[str], *refs: str) -> tuple[int, list[str]]:
    code = run_show(ch, forge, *refs)
    return code, capsys.readouterr().out.splitlines()


def loop_of_three(forge: ShowForge) -> None:
    """o/r#1 and o/r#2 hold each other, o/r#3 is on the longer loop through both, and o/r#4
    waits on the cycle without being on it"""
    forge.issue("o/r#1", body="Depends on #2")
    forge.issue("o/r#2", body="Depends on #1\nDepends on #3")
    forge.issue("o/r#3", body="Depends on #1")
    forge.issue("o/r#4", body="Depends on #3")
    forge.configs = {"o/r": GATED}


def test_s041_7_show_prints_cycle_with_the_shortest_loop_from_its_least_reference(
    ch: ModuleType, forge: ShowForge, capsys: pytest.CaptureFixture[str]
) -> None:
    loop_of_three(forge)
    code, lines = text(ch, forge, capsys, "o/r#4")
    assert lines == [
        "o/r#4  title of o/r#4  agent  BLOCKED (o/r#3)",  # waits on the cycle, not on it
        "o/r#3  title of o/r#3  agent  CYCLE (o/r#1 -> o/r#2 -> o/r#3 -> o/r#1)",
        "o/r#1  title of o/r#1  agent  CYCLE (o/r#1 -> o/r#2 -> o/r#1)",
        "o/r#2  title of o/r#2  agent  CYCLE (o/r#1 -> o/r#2 -> o/r#1)",
    ]
    assert code == 1  # no NO_GATE row: the cycle alone
    assert forge.read == []  # no READY row, so no config read


def test_s041_7_a_tie_goes_to_the_least_sequence_and_any_kind_of_hold_counts(
    ch: ModuleType, forge: ShowForge, capsys: pytest.CaptureFixture[str]
) -> None:
    # B/x#5 is on two loops of two: through its sub-issue B/x#3 and through B/x#2, which a
    # native relation says it is blocked by; and on one through a/y#7, the least reference
    # with case ignored
    forge.issue("B/x#5", children=["B/x#3"], blocked_by=["B/x#2"])
    forge.issue("B/x#3", body="Depends on B/x#5")
    forge.issue("B/x#2", blocked_by=["B/x#5"])
    forge.issue("a/y#7", body="Depends on B/x#5")
    forge.items[("b", "x", 5)]["body"] = "Depends on a/y#7"
    code, rows = shown(ch, forge, capsys, "B/x#5")
    cycles = {r["ref"]: r["cycle"] for r in rows}
    assert cycles["B/x#5"] == ["a/y#7", "B/x#5", "a/y#7"]  # a/y#7 sorts before B/x#2
    assert cycles["B/x#3"] == ["B/x#3", "B/x#5", "B/x#3"]
    assert cycles["B/x#2"] == ["B/x#2", "B/x#5", "B/x#2"]
    assert cycles["a/y#7"] == ["a/y#7", "B/x#5", "a/y#7"]
    assert code == 1
    # the same rows, whichever item the walk starts from
    forge.asked.clear()
    assert {r["ref"]: r["cycle"] for r in shown(ch, forge, capsys, "B/x#3")[1]} == cycles


def test_s041_7_the_loop_search_is_deterministic(ch: ModuleType) -> None:
    a, b, c, d = ("o", "r", 1), ("o", "r", 2), ("o", "r", 3), ("o", "r", 4)
    # d is on d->b->d and d->c->d (both of two) and on d->a->b->d: the least of the shortest
    graph = {d: [c, b, a], a: [b], b: [d], c: [d]}
    assert ch.shortest_loop(graph, d) == [b, d]
    assert ch.shortest_loop(graph, a) == [a, b, d]
    assert ch.shortest_loop({a: [b], b: []}, a) is None
    assert ch.shortest_loop({a: [a]}, a) == [a]


def test_s041_8_show_json_gives_the_cycle_and_null_for_every_other_row(
    ch: ModuleType, forge: ShowForge, capsys: pytest.CaptureFixture[str]
) -> None:
    loop_of_three(forge)
    forge.issue("o/r#5", state="CLOSED", reason="COMPLETED")
    forge.items[("o", "r", 4)]["body"] = "Depends on #3\nDepends on #5"
    code, rows = shown(ch, forge, capsys, "o/r#4")
    assert [(r["ref"], r["state"], r["cycle"], r["holds"]) for r in rows] == [
        ("o/r#4", "BLOCKED", None, ["o/r#3"]),
        ("o/r#3", "CYCLE", ["o/r#1", "o/r#2", "o/r#3", "o/r#1"], ["o/r#1"]),
        ("o/r#5", "CLOSED", None, []),
        ("o/r#1", "CYCLE", ["o/r#1", "o/r#2", "o/r#1"], ["o/r#2"]),
        ("o/r#2", "CYCLE", ["o/r#1", "o/r#2", "o/r#1"], ["o/r#1", "o/r#3"]),
    ]
    assert all(r["malformed"] == [] and r["gate"] is None for r in rows)
    assert code == 1


def test_s041_8_rows_off_a_cycle_keep_their_output_with_the_two_new_keys(
    ch: ModuleType, forge: ShowForge, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.issue("o/r#1", body="Depends on #2")
    forge.issue("o/r#2")
    forge.configs = {"o/r": GATED}
    code, rows = shown(ch, forge, capsys, "o/r#1")
    assert rows[0] == {
        "ref": "o/r#1",
        "title": "title of o/r#1",
        "executor": "agent",
        "state": "BLOCKED",
        "holds": ["o/r#2"],
        "waits_on": ["o/r#2"],
        "waited_on_by": [],
        "gate": None,
        "cycle": None,
        "malformed": [],
    }
    assert code == 0
    assert text(ch, forge, capsys, "o/r#1")[1] == [
        "o/r#1  title of o/r#1  agent  BLOCKED (o/r#2)",
        "o/r#2  title of o/r#2  agent  READY",
    ]


@pytest.mark.parametrize("through", ["closed", "untrusted", "unreadable"])
def test_s041_9_a_loop_through_a_closed_untrusted_or_unreadable_item_is_no_cycle(
    ch: ModuleType, forge: ShowForge, capsys: pytest.CaptureFixture[str], through: str
) -> None:
    # o/r#1 -> o/r#3 -> the item -> o/r#1, the item closed, by an outsider, or not there
    forge.issue("o/r#1", body="Depends on #3")
    if through == "closed":
        forge.issue("o/r#3", body="Depends on #2")
        forge.issue("o/r#2", state="CLOSED", reason="COMPLETED", body="Depends on #1")
    elif through == "untrusted":
        forge.issue("o/r#3", body="Depends on #2")
        forge.issue("o/r#2", author=("mallory", "NONE"), body="Depends on #1")
    else:
        forge.issue("o/r#3", body="Depends on x/gone#2")  # no such issue: nothing of it is read
    forge.configs = {"o/r": GATED}
    code, rows = shown(ch, forge, capsys, "o/r#1", "--trusted-only", "--bot-login", "app[bot]")
    assert [r["state"] for r in rows if r["state"] == "CYCLE"] == []
    assert all(r["cycle"] is None for r in rows)
    assert {r["ref"]: r["state"] for r in rows}["o/r#1"] == "BLOCKED"
    assert code == 0
    if through == "untrusted":  # read without --trusted-only, the same loop is a cycle
        code, rows = shown(ch, forge, capsys, "o/r#1")
        assert {r["ref"]: r["state"] for r in rows} == {"o/r#1": "CYCLE", "o/r#3": "CYCLE", "o/r#2": "CYCLE"}
        assert code == 1


def test_s041_10_show_ends_a_row_with_its_malformed_depends_lines_and_exits_1(
    ch: ModuleType, forge: ShowForge, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.issue("o/r#1", body="The page.\nDepends on #2 deployed; see #3\n- Depends on: the API and #2")
    forge.issue("o/r#2")
    forge.issue("o/r#3")
    forge.configs = {"o/r": GATED}
    malformed = ["line 2: Depends on #2 deployed; see #3", "line 3: - Depends on: the API and #2"]
    code, rows = shown(ch, forge, capsys, "o/r#1")
    assert [(r["ref"], r["state"], r["holds"], r["malformed"]) for r in rows] == [
        ("o/r#1", "BLOCKED", ["o/r#2", "o/r#3"], malformed),  # still holds on every reference
        ("o/r#2", "READY", [], []),
        ("o/r#3", "READY", [], []),
    ]
    assert code == 1  # no NO_GATE, no CYCLE: the malformed line alone
    code, lines = text(ch, forge, capsys, "o/r#1")
    assert lines[0] == (
        "o/r#1  title of o/r#1  agent  BLOCKED (o/r#2 o/r#3)  MALFORMED_DEPENDS "
        "line 2: Depends on #2 deployed; see #3 | line 3: - Depends on: the API and #2"
    )
    assert code == 1


def test_s041_10_malformed_depends_sits_beside_no_gate_in_the_last_column(
    ch: ModuleType, forge: ShowForge, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.issue("o/r#1", body="Depends on x/none#3")
    forge.issue("x/none#3", body="Depends on x/none#9 shipped")
    forge.issue("x/none#9", state="CLOSED", reason="COMPLETED")
    forge.configs = {"o/r": GATED, "x/none": UNGATED}
    code, lines = text(ch, forge, capsys, "o/r#1")
    assert lines[1] == (
        "x/none#3  title of x/none#3  agent  READY  NO_GATE  MALFORMED_DEPENDS line 1: Depends on x/none#9 shipped"
    )
    assert code == 1


# -- link ----------------------------------------------------------------------------------


def no_writes(forge: Forge) -> bool:
    """Not one mutation sent: no relation, no body edit"""
    return forge.writes() == [] and all("mutation" not in query for query, _ in forge.calls)


@pytest.mark.parametrize("no_text", [False, True])
def test_s041_11_link_blocked_by_refuses_a_link_that_closes_a_cycle(
    ch: ModuleType, capsys: pytest.CaptureFixture[str], no_text: bool
) -> None:
    forge = Forge(ch)
    a = forge.add("o/r#1", "Body\n")
    forge.add("o/r#2", "Depends on #3\n")  # B waits on o/r#3 ...
    c = forge.add("o/r#3")
    forge.blocked.add((c, a))  # ... which GitHub records blocked by A
    with pytest.raises(SystemExit) as exit_:
        link(ch, forge, "o/r#1", "--blocked-by", "o/r#2", *(["--no-text"] if no_text else []))
    assert exit_.value.code == 2
    err = capsys.readouterr().err
    assert err == "error: linking o/r#1 to o/r#2 closes a cycle: o/r#1 -> o/r#2 -> o/r#3 -> o/r#1\n"
    assert no_writes(forge) and forge.body("o/r#1") == "Body\n"


def test_s041_11_link_child_refuses_a_child_that_already_waits_on_its_parent(
    ch: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(ch)
    p = forge.add("o/r#5", "The feature\n")
    c = forge.add("o/r#6")
    forge.parents[p] = c  # P is C's sub-issue: C waits on P
    with pytest.raises(SystemExit) as exit_:
        link(ch, forge, "o/r#5", "--child", "o/r#6")
    assert exit_.value.code == 2
    assert "closes a cycle: o/r#5 -> o/r#6 -> o/r#5" in capsys.readouterr().err
    assert no_writes(forge)


def test_s041_11_both_halves_in_place_on_a_cycle_are_refused_too(
    ch: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(ch)
    a = forge.add("o/r#1", "Depends on #2\n")
    b = forge.add("o/r#2", "Depends on #1\n")
    forge.blocked.add((a, b))
    with pytest.raises(SystemExit) as exit_:
        link(ch, forge, "o/r#1", "--blocked-by", "o/r#2")
    assert exit_.value.code == 2
    assert "closes a cycle: o/r#1 -> o/r#2 -> o/r#1" in capsys.readouterr().err
    assert no_writes(forge)


@pytest.mark.parametrize("why", ["closed", "a closed target"])
def test_s041_11_a_closed_hold_closes_no_cycle(ch: ModuleType, capsys: pytest.CaptureFixture[str], why: str) -> None:
    forge = Forge(ch)
    a = forge.add("o/r#1", "Body\n", state="CLOSED" if why == "a closed target" else "OPEN")
    forge.add("o/r#2", "Depends on #3\n")
    c = forge.add("o/r#3", state="CLOSED" if why == "closed" else "OPEN")
    forge.blocked.add((c, a))
    assert link(ch, forge, "o/r#1", "--blocked-by", "o/r#2") == 0
    assert forge.writes() == ["addBlockedBy", "updateIssue"]
    assert "closes a cycle" not in capsys.readouterr().err


def test_s041_11_product_child_refuses_a_cycle_reading_through_the_product_token(
    ch: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(ch)
    forge.add("acme/api#3", "The report\n")
    forge.add("acme/web#7", "Depends on acme/api#3\n")
    with pytest.raises(SystemExit) as exit_:
        run_link(ch, forge, tmp_path, COORDINATOR, "acme/product", "--product", "acme/api#3", "--child", "acme/web#7")
    assert exit_.value.code == 2
    assert "closes a cycle: acme/api#3 -> acme/web#7 -> acme/api#3" in capsys.readouterr().err
    assert no_writes(forge)
