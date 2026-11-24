"""Spec 089: what a hand's recorded end means for the walk. Only a hand whose session ended ok
turns idle (S-089-3); one whose session ended limit, auth, or error drops on the tick that
records it, whichever session gate.json names (S-089-4); an ok end that wrote nothing behaves
as before (S-089-14)"""

import datetime as dt
import json
import os

import pytest

from shipmill.agents import Mode
from shipmill.findings import Finding
from shipmill.gate import RECORD, Action, Launch, Process, save_launch, session_log, state_dir
from shipmill.gitrepo import Git
from shipmill.walk import HANDED, Changes, End, Hand, Handed, Head, Pull, Swept, item_key, walk

from .test_gate import FakeClaude, checkout
from .test_gate_headless import PID, STARTED
from .test_gate_walk import INCIDENT, NOW, ONE, REPO, Source, cfg, handed, tick

__all__ = ["checkout"]  # the fixture, imported for the tests below

SHA = "a" * 40
NEW_SESSION = str(ONE)  # the session id a headless tick here launches
HEAD = Head(SHA, "SUCCESS")
DAY = dt.timedelta(hours=24)
BEFORE = NOW - dt.timedelta(hours=25)  # a hand past retry_hours (24)
OK = {"type": "result", "subtype": "success", "is_error": False, "result": "Nothing to do on #3"}
FAILED = {"type": "result", "subtype": "error_during_execution", "is_error": True}
REFUSED = {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 401}
# the events a session a usage limit stopped writes, as cf076ed3's and b65d4d03's logs hold them
INIT = {"type": "system", "subtype": "init"}
REJECTED = {
    "type": "rate_limit_event",
    "rate_limit_info": {"status": "rejected", "resetsAt": 1795608000, "rateLimitType": "seven_day"},
}
REFUSED_429 = {"type": "assistant", "api_error_status": 429}
LIMITED = {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 429, "num_turns": 1}
ENDS = {End.OK: (INIT, OK), End.LIMIT: (INIT, REJECTED, REFUSED_429, LIMITED), End.AUTH: (INIT, REFUSED)}
ENDS[End.ERROR] = (INIT, FAILED)


def logged(git: Git, session: str, *events: object, at: dt.datetime = BEFORE) -> None:
    log = session_log(state_dir(git), session)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    os.utime(log, (at.timestamp() + 60, at.timestamp() + 60))


def launched(git: Git, session: str, at: dt.datetime, fingerprint: str = "f") -> None:
    """gate.json naming this headless session, launched at at; the tick's start time reads none, so
    its process is gone"""
    save_launch(state_dir(git) / RECORD, Launch(fingerprint, session, at, Process(PID, STARTED)))


def prs(*numbers: int) -> Finding:
    return Finding(
        "PRS_OPEN", REPO, " ".join(f"#{n}" for n in numbers), False, tuple((n, SHA) for n in numbers), "land"
    )


def unchanged(*numbers: int, at: dt.datetime = BEFORE) -> dict[int, Pull]:
    """Open pull requests nobody wrote on since a hand at at, their head the hand's"""
    return {n: Pull(HEAD, at - dt.timedelta(hours=1)) for n in numbers}


# -- S-089-3: only an ok end turns idle


@pytest.mark.parametrize("end", [End.LIMIT, End.AUTH, End.ERROR])
def test_s089_3_a_walk_never_marks_idle_a_hand_whose_session_didnt_end_ok(end: End) -> None:
    hands = Handed({"PRS_OPEN #3": Hand("s0", BEFORE, HEAD, ended=end)})
    changes = Changes("sig", (), pulls=unchanged(3))
    found = walk(Source({3: [prs(3)]}), changes, Swept(NOW, (), None), hands, NOW, DAY, True)
    assert found.item == prs(3) and not any(h.idle for h in found.handed.hands.values())
    ok = Handed({"PRS_OPEN #3": Hand("s0", BEFORE, HEAD, ended=End.OK)})
    found = walk(Source({3: [prs(3)]}), changes, Swept(NOW, (), None), ok, NOW, DAY, True)
    assert found.item is None and found.handed.hands["PRS_OPEN #3"].idle  # S-061-5, as before


@pytest.mark.parametrize("end", [End.LIMIT, End.AUTH, End.ERROR])
def test_s089_3_a_subject_whose_session_didnt_end_ok_is_handed_again_not_idle(checkout: Git, end: End) -> None:
    Handed({"PRS_OPEN #3": Hand("s0", BEFORE, HEAD)}).save(state_dir(checkout) / HANDED)
    logged(checkout, "s0", *ENDS[end])
    decision = tick(checkout, Source({3: [prs(3)]}, pulls=unchanged(3)), NOW, cfg(Mode.HEADLESS), FakeClaude())
    assert decision.action is Action.LAUNCH
    assert handed(checkout)["PRS_OPEN #3"] == {
        "session": NEW_SESSION,
        "at": NOW.isoformat(),
        "head": SHA,
        "rollup": "SUCCESS",
    }


def test_s089_3_a_subject_whose_session_ended_ok_and_didnt_change_turns_idle(checkout: Git) -> None:
    Handed({"PRS_OPEN #3": Hand("s0", BEFORE, HEAD)}).save(state_dir(checkout) / HANDED)
    logged(checkout, "s0", *ENDS[End.OK])
    claude = FakeClaude()
    decision = tick(checkout, Source({3: [prs(3)]}, pulls=unchanged(3)), NOW, cfg(Mode.HEADLESS), claude)
    assert decision.action is Action.UNCHANGED and not claude.started
    assert handed(checkout)["PRS_OPEN #3"] == {
        "session": "s0",
        "at": BEFORE.isoformat(),
        "head": SHA,
        "rollup": "SUCCESS",
        "idle": True,
        "ended": "ok",
    }


# -- S-089-4: a hand drops on the tick that records its end


CF076 = "cf076ed3-a9b8-4d0b-a502-c56e086e4282"
B65D4 = "b65d4d03-231b-4678-81d1-f684df27f37a"
LATER_SESSION = "caa7c56a-eb50-47cd-ba7c-05d8b297b22e"
FIRST_LIMIT = dt.datetime(2026, 11, 23, 7, 21, 52, 575639, tzinfo=dt.UTC)
SECOND_LIMIT = dt.datetime(2026, 11, 23, 12, 47, 10, 768839, tzinfo=dt.UTC)
LATER_LAUNCH = dt.datetime(2026, 11, 24, 16, 27, 26, 522290, tzinfo=dt.UTC)
UPGRADE = dt.datetime(2026, 11, 24, 20, 0, tzinfo=dt.UTC)
STUCK = (1431, 1432, 1434, 1440, 1471, 1498, 1500, 1502, 1504, 1505)


def stuck_hands() -> dict[str, dict[str, object]]:
    """handed.json's hands of cf076ed3 and b65d4d03 as the gate held them on 2026-11-24, written
    before spec 089: cf076ed3's marked idle, b65d4d03's not yet; and one of the later session"""
    hands: dict[str, dict[str, object]] = {}
    for n in STUCK:
        session, at = (CF076, FIRST_LIMIT) if n < 1498 else (B65D4, SECOND_LIMIT)
        hand: dict[str, object] = {"session": session, "at": at.isoformat(), "head": SHA, "rollup": "SUCCESS"}
        hands[f"PRS_OPEN #{n}"] = hand | ({"idle": True} if session == CF076 else {})
    hands["PRS_OPEN #1489"] = {
        "session": LATER_SESSION,
        "at": LATER_LAUNCH.isoformat(),
        "head": SHA,
        "rollup": "SUCCESS",
    }
    return hands


def test_s089_4_the_stuck_hands_of_cf076ed3_and_b65d4d03_drop_after_the_upgrade(checkout: Git) -> None:
    state = state_dir(checkout)
    (state / HANDED).parent.mkdir(parents=True, exist_ok=True)
    (state / HANDED).write_text(json.dumps(stuck_hands()), encoding="utf-8")
    logged(checkout, CF076, *ENDS[End.LIMIT], at=FIRST_LIMIT)
    logged(checkout, B65D4, *ENDS[End.LIMIT], at=SECOND_LIMIT)
    logged(checkout, LATER_SESSION, *ENDS[End.OK], at=LATER_LAUNCH)
    launched(checkout, LATER_SESSION, LATER_LAUNCH)  # gate.json names the later session, not the dead ones
    pulls = {n: Pull(HEAD, FIRST_LIMIT - dt.timedelta(hours=1)) for n in (*STUCK, 1489)}
    source = Source({3: [prs(*STUCK, 1489)]}, pulls=pulls)
    claude = FakeClaude()
    decision = tick(checkout, source, UPGRADE, cfg(Mode.HEADLESS), claude)
    assert decision.action is Action.LAUNCH and claude.started
    found = handed(checkout)
    for n in STUCK:  # classified limit, dropped, and handed again to the new session
        assert found[f"PRS_OPEN #{n}"] == {
            "session": NEW_SESSION,
            "at": UPGRADE.isoformat(),
            "head": SHA,
            "rollup": "SUCCESS",
        }
    # the later session ended ok and its hand is within retry_hours: it stays, its end recorded
    assert found["PRS_OPEN #1489"]["session"] == LATER_SESSION and found["PRS_OPEN #1489"]["ended"] == "ok"


def test_s089_4_a_dropped_hand_is_a_change_so_a_quiet_gate_walks(checkout: Git) -> None:
    """With nothing else changed since the cursor, the drop alone makes the tick walk, or the
    item would wait for an unrelated change"""
    source = Source({1: [INCIDENT]})
    tick(checkout, source, NOW, cfg(Mode.HEADLESS), FakeClaude())  # launches s1 and sets the cursor
    logged(checkout, NEW_SESSION, *ENDS[End.LIMIT], at=NOW)
    decision = tick(checkout, source, NOW + dt.timedelta(minutes=10), cfg(Mode.HEADLESS), FakeClaude())
    assert decision.action is not Action.QUIET and decision.walk is not None and decision.walk.change


def test_s089_4_a_capped_dead_sessions_hands_still_hold_its_item() -> None:
    """Until the backoff (S-089-11), DEAD_STREAK's hold stays: the capped dead session's own hands
    are kept past their end, never idle; every other non-ok hand drops"""
    hands = Handed(
        {
            "PRS_OPEN #3": Hand("dead", NOW, HEAD, ended=End.ERROR),
            "PRS_OPEN #4": Hand("older", NOW, HEAD, ended=End.LIMIT),
            "PRS_OPEN #5": Hand("ok", NOW, HEAD, ended=End.OK),
            "PRS_OPEN #6": Hand("running", NOW, HEAD),
        }
    )
    assert set(hands.ended_ok("dead").hands) == {"PRS_OPEN #3", "PRS_OPEN #5", "PRS_OPEN #6"}
    assert set(hands.ended_ok().hands) == {"PRS_OPEN #5", "PRS_OPEN #6"}


CAPPED = "33333333-3333-4333-8333-333333333333"
NEXT = "44444444-4444-4444-8444-444444444444"


def test_s089_4_a_capped_hold_outlives_a_later_session_on_another_item(checkout: Git) -> None:
    """The capped session's hand, its end recorded on the tick that capped it, still holds its
    item for retry_hours once gate.json names a session on another item: dropping it then would
    hand it again with a fresh run of deaths, never capped while two items take turns dying"""
    capped_at = NOW - dt.timedelta(hours=1)
    later = NOW - dt.timedelta(minutes=30)
    hands = {item_key(INCIDENT): Hand(CAPPED, capped_at, ended=End.ERROR), "PRS_OPEN #3": Hand(NEXT, later, HEAD)}
    Handed(hands).save(state_dir(checkout) / HANDED)
    logged(checkout, CAPPED, *ENDS[End.ERROR], at=capped_at)
    logged(checkout, NEXT, *ENDS[End.ERROR], at=later)
    launched(checkout, NEXT, later, "PRS_OPEN #3")
    source = Source({1: [INCIDENT], 3: [prs(3)]}, pulls=unchanged(3, at=later))
    decision = tick(checkout, source, NOW, cfg(Mode.HEADLESS), FakeClaude())
    assert decision.work == (prs(3),)  # the dead session's own item again, not the held one
    assert handed(checkout)[item_key(INCIDENT)]["session"] == CAPPED


# -- S-089-14: an ok end that wrote nothing, as before


def test_s089_14_an_ok_end_leaves_a_subject_idle_until_it_changes(checkout: Git) -> None:
    Handed({"PRS_OPEN #3": Hand("s0", BEFORE, HEAD)}).save(state_dir(checkout) / HANDED)
    logged(checkout, "s0", *ENDS[End.OK])
    decision = tick(checkout, Source({3: [prs(3)]}, pulls=unchanged(3)), NOW, cfg(Mode.HEADLESS), FakeClaude())
    assert decision.action is Action.UNCHANGED and handed(checkout)["PRS_OPEN #3"]["idle"] is True
    later = NOW + dt.timedelta(hours=1)  # a new head: the subject changed, so it is handed again
    moved = {3: Pull(Head("b" * 40, "SUCCESS"), later)}
    row = Finding("PRS_OPEN", REPO, "#3", False, ((3, "b" * 40),), "land")
    decision = tick(checkout, Source({3: [row]}, signature="next", pulls=moved), later, cfg(Mode.HEADLESS))
    assert decision.action is Action.LAUNCH


def test_s089_14_an_ok_end_holds_an_item_without_subjects_for_retry_hours(checkout: Git) -> None:
    source = Source({1: [INCIDENT]})
    tick(checkout, source, NOW, cfg(Mode.HEADLESS), FakeClaude())  # launches s1
    logged(checkout, NEW_SESSION, *ENDS[End.OK], at=NOW)
    held = tick(checkout, Source({1: [INCIDENT]}, signature="next"), NOW + dt.timedelta(hours=1), cfg(Mode.HEADLESS))
    assert held.action is Action.UNCHANGED
    again = tick(checkout, Source({1: [INCIDENT]}, signature="again"), NOW + DAY, cfg(Mode.HEADLESS))
    assert again.action is Action.LAUNCH
