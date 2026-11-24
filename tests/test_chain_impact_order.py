"""Spec 086, #1532: the watch's tier 4 and 6 reads give each ISSUES row its impact, the gate
reads it without changing a fingerprint, its walk takes what holds the most first, and its
LAUNCH says why"""

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.autonomy import Autonomy
from shipmill.errors import ReleaseError
from shipmill.findings import Finding, fingerprint, parse_findings
from shipmill.gate import prompt, walked_decision
from shipmill.walk import Handed, Rows, Swept, Walked, cut, item_key, order, walk

from .test_chains_show import GATED, proc, trusted_only
from .test_chains_show import Forge as ShowForge
from .test_cycle_states import load

ROOT = Path(__file__).resolve().parents[1]

NOW = dt.datetime(2026, 11, 24, 12, 0, tzinfo=dt.UTC)
FIX = "/shipmill:github-issue-triage o/r"
RETRY = dt.timedelta(hours=6)


@pytest.fixture(scope="module")
def ch() -> ModuleType:
    return load("chains_impact_order", ROOT / "skills" / "github-issue-triage" / "scripts" / "chains.py")


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("watch_state_impact_order", ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py")


@pytest.fixture
def forge(ch: ModuleType) -> ShowForge:
    return ShowForge(ch)


def args(bot: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(repo="o/r", bot_login=bot)


def issues(detail: str, *impact: tuple[int, int], expedite: bool = False) -> Finding:
    return Finding("ISSUES", "o/r", detail, True, (), FIX, expedite, impact)


# -- S-086-9: the tier's rows carry impact --------------------------------------------------


def test_s086_9_tier_6_rows_carry_their_subjects_impact_most_held_first(
    ch: ModuleType, ws: ModuleType, forge: ShowForge
) -> None:
    # #1 holds #2 and, through it, #3; #2 holds #3; #4 holds #5; #6 holds nothing
    forge.issue("o/r#1")
    forge.issue("o/r#2", body="Depends on #1")
    forge.issue("o/r#3", body="Depends on #2")
    forge.issue("o/r#4")
    forge.issue("o/r#5", body="Depends on #4")
    forge.issue("o/r#6")
    forge.configs = {"o/r": GATED}
    rows = [
        ws.Row("ISSUES", "o/r", "NEW #4 #2 #1", FIX),
        ws.Row("ISSUES", "o/r", "NEEDS_PR #6", FIX),
        ws.Row("ISSUES", "docs/specs/001-x.md", "SPEC_UNSPLIT S-001 x (docs/specs/001-x.md): #1", FIX),
    ]
    starts = [f"o/r#{n}" for n in range(1, 7)]
    found = ws.tier_impact(args("app[bot]"), rows, lambda: starts, trusted_only(ch, forge))
    assert len(forge.ran) == 1 and forge.ran[0][-6:] == starts  # one walk over the open issues
    assert "--trusted-only" in forge.ran[0] and forge.ran[0][forge.ran[0].index("--bot-login") + 1] == "app[bot]"
    assert [r.json()["impact"] for r in found] == [[[1, 2], [2, 1], [4, 1]], [], []]
    # every other field prints as it did
    assert {k: v for k, v in found[0].json().items() if k != "impact"} == rows[0].json()


def test_s086_9_a_failed_walk_is_chain_unreadable_and_empty_impact_while_the_rows_print(ws: ModuleType) -> None:
    rows = [ws.Row("ISSUES", "o/r", "NEW #4 #2", FIX), ws.Row("ISSUES", "o/r", "UNBLOCKED #7", FIX)]
    failed = ws.tier_impact(args(), rows, lambda: ["o/r#2", "o/r#4", "o/r#7"], lambda cmd: proc(2, err="error: boom"))
    assert [(r.state, r.detail) for r in failed] == [
        ("ISSUES", "NEW #4 #2"),
        ("ISSUES", "UNBLOCKED #7"),
        ("CHAIN_UNREADABLE", "error: boom"),
    ]
    assert [r.json().get("impact") for r in failed] == [[], [], None]
    assert failed[2].json()["agent"] is False
    # a malformed held is a failed walk too
    bad = {"rows": [{"ref": "o/r#2", "gate": None, "cycle": None, "held": "2"}]}
    garbled = ws.tier_impact(args(), rows, lambda: ["o/r#2"], lambda cmd: proc(0, json.dumps(bad)))
    assert [r.state for r in garbled] == ["ISSUES", "ISSUES", "CHAIN_UNREADABLE"]
    assert all(r.impact == () for r in garbled[:2])


def test_s086_9_a_tier_with_no_issue_runs_no_walk(ws: ModuleType) -> None:
    def never(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("a walk ran for a tier naming no issue")

    def unread() -> list[str]:
        raise AssertionError("the open issues were read for a tier naming no issue")

    vetoed = ws.Row("VETOED", "o/r", "#3", "take up each veto (needs-decision.md): /shipmill:github-issue-triage o/r")
    assert ws.tier_impact(args(), [vetoed], unread, never) == [vetoed]
    spec = ws.Row("ISSUES", "docs/specs/001-x.md", "SPEC_UNSPLIT S-001 x (docs/specs/001-x.md)", FIX)
    assert [r.json()["impact"] for r in ws.tier_impact(args(), [spec], unread, never)] == [[]]


def test_s086_9_tier_4_reads_the_open_issues_as_its_starts(ws: ModuleType) -> None:
    asked: list[list[str]] = []

    def read(cmd: list[str]) -> str:
        asked.append(cmd)
        return json.dumps([{"number": 9}, {"number": 3}])

    assert ws.open_starts("o/r", read) == ["o/r#3", "o/r#9"]
    assert asked == [["gh", "issue", "list", "-R", "o/r", "--state", "open", "-L", "1000", "--json", "number"]]
    with pytest.raises(ws.Refused, match="1000"):
        ws.open_starts("o/r", lambda cmd: json.dumps([{"number": n} for n in range(1, 1001)]))


def test_s086_9_only_an_issues_row_has_impact(ws: ModuleType) -> None:
    with pytest.raises(ValueError, match="only an ISSUES row has impact"):
        ws.Row("VETOED", "o/r", "#3", "x", impact=())
    assert "impact" not in ws.Row("ISSUES", "o/r", "NEW #3", FIX).json()  # a read without the walk


# -- S-086-10: the finding ------------------------------------------------------------------


def test_s086_10_impact_joins_no_fingerprint_or_item_key(ws: ModuleType) -> None:
    row = ws.Row("ISSUES", "o/r", "NEW #4 #2", FIX)
    lines = [json.dumps(r.json(), sort_keys=True) for r in (row, ws.replace(row, impact=()))]
    lines.append(json.dumps(ws.replace(row, impact=((2, 5), (4, 1))).json(), sort_keys=True))
    lines.append(json.dumps(ws.replace(row, impact=((4, 7),)).json(), sort_keys=True))
    found = [f for line in lines for f in parse_findings(line)]
    assert [f.impact for f in found] == [(), (), ((2, 5), (4, 1)), ((4, 7),)]
    assert len({fingerprint([f]) for f in found}) == 1
    assert len({item_key(f) for f in found}) == 1


@pytest.mark.parametrize(
    "impact",
    [{}, [[2]], [[2, 5, 1]], [["2", 5]], [[2, 0]], [[0, 5]], [[2, -1]], [[True, 5]], [[2, 1.5]], [(2, 5), 7], "2:5"],
    ids=str,
)
def test_s086_10_a_malformed_impact_fails_the_read(impact: Any) -> None:
    line = json.dumps({"state": "ISSUES", "subject": "o/r", "detail": "NEW #2", "agent": True, "impact": impact})
    with pytest.raises(ReleaseError, match="impact must be a list of"):
        parse_findings(line)


# -- S-086-11: the walk's order -------------------------------------------------------------


def test_s086_11_a_row_holding_more_comes_first_in_tier_6() -> None:
    three = issues("NEEDS_PR #7", (7, 3))  # a later kind than NEW
    one = issues("NEW #5", (5, 1))
    none = issues("NEW #4")
    assert order([none, one, three]) == [three, one, none]


def test_s086_11_with_no_impact_the_order_is_s046_12s() -> None:
    # the kind's place, then the subject and the detail, as before spec 086
    rows = [issues("NEEDS_PR #3"), issues("UNBLOCKED #8"), issues("NEW #9"), issues("NEW #10")]
    assert [f.detail for f in order(rows)] == ["NEW #10", "NEW #9", "UNBLOCKED #8", "NEEDS_PR #3"]
    tickets = [Finding("PRS_OPEN", "o/r", "#4", True), Finding("LAND_DUE", "#10", "d", True)]
    tickets += [Finding("LAND_DUE", "#9", "d", True), Finding("INCIDENT_OPEN", "#2", "d", True)]
    assert [(f.state, f.subject) for f in order(tickets)] == [
        ("INCIDENT_OPEN", "#2"),
        ("LAND_DUE", "#9"),
        ("LAND_DUE", "#10"),
        ("PRS_OPEN", "o/r"),
    ]


def test_s086_11_an_expedite_row_still_comes_before_a_standard_row_of_higher_impact() -> None:
    fast = issues("NEEDS_PR #9", expedite=True)
    heavy = issues("NEW #8", (8, 5))
    assert order([heavy, fast]) == [fast, heavy]
    # impact orders within each group too
    faster = issues("NEEDS_PR #2", (2, 1), expedite=True)
    assert order([heavy, fast, faster]) == [faster, fast, heavy]


def test_s086_11_tiers_keep_their_order_and_tier_4_goes_by_impact() -> None:
    incident = Finding("INCIDENT_OPEN", "#1", "open 1 h", True)
    prs = Finding("PRS_OPEN", "o/r", "#2", True)
    vetoed = Finding("VETOED", "o/r", "#5", True)
    decided = issues("DECIDED #6", (6, 9))
    new = issues("NEW #7", (7, 20))
    assert order([new, decided, vetoed, prs, incident]) == [incident, prs, decided, vetoed, new]


def test_s086_11_the_walk_hands_the_heavier_row_of_tier_6_first() -> None:
    light, heavy = issues("NEW #3"), issues("UNBLOCKED #8", (8, 2))
    rows = Rows((light, heavy))
    found = walk(rows, rows.changes(None), Swept(NOW, (), None), Handed(), NOW, RETRY, True)
    assert (found.item, found.tier) == (heavy, 6)


# -- S-086-12: why it came first ------------------------------------------------------------


def launched(item: Finding) -> Walked:
    return Walked(item, 6, None, None, (1, 2, 3, 4, 5, 6), (item,), Swept(NOW, (), None))


def test_s086_12_a_launch_names_its_subject_of_highest_held_in_the_reason_and_the_prompt() -> None:
    item = issues("NEW #4 #2 #9", (2, 3), (9, 3), (4, 1))
    decision = walked_decision(launched(item), [], RETRY, Autonomy.PROPOSE)
    assert decision.reason == (
        "ISSUES NEW o/r needs an agent (tier 6), first by impact: #2 holds 3 open issue(s); read tiers 1-6"
    )
    text = prompt("/shipmill:github-issue-triage {repo}", "o/r", decision.work, NOW)
    assert "\n#2 holds 3 open issue(s) that wait on it: start with it.\n" in text
    # cut to the subjects not taken, it names the highest of those
    trimmed = cut(item, [4, 9])
    assert trimmed.impact == ((9, 3), (4, 1))
    assert "first by impact: #9 holds 3" in walked_decision(launched(trimmed), [], RETRY, Autonomy.PROPOSE).reason


def test_s086_12_a_launch_without_impact_reads_as_today() -> None:
    item = issues("NEW #4 #2")
    decision = walked_decision(launched(item), [], RETRY, Autonomy.PROPOSE)
    assert decision.reason == "ISSUES NEW o/r needs an agent (tier 6); read tiers 1-6"
    text = prompt("/shipmill:github-issue-triage {repo}", "o/r", decision.work, NOW)
    assert "holds" not in text and "start with it" not in text


def test_s086_12_the_numbers_come_from_the_parsed_digits(ws: ModuleType) -> None:
    printed = json.dumps(ws.Row("ISSUES", "o/r", "NEW #2", FIX, impact=((2, 4),)).json(), sort_keys=True)
    (item,) = parse_findings(printed)
    reason = walked_decision(launched(item), [], RETRY, Autonomy.PROPOSE).reason
    assert ", first by impact: #2 holds 4 open issue(s);" in reason
