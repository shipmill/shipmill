"""Spec 061: the gate hands an item of tier 3, 4, or 6 by its subjects, the issues and pull
requests its detail names, and a subject whose last session wrote nothing on it waits until it
changes. The fake source of test_gate_walk.py logs every read, issue updatedAt reads included"""

import datetime as dt
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from shipmill.agents import Mode
from shipmill.errors import ReleaseError
from shipmill.findings import Finding
from shipmill.gate import CUT_LINE, RECORD, TICK, Action, Deaths, Decision, state_dir
from shipmill.gitrepo import Git
from shipmill.walk import (
    CURSOR,
    HANDED,
    PAGE,
    Changes,
    Hand,
    Handed,
    Head,
    Pull,
    issue_query,
    issue_updates,
    item_key,
    subjects,
)

from .test_gate import FakeClaude, checkout
from .test_gate_walk import INCIDENT, NOW, ONE, REPO, Source, cfg, dead_launch, handed, tick

__all__ = ["checkout"]  # the fixture, imported for the tests below

VERIFY = Finding("ISSUES", REPO, "VERIFY_DUE #842 #900", True, (), "triage")
SHA = "a" * 40
PRS = Finding("PRS_OPEN", REPO, "#3", False, ((3, SHA),), "land")
DAY = dt.timedelta(hours=24)
BEFORE = NOW - dt.timedelta(hours=25)  # a hand past retry_hours (24)


def seed(git: Git, hands: Mapping[str, Hand]) -> None:
    Handed(hands).save(state_dir(git) / HANDED)


def hand(at: dt.datetime = BEFORE, session: str = "s0", head: Head | None = None, idle: bool = False) -> Hand:
    return Hand(session, at, head, idle)


# -- handing by subject


def test_s061_1_a_launch_of_tier_3_4_or_6_records_one_hand_per_subject(checkout: Git) -> None:
    tick(checkout, Source({6: [VERIFY]}))
    assert handed(checkout) == {
        "ISSUES VERIFY_DUE #842": {"session": "s1", "at": NOW.isoformat()},
        "ISSUES VERIFY_DUE #900": {"session": "s1", "at": NOW.isoformat()},
    }
    for name in (HANDED, RECORD):
        (state_dir(checkout) / name).unlink()
    pulls = {3: Pull(Head(SHA, "SUCCESS"), NOW)}
    tick(checkout, Source({3: [PRS]}, signature="next", pulls=pulls))
    assert handed(checkout) == {
        "PRS_OPEN #3": {"session": "s1", "at": NOW.isoformat(), "head": SHA, "rollup": "SUCCESS"}
    }


def test_s061_1_a_launch_of_tier_1_records_its_fingerprint_as_before(checkout: Git) -> None:
    tick(checkout, Source({1: [INCIDENT]}))
    assert handed(checkout) == {item_key(INCIDENT): {"session": "s1", "at": NOW.isoformat()}}


def test_s061_1_subjects_are_digits_the_gate_parsed() -> None:
    assert subjects(VERIFY) == (842, 900)
    assert subjects(PRS) == (3,)
    assert subjects(Finding("VETOED", REPO, "#2 #7", True)) == (2, 7)
    assert subjects(INCIDENT) is None  # tier 1: its fingerprint
    # a detail with any other word names no subjects: SPEC_UNSPLIT names a spec
    assert subjects(Finding("ISSUES", "docs/specs/001-a.md", "SPEC_UNSPLIT S-001 Fix #9 (docs)", True)) is None
    assert subjects(Finding("LAND_DUE", "#5", "Deploy: the land window is open", False)) is None


def test_s061_1_handed_json_round_trips_and_refuses_a_malformed_hand(checkout: Git) -> None:
    path = state_dir(checkout) / HANDED
    hands = {
        "PRS_OPEN #3": hand(head=Head(SHA, None), idle=True),
        "ISSUES VERIFY_DUE #842": hand(),
        item_key(INCIDENT): hand(NOW),
    }
    seed(checkout, hands)
    assert Handed.load(path) == Handed(hands)
    assert json.loads(path.read_text())["PRS_OPEN #3"] == {
        "session": "s0",
        "at": BEFORE.isoformat(),
        "head": SHA,
        "rollup": None,
        "idle": True,
    }
    for bad in (
        {"PRS_OPEN #3": {"session": "s0", "at": NOW.isoformat(), "head": SHA}},  # a head without its rollup
        {"PRS_OPEN #3": {"session": "s0", "at": NOW.isoformat(), "idle": "yes"}},
        {"0123456789abcdef": {"session": "s0", "at": NOW.isoformat(), "idle": True}},  # a fingerprint is never idle
        {"PRS_OPEN #3": {"session": "s0", "at": NOW.isoformat(), "seen": 1}},
    ):
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ReleaseError, match="malformed"):
            Handed.load(path)


def test_s061_2_an_item_is_cut_to_its_subjects_not_taken(checkout: Git) -> None:
    seed(checkout, {"ISSUES VERIFY_DUE #842": hand(NOW - dt.timedelta(hours=1))})
    claude = FakeClaude()
    decision = tick(checkout, Source({6: [VERIFY]}), claude=claude)
    cut = Finding("ISSUES", REPO, "VERIFY_DUE #900", True, (), "triage")
    assert (decision.action, decision.work, decision.subjects) == (Action.LAUNCH, (cut,), (900,))
    _, text = claude.launched[0]
    assert f"\n- ISSUES VERIFY_DUE {REPO}: #900 (tier 6)\n  fix: triage\n{CUT_LINE}\n" in text
    assert "#842" not in text
    found = handed(checkout)
    assert found["ISSUES VERIFY_DUE #900"] == {"session": "s1", "at": NOW.isoformat()}
    assert found["ISSUES VERIFY_DUE #842"]["session"] == "s0"  # its own hand, untouched


def test_s061_2_an_item_with_no_subject_taken_is_handed_whole_and_named_as_before(checkout: Git) -> None:
    claude = FakeClaude()
    decision = tick(checkout, Source({6: [VERIFY]}), claude=claude)
    assert (decision.work, decision.subjects) == ((VERIFY,), ())
    _, text = claude.launched[0]
    assert f"\n- ISSUES VERIFY_DUE {REPO} (tier 6)\n" in text and CUT_LINE not in text


def test_s061_3_an_item_whose_every_subject_is_taken_is_no_item(checkout: Git) -> None:
    within = NOW - dt.timedelta(hours=1)
    seed(checkout, {"ISSUES VERIFY_DUE #842": hand(within), "ISSUES VERIFY_DUE #900": hand(within, "s9")})
    decision = tick(checkout, Source({6: [VERIFY]}))
    again = (within + DAY).isoformat(timespec="minutes")
    assert (decision.action, decision.work) == (Action.UNCHANGED, (VERIFY,))
    first = f"ISSUES VERIFY_DUE {REPO} (tier 6)"
    assert decision.reason.startswith(
        f"every item was handed; the first, {first}, went to session s0; retried after {again};"
    )


# -- a subject is taken


def idle_tick(checkout: Git, claude: FakeClaude) -> Decision:
    """A tick whose only item's subject, #842, is unchanged since its hand past retry_hours"""
    seed(checkout, {"ISSUES VERIFY_DUE #842": hand()})
    source = Source({6: [Finding("ISSUES", REPO, "VERIFY_DUE #842", True, (), "triage")]})
    source.issued = {842: BEFORE - dt.timedelta(minutes=6)}
    return tick(checkout, source, claude=claude, agents=cfg(sweep_hours=48))


def test_s061_4_an_issue_unchanged_since_its_hand_is_idle(checkout: Git) -> None:
    claude = FakeClaude()
    decision = idle_tick(checkout, claude)
    assert decision.action is Action.UNCHANGED and not claude.launched
    assert handed(checkout) == {"ISSUES VERIFY_DUE #842": {"session": "s0", "at": BEFORE.isoformat(), "idle": True}}


def test_s061_10_an_unchanged_tick_whose_first_subject_is_idle_says_it_waits_for_a_change(checkout: Git) -> None:
    decision = idle_tick(checkout, FakeClaude())
    assert decision.action is Action.UNCHANGED
    assert decision.reason.startswith(
        "every item was handed; the first, ISSUES VERIFY_DUE #842, went to session s0, which wrote nothing on it;"
        " it waits for a change; read tiers"
    )


@pytest.mark.parametrize(
    "updated",
    [BEFORE - dt.timedelta(minutes=5), BEFORE + dt.timedelta(hours=1)],
    ids=["at the hand less 5 minutes", "after the hand"],
)
def test_s061_6_an_issue_updated_since_its_hand_is_handed_again(checkout: Git, updated: dt.datetime) -> None:
    seed(checkout, {"ISSUES VERIFY_DUE #842": hand()})
    source = Source({6: [Finding("ISSUES", REPO, "VERIFY_DUE #842", True, (), "triage")]}, issued={842: updated})
    decision = tick(checkout, source)
    assert decision.action is Action.LAUNCH
    assert handed(checkout) == {"ISSUES VERIFY_DUE #842": {"session": "s1", "at": NOW.isoformat()}}


def test_s061_6_an_issue_whose_updated_at_github_doesnt_give_reads_changed(checkout: Git) -> None:
    seed(checkout, {"ISSUES VERIFY_DUE #842": hand()})
    source = Source({6: [Finding("ISSUES", REPO, "VERIFY_DUE #842", True, (), "triage")]})
    assert tick(checkout, source).action is Action.LAUNCH


def test_s061_5_a_pull_request_unchanged_since_its_hand_is_idle(checkout: Git) -> None:
    head = Head(SHA, "SUCCESS")
    seed(checkout, {"PRS_OPEN #3": hand(head=head)})
    source = Source({3: [PRS]}, pulls={3: Pull(head, BEFORE - dt.timedelta(hours=1))})
    decision = tick(checkout, source)
    assert (
        decision.action is Action.UNCHANGED
        and "PRS_OPEN #3, went to session s0, which wrote nothing" in decision.reason
    )
    assert not any(r.startswith("issues") for r in source.reads)  # its updatedAt is the change check's
    assert handed(checkout)["PRS_OPEN #3"]["idle"] is True


@pytest.mark.parametrize(
    "now",
    [
        Pull(Head("b" * 40, "SUCCESS"), BEFORE - dt.timedelta(hours=1)),
        Pull(Head(SHA, "FAILURE"), BEFORE - dt.timedelta(hours=1)),
        Pull(Head(SHA, "SUCCESS"), BEFORE),
    ],
    ids=["a new head", "a new rollup", "a later updatedAt"],
)
def test_s061_5_a_pull_request_that_changed_is_handed_again_and_its_hand_replaced(checkout: Git, now: Pull) -> None:
    seed(checkout, {"PRS_OPEN #3": hand(head=Head(SHA, "SUCCESS"))})
    row = Finding("PRS_OPEN", REPO, "#3", False, ((3, now.head.sha),), "land")
    decision = tick(checkout, Source({3: [row]}, pulls={3: now}))
    assert decision.action is Action.LAUNCH
    expected = {"session": "s1", "at": NOW.isoformat(), "head": now.head.sha, "rollup": now.head.rollup}
    assert handed(checkout) == {"PRS_OPEN #3": expected}


# -- where it is read


def test_s061_7_a_walk_reads_issue_updated_at_once_and_none_without_a_subject_past_retry(checkout: Git) -> None:
    seed(checkout, {"ISSUES VERIFY_DUE #842": hand(), "ISSUES VERIFY_DUE #900": hand()})
    source = Source({6: [VERIFY]}, issued={842: NOW, 900: NOW})
    tick(checkout, source)
    assert [r for r in source.reads if r.startswith("issues")] == ["issues #842 #900"]
    fresh = Source({6: [VERIFY]}, signature="next")
    (state_dir(checkout) / RECORD).unlink()
    tick(checkout, fresh, NOW + dt.timedelta(minutes=15))  # every hand within retry_hours now
    assert not any(r.startswith("issues") for r in fresh.reads)


@dataclass
class GraphQL:
    queries: list[str] = field(default_factory=list)

    def __call__(self, query: str, variables: Mapping[str, str]) -> dict[str, Any]:
        self.queries.append(query)
        assert dict(variables) == {"owner": "romamo", "name": "demo"}
        numbers = [int(n) for n in re.findall(r"i(\d+): issueOrPullRequest", query)]
        # #7 is a number GitHub no longer has
        nodes = {f"i{n}": None if n == 7 else {"updatedAt": "2026-10-01T10:00:00Z"} for n in numbers}
        return {"data": {"repository": nodes}}


def test_s061_7_issue_updated_at_is_one_graphql_query_per_100() -> None:
    graphql = GraphQL()
    found = issue_updates(REPO, range(1, 151), graphql)
    assert len(graphql.queries) == 2 and graphql.queries[0].count("issueOrPullRequest") == PAGE
    assert graphql.queries[1].count("issueOrPullRequest") == 50
    assert found[1] == dt.datetime(2026, 10, 1, 10, 0, tzinfo=dt.UTC) and 7 not in found
    assert issue_updates(REPO, [], graphql) == {} and len(graphql.queries) == 2
    assert "... on Issue { updatedAt }" in issue_query([842])


# -- the gate's side of the change check


def test_s061_8_an_expired_hand_walks_once_then_its_idle_mark_is_quiet(checkout: Git) -> None:
    seed(checkout, {"ISSUES VERIFY_DUE #842": hand()})
    row = Finding("ISSUES", REPO, "VERIFY_DUE #842", True, (), "triage")
    source = Source({6: [row]}, signature="same", issued={842: BEFORE - dt.timedelta(hours=1)})
    tick(checkout, source, NOW - dt.timedelta(hours=2), agents=cfg(sweep_hours=48))  # the cursor; #842 within retry
    source.reads.clear()
    first = tick(checkout, source, agents=cfg(sweep_hours=48))  # its retry_hours ran out: a change
    assert first.walk is not None and first.walk.change and "tier 6" in source.reads
    assert first.action is Action.UNCHANGED and handed(checkout)["ISSUES VERIFY_DUE #842"]["idle"] is True
    source.reads.clear()
    later = tick(checkout, source, NOW + dt.timedelta(minutes=15), agents=cfg(sweep_hours=48))
    assert later.action is Action.QUIET and later.reason.startswith("no change since")
    assert source.reads == ["changes"]


def test_s061_8_an_idle_subject_updated_on_github_is_handed_again(checkout: Git) -> None:
    seed(checkout, {"ISSUES VERIFY_DUE #842": hand(idle=True)})
    row = Finding("ISSUES", REPO, "VERIFY_DUE #842", True, (), "triage")
    source = Source({6: [row]}, updated=(842,), issued={842: NOW - dt.timedelta(minutes=30)})
    decision = tick(checkout, source)
    assert decision.action is Action.LAUNCH
    assert handed(checkout) == {"ISSUES VERIFY_DUE #842": {"session": "s1", "at": NOW.isoformat()}}


def test_s061_8_an_idle_hand_a_launch_above_it_didnt_meet_loses_its_mark_when_it_changed(checkout: Git) -> None:
    seed(checkout, {"ISSUES VERIFY_DUE #842": hand(idle=True), "ISSUES VERIFY_DUE #900": hand(idle=True)})
    source = Source({1: [INCIDENT], 6: [VERIFY]}, updated=(842,))
    assert tick(checkout, source).work == (INCIDENT,)
    found = handed(checkout)
    assert "idle" not in found["ISSUES VERIFY_DUE #842"]  # the next walk reads it again
    assert found["ISSUES VERIFY_DUE #900"]["idle"] is True


# -- dropping a hand


def test_s061_9_an_idle_hand_drops_when_a_full_walk_no_longer_finds_its_subject(checkout: Git) -> None:
    seed(checkout, {"ISSUES VERIFY_DUE #842": hand(idle=True), "ISSUES VERIFY_DUE #900": hand(idle=True)})
    row = Finding("ISSUES", REPO, "VERIFY_DUE #900", True, (), "triage")
    source = Source({6: [row]}, issued={900: BEFORE - dt.timedelta(hours=1)})
    assert tick(checkout, source).action is Action.UNCHANGED  # #842 closed, or left VERIFY_DUE
    assert set(handed(checkout)) == {"ISSUES VERIFY_DUE #900"}


def test_s061_9_an_idle_hand_drops_when_its_session_ended_dead(checkout: Git) -> None:
    row = Finding("ISSUES", REPO, "VERIFY_DUE #842", True, (), "triage")
    dead_launch(checkout, row, None)
    seed(checkout, {"ISSUES VERIFY_DUE #842": hand(session=str(ONE), idle=True)})
    claude = FakeClaude()
    later = NOW + dt.timedelta(minutes=15)
    decision = tick(checkout, Source({6: [row]}, issued={842: BEFORE}), later, cfg(Mode.HEADLESS), claude)
    assert (decision.action, decision.work) == (Action.SESSION_DEAD, (row,)) and len(claude.started) == 1
    assert handed(checkout) == {"ISSUES VERIFY_DUE #842": {"session": str(ONE), "at": later.isoformat()}}


def test_s061_4_a_subject_whose_session_ended_dead_is_never_idle(checkout: Git) -> None:
    # review finding: after DEAD_STREAK deaths the dead session's hand stays for retry_hours (S-046-15);
    # past them, its subject, which the dead session never wrote on, is handed again, not held idle
    row = Finding("ISSUES", REPO, "VERIFY_DUE #842", True, (), "triage")
    dead_launch(checkout, row, Deaths(2, NOW - dt.timedelta(minutes=30)))
    seed(checkout, {"ISSUES VERIFY_DUE #842": hand(NOW, session=str(ONE))})
    claude = FakeClaude()
    later = NOW + dt.timedelta(hours=25)
    source = Source({6: [row]}, issued={842: NOW - dt.timedelta(hours=1)})
    decision = tick(checkout, source, later, cfg(Mode.HEADLESS, sweep_hours=48), claude)
    assert decision.work == (row,) and len(claude.started) == 1
    assert "idle" not in handed(checkout)["ISSUES VERIFY_DUE #842"]


# -- a hand-off is read again


HANDOFF = Finding("ISSUES", REPO, "HANDOFF_DUE #4 #5", True, (), "triage")


@dataclass
class Again(Source):
    """A source whose tier 6 reads HANDOFF on the walk and again's rows on the read again"""

    again: list[Finding] = field(default_factory=list)

    def tier(self, number: int, changes: Changes) -> list[Finding]:
        read = super().tier(number, changes)
        return list(self.again) if number == 6 and self.reads.count("tier 6") > 1 else read


@pytest.mark.parametrize("dry_run", [False, True])
def test_s061_12_a_hand_off_is_read_again_and_started_for_what_is_still_due(checkout: Git, dry_run: bool) -> None:
    still = Finding("ISSUES", REPO, "HANDOFF_DUE #5", True, (), "triage")
    source = Again({6: [HANDOFF]}, again=[still, Finding("ISSUES", REPO, "NEW #4", True, (), "triage")])
    claude = FakeClaude()
    decision = tick(checkout, source, claude=claude, dry_run=dry_run)
    assert source.reads.count("tier 6") == 2
    assert (decision.action, decision.work, decision.subjects) == (Action.LAUNCH, (still,), (5,))
    if dry_run:
        assert not claude.launched and not (state_dir(checkout) / HANDED).exists()
        return
    _, text = claude.launched[0]
    assert f"- ISSUES HANDOFF_DUE {REPO}: #5 (tier 6)" in text and "#4" not in text
    assert set(handed(checkout)) == {"ISSUES HANDOFF_DUE #5"}


def test_s061_13_a_hand_off_no_longer_due_starts_nothing_and_writes_no_cursor(checkout: Git) -> None:
    source = Again({6: [HANDOFF]}, again=[])
    claude = FakeClaude()
    decision = tick(checkout, source, claude=claude)
    reason = "HANDOFF_DUE #4 #5 read again: no longer due; the next tick walks again"
    assert (decision.action, decision.reason, decision.work) == (Action.QUIET, reason, ())
    assert not claude.launched
    state = state_dir(checkout)
    assert not (state / CURSOR).exists() and not (state / HANDED).exists() and not (state / RECORD).exists()
    record = json.loads((state / TICK).read_text())
    assert (record["action"], record["reason"]) == ("QUIET", reason)
