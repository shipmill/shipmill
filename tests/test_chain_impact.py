"""Spec 086, #1526: chains.py show --json says, per item, how much open work waits on it
(held, held_direct, milestones), what it waits for itself (waiting_for), and for how long
nothing moved (idle_days)"""

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_chains_show import GATED, key
from .test_chains_show import Forge as ShowForge

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "github-issue-triage" / "scripts"
NOW = dt.datetime(2026, 3, 10, 12, 0, tzinfo=dt.timezone.utc)  # noqa: UP017 (as the script, 3.10)


@pytest.fixture(scope="module")
def ch() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))  # chains imports triage_state, as when run from its folder
    try:
        spec = importlib.util.spec_from_file_location("chains_impact", SCRIPTS / "chains.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


class Forge(ShowForge):
    """test_chains_show's fake forge, where an issue GitHub records waiting on another may be
    one the token can't read: named in a relation, never answered"""

    def related(self, ref: str, states: bool = True) -> dict[str, Any]:
        if key(ref) in self.items:
            return super().related(ref, states)
        repo, _, number = ref.partition("#")
        node: dict[str, Any] = {"number": int(number), "repository": {"nameWithOwner": repo}}
        return node | ({"state": "OPEN", "stateReason": None} if states else {})


@pytest.fixture
def forge(ch: ModuleType) -> Forge:
    return Forge(ch)


def shown(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str], *argv: str
) -> tuple[int, dict[str, dict[str, Any]]]:
    code: int = ch.main(["show", "--json", *argv], run=forge, contents=forge.config, standing=forge.standing, now=NOW)
    rows = json.loads(capsys.readouterr().out)["rows"]
    return code, {row["ref"]: row for row in rows}


def weight(row: dict[str, Any]) -> tuple[int, int, list[str]]:
    return row["held"], row["held_direct"], row["milestones"]


def test_s086_1_a_direct_and_a_transitive_waiter_in_another_repo_count_once_each(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    # A (o/r#2) waits on o/r#1 directly; B (p/q#3, another repo) waits on it through A
    forge.issue("o/r#1", blocking=["o/r#2"])
    forge.issue("o/r#2", blocked_by=["o/r#1"], blocking=["p/q#3"], milestone="v1")
    forge.issue("p/q#3", body="Depends on o/r#2", blocked_by=["o/r#2"], milestone="v1")
    forge.configs = {"o/r": GATED}
    code, rows = shown(ch, forge, capsys, "o/r#1")
    assert weight(rows["o/r#1"]) == (2, 1, ["o/r v1", "p/q v1"])
    assert weight(rows["o/r#2"]) == (1, 1, ["p/q v1"])
    assert weight(rows["p/q#3"]) == (0, 0, [])
    assert code == 0


def test_s086_1_a_waiter_two_paths_reach_counts_once_and_milestones_are_sorted_and_unique(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    # o/r#4 waits on o/r#1 through o/r#2 and through o/r#3, and holds on it itself too
    forge.issue("o/r#1")
    forge.issue("o/r#2", body="Depends on o/r#1", milestone="v2")
    forge.issue("o/r#3", body="Depends on o/r#1", milestone="v1")
    forge.issue("o/r#4", body="Depends on o/r#2\nDepends on o/r#3\nDepends on o/r#1", milestone="v2")
    forge.issue("a/b#5", body="Depends on o/r#3", milestone="z")
    forge.configs = {"o/r": GATED}
    _, rows = shown(ch, forge, capsys, "o/r#4", "a/b#5")
    assert weight(rows["o/r#1"]) == (4, 3, ["a/b z", "o/r v1", "o/r v2"])
    assert weight(rows["o/r#3"]) == (2, 2, ["a/b z", "o/r v2"])
    assert weight(rows["o/r#2"]) == (1, 1, ["o/r v2"])


def test_s086_1_an_items_own_cycle_counts_nothing_for_it(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    # o/r#1 -> o/r#2 -> o/r#3 -> o/r#1, and o/r#9 waits on the loop from outside it
    forge.issue("o/r#1", body="Depends on o/r#2")
    forge.issue("o/r#2", body="Depends on o/r#3")
    forge.issue("o/r#3", body="Depends on o/r#1")
    forge.issue("o/r#9", body="Depends on o/r#1")
    code, rows = shown(ch, forge, capsys, "o/r#9")
    # each member holds the other two and o/r#9, never itself; o/r#9 holds nothing
    assert [weight(rows[f"o/r#{n}"])[:2] for n in (1, 2, 3, 9)] == [(3, 2), (3, 1), (3, 1), (0, 0)]
    assert code == 1  # the cycle's exit, as before


def test_s086_2_untrusted_unreadable_and_closed_issues_add_nothing(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    def build(outsiders: bool) -> None:
        forge.items.clear()
        blocking = ["o/r#2"] + (["evil/x#9", "x/secret#4", "o/r#5"] if outsiders else [])
        forge.issue("o/r#1", blocking=blocking)
        forge.issue("o/r#2", blocked_by=["o/r#1"])
        if outsiders:
            # an outsider's issue holds on o/r#1 both ways, and on o/r#2 by a Depends on line
            forge.issue(
                "evil/x#9",
                author=("mallory", "OWNER"),
                blocked_by=["o/r#1"],
                body="Depends on o/r#1\nDepends on o/r#2",
                milestone="pwn",
            )
            forge.issue("o/r#5", state="CLOSED", reason="COMPLETED", blocked_by=["o/r#1"], milestone="old")
            # x/secret#4 GitHub records waiting on o/r#1, but the token can't read it
            # o/r#6 waits on o/r#1 only through the outsider's issue, which holds nothing here
            forge.issue("o/r#6", body="Depends on evil/x#9")

    forge.configs = {"o/r": GATED}
    build(outsiders=False)
    _, before = shown(ch, forge, capsys, "o/r#1", "--trusted-only")
    build(outsiders=True)
    _, after = shown(ch, forge, capsys, "o/r#1", "o/r#6", "--trusted-only")
    assert after["evil/x#9"]["state"] == "UNTRUSTED" and after["x/secret#4"]["state"] == "UNREADABLE"
    assert after["o/r#5"]["state"] == "CLOSED"
    for ref in ("o/r#1", "o/r#2"):
        assert weight(after[ref]) == weight(before[ref])
    assert weight(after["o/r#1"]) == (1, 1, [])
    assert weight(after["evil/x#9"]) == (1, 1, [])  # a trusted issue may wait on an outsider's
    for ref in ("x/secret#4", "o/r#5", "o/r#6"):
        assert weight(after[ref]) == (0, 0, [])


def waiting(forge: Forge) -> list[str]:
    """One issue set up for each value of waiting_for, two that apply on each but the last,
    the earlier one winning"""
    forge.issue("o/r#1", labels=["needs-decision"], body="Depends on o/r#99")
    forge.issue("o/r#2", labels=["needs-decision", "human"], body="Depends on o/r#3")
    forge.issue("o/r#3", body="Depends on o/r#2", labels=["upstream"])  # cycle: 2 -> 3 -> 2
    forge.issue("o/r#4", labels=["upstream", "postponed"], body="Depends on o/r#99")
    forge.issue("o/r#5", labels=["upstream", "postponed"])
    forge.issue("o/r#6", labels=["postponed", "human"])
    forge.issue("o/r#7", labels=["role:maintainer", "role:infra"], closers=[("OPEN", "2026-03-01T00:00:00Z")])
    forge.issue("o/r#8", labels=["role:infra"], closers=[("OPEN", "2026-03-01T00:00:00Z")])
    forge.issue("n/g#9", closers=[("OPEN", "2026-03-01T00:00:00Z")])
    forge.issue("n/g#10", closers=[("MERGED", "2026-03-01T00:00:00Z")])  # no open one: its repo's gate decides
    forge.issue("o/r#11", closers=[("CLOSED", "2026-03-01T00:00:00Z")])
    forge.issue("o/r#99")
    forge.configs = {"o/r": GATED, "n/g": None}
    return ["o/r#1", "o/r#2", "o/r#4", "o/r#5", "o/r#6", "o/r#7", "o/r#8", "n/g#9", "n/g#10", "o/r#11"]


def test_s086_3_waiting_for_reads_the_first_that_applies_in_order(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    starts = waiting(forge)
    _, rows = shown(ch, forge, capsys, *starts)
    assert {ref: rows[ref]["waiting_for"] for ref in [*starts, "o/r#3"]} == {
        "o/r#1": "decision",  # before items
        "o/r#2": "decision",  # before cycle
        "o/r#3": "cycle",  # before items and upstream
        "o/r#4": "items",  # before upstream
        "o/r#5": "upstream",  # before postponed
        "o/r#6": "postponed",  # before maintainer
        "o/r#7": "maintainer",  # role:maintainer, before person and pull request
        "o/r#8": "person",  # before pull request
        "n/g#9": "pull request",  # before no gate
        "n/g#10": "no gate",
        "o/r#11": "agent",
    }


def test_s086_3_waiting_for_of_items_that_are_no_open_issue(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.issue("o/r#1", body="Depends on #2\nDepends on #3\nDepends on #4\nDepends on x/secret#5\nDepends on e/x#6")
    forge.pull("o/r#2")
    forge.pull("o/r#3", state="MERGED")
    forge.issue("o/r#4", state="CLOSED", reason="COMPLETED")
    forge.issue("e/x#6", author=("mallory", "NONE"), labels=["needs-decision"])
    _, rows = shown(ch, forge, capsys, "o/r#1", "--trusted-only")
    assert {ref: (row["waiting_for"], row["idle_days"]) for ref, row in rows.items()} == {
        "o/r#1": ("items", 68),  # the fake's updatedAt, 2026-01-01
        "o/r#2": ("pull request", None),
        "o/r#3": (None, None),
        "o/r#4": (None, None),
        "x/secret#5": ("unreadable", None),
        "e/x#6": ("untrusted", None),
    }


def test_s086_3_idle_days_counts_from_the_newer_of_the_issue_and_its_open_closing_pull_request(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.issue("o/r#1", updated="2026-03-01T13:00:00Z")  # 8 days 23 hours: 8
    forge.issue("o/r#2", updated="2026-03-01T13:00:00Z", closers=[("OPEN", "2026-03-07T11:00:00Z")])  # 3 days 1 hour
    forge.issue(
        "o/r#3",
        updated="2026-03-09T12:00:00Z",  # newer than its pull request: 1
        closers=[("OPEN", "2026-03-02T00:00:00Z"), ("CLOSED", "2026-03-10T11:00:00Z")],  # a closed one never counts
    )
    forge.issue("o/r#4", updated="2026-03-10T12:30:00Z")  # a clock ahead of ours: 0
    forge.issue("o/r#5", updated="2026-03-10T11:59:59Z")
    forge.configs = {"o/r": GATED}
    _, rows = shown(ch, forge, capsys, "o/r#1", "o/r#2", "o/r#3", "o/r#4", "o/r#5")
    assert [rows[f"o/r#{n}"]["idle_days"] for n in range(1, 6)] == [8, 3, 1, 0, 0]


def test_s086_the_table_and_the_other_fields_are_unchanged(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.issue("o/r#1", labels=["needs-decision"], milestone="v1")
    forge.issue("o/r#2", body="Depends on o/r#1", milestone="v1")
    forge.configs = {"o/r": None}
    code, rows = shown(ch, forge, capsys, "o/r#2")
    assert set(rows["o/r#1"]) == {
        "ref", "title", "executor", "state", "holds", "waits_on", "waited_on_by", "gate", "cycle", "malformed",
        "held", "held_direct", "milestones", "waiting_for", "idle_days",
    }  # fmt: skip
    assert code == 1  # NO_GATE, as before
    table = ch.main(["show", "o/r#2"], run=forge, contents=forge.config, standing=forge.standing, now=NOW)
    assert table == 1
    assert capsys.readouterr().out.splitlines() == [
        "o/r#2  title of o/r#2  agent  BLOCKED (o/r#1)",
        "o/r#1  title of o/r#1  agent  READY  NO_GATE",
    ]
