"""Spec 086, #1530: the watch's full report gives a chain's head idle a week or more one
report-only CHAIN_STALLED row, from the chains.py show run it already makes, and shipmill
status lists it on its own line without changing the verdict"""

import datetime as dt
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.status import Row as StatusRow
from shipmill.status import report

from .test_chains_show import GATED, proc, triage_lines, trusted_only
from .test_chains_show import Forge as ShowForge
from .test_cycle_states import load
from .test_status_picture import REPO as STATUS_REPO
from .test_status_picture import facts, lines

SCRIPTS = Path(__file__).resolve().parents[1] / "skills"
STATUS_URL = f"https://github.com/{STATUS_REPO}"


def ago(days: int) -> str:
    """A GitHub timestamp days ago, an hour past the whole day, so the read's own clock can't
    cross into the next day"""
    at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days, hours=1)  # noqa: UP017
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def row(ref: str, held: int, idle: int | None, waits: str | None, **more: Any) -> dict[str, Any]:
    """One row of chains.py show --json, with the fields the watch reads"""
    return {"ref": ref, "gate": None, "cycle": None, "held": held, "idle_days": idle, "waiting_for": waits} | more


def test_s086_8_a_head_idle_a_week_gives_one_chain_stalled_row_from_the_one_walk(
    ch: ModuleType, ws: ModuleType, forge: ShowForge
) -> None:
    # o/r#1 holds o/r#2 and, through it, o/r#3; it waits on an agent and moved 10 days ago
    forge.issue("o/r#1", updated=ago(10))
    forge.issue("o/r#2", body="Depends on #1", updated=ago(10))
    forge.issue("o/r#3", body="Depends on #2", updated=ago(10))
    # o/r#4 holds o/r#5 but moved 6 days ago: not stalled yet
    forge.issue("o/r#4", updated=ago(6))
    forge.issue("o/r#5", body="Depends on #4", updated=ago(10))
    forge.configs = {"o/r": GATED}
    triage = triage_lines((1, "NEW"), (2, "BLOCKED"), (3, "BLOCKED"), (4, "NEW"), (5, "BLOCKED"))
    rows = ws.chain_rows("o/r", triage, None, trusted_only(ch, forge), stalled=True)
    assert len(forge.ran) == 1  # the walk the watch already makes, no second one
    assert [(r.state, r.subject, r.detail) for r in rows] == [
        ("CHAIN_STALLED", "o/r#1", "holds 2 open issue(s), no event for 10 day(s), waits for agent")
    ]
    assert rows[0].fix == f"see its chain: uv run --no-project python {ws.CHAINS} show o/r#1"
    # report-only: no action, so the exit code stays, and never an agent's
    assert not rows[0].action and rows[0].json()["agent"] is False
    assert "CHAIN_STALLED" not in ws.ACTION and "CHAIN_STALLED" not in ws.AGENT


def test_s086_8_no_row_under_a_tier_or_the_sweep(ch: ModuleType, ws: ModuleType, forge: ShowForge) -> None:
    forge.issue("o/r#1", updated=ago(10))
    forge.issue("o/r#2", body="Depends on #1", updated=ago(10))
    forge.configs = {"o/r": GATED}
    # the sweep and tiers 5 and 7 read report_rows without the host's rows, which reads no stall
    assert ws.chain_rows("o/r", triage_lines((1, "NEW"), (2, "BLOCKED")), None, trusted_only(ch, forge)) == []
    assert all("CHAIN_STALLED" not in states for states in ws.TIERS.values())
    assert "CHAIN_STALLED" not in ws.SWEPT


def test_s086_8_only_a_head_idle_7_days_or_more_gives_a_row(ws: ModuleType) -> None:
    shown = {
        "rows": [
            row("o/r#1", 3, 7, "decision"),
            row("o/r#2", 1, 30, "items"),  # waits on another item first: no head
            row("o/r#3", 2, 30, "cycle"),
            row("o/r#4", 0, 30, "agent"),  # holds nothing
            row("o/r#5", 1, 6, "person"),
            row("x/b#6", 1, None, "pull request"),  # an open pull request: no idle days
            row("x/b#7", 4, None, None),  # closed
            row("x/b#8", 1, 9, "no gate"),
        ]
    }
    found = ws.chain_stalled_rows(shown)
    assert [(r.subject, r.detail) for r in found] == [
        ("o/r#1", "holds 3 open issue(s), no event for 7 day(s), waits for decision"),
        ("x/b#8", "holds 1 open issue(s), no event for 9 day(s), waits for no gate"),
    ]


@pytest.mark.parametrize(
    "bad",
    [
        {"held": "2"},
        {"held": True},
        {"held": -1},
        {"idle_days": 7.5},
        {"waiting_for": "agent; rm -rf ~"},
        {"ref": "o/r#1 or; rm -rf ~"},
    ],
)
def test_s086_8_a_malformed_field_is_chain_unreadable(ws: ModuleType, bad: dict[str, Any]) -> None:
    printed = json.dumps({"rows": [row("o/r#1", 2, 9, "agent") | bad]})
    with pytest.raises(ws.Refused, match="malformed"):
        ws.chain_stalled_rows(json.loads(printed))
    rows = ws.chain_rows("o/r", triage_lines((1, "NEW")), None, lambda cmd: proc(0, printed), stalled=True)
    assert [r.state for r in rows] == ["CHAIN_UNREADABLE"]
    assert rows[0].fix is not None and "rm -rf" not in rows[0].fix


def test_s086_8_status_lists_it_on_stalled_chains_with_the_same_verdict() -> None:
    fix = "see its chain: uv run --no-project python chains.py show o/x#3"
    stalled = StatusRow(
        "CHAIN_STALLED", "o/x#3", "holds 2 open issue(s), no event for 9 day(s), waits for agent", False, fix
    )
    for others in [(), (StatusRow("HOLD", "#3", "freeze", False, "close #3"),)]:
        assert report(facts(stalled, *others)).verdict is report(facts(*others)).verdict
    text = lines(facts(stalled))
    at = text.index(
        "  stalled chains o/x#3 https://github.com/o/x/issues/3:"
        " holds 2 open issue(s), no event for 9 day(s), waits for agent"
    )
    assert text[at + 1] == f"                 fix: {fix}"
    assert not any(line.startswith("  other") for line in text)
    assert STATUS_URL in text[0]


@pytest.fixture(scope="module")
def ch() -> ModuleType:
    return load("chains_stalled", SCRIPTS / "github-issue-triage" / "scripts" / "chains.py")


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("watch_state_stalled", SCRIPTS / "github-ship-watch" / "scripts" / "watch_state.py")


@pytest.fixture
def forge(ch: ModuleType) -> ShowForge:
    return ShowForge(ch)
