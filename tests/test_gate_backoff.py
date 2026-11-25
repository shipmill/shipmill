"""Spec 089 (S-089-11): an item whose session ended `error` is handed again 15 minutes, then 1
hour, then 4 hours after each death in its run; the error end after those holds it for
retry_hours and reads SESSION_DEAD, and it never turns idle; an ok end resets the run. The run
lives on the item's hand, so it survives another item's launch in between"""

import datetime as dt
import json
import os
from pathlib import Path
from types import ModuleType

import pytest

from shipmill.agents import Mode
from shipmill.autonomy import Autonomy
from shipmill.findings import Finding
from shipmill.gate import RECORD, Action, Decision, Launch, Process, save_launch, session_log, state_dir
from shipmill.gitrepo import Git
from shipmill.walk import BACKOFF, HANDED, End, Hand, Handed, Head, Pull, item_key

from .test_gate import FakeClaude, checkout
from .test_gate_headless import PID, STARTED
from .test_gate_walk import BOT_FAILED, INCIDENT, NOW, ONE, REPO, Source, cfg, handed, tick
from .test_watch_gate_idle import ws

__all__ = ["checkout", "ws"]  # the fixtures, imported for the tests below

SESSION = str(ONE)  # every headless launch here gets this id
DAY = dt.timedelta(hours=24)
FAILED = {"type": "result", "subtype": "error_during_execution", "is_error": True}
OK = {"type": "result", "subtype": "success", "is_error": False}
KEY = item_key(INCIDENT)


def died(git: Git, at: dt.datetime, *events: object) -> None:
    """The launched session's log, last written at at: it ended then"""
    log = session_log(state_dir(git), SESSION)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("".join(json.dumps(e) + "\n" for e in (events or (FAILED,))), encoding="utf-8")
    os.utime(log, (at.timestamp(), at.timestamp()))


class Gate:
    def __init__(self, git: Git) -> None:
        self.git, self.claude, self.ticks = git, FakeClaude(), 0

    def tick(self, at: dt.datetime, source: Source | None = None) -> Decision:
        self.ticks += 1
        found = source or Source({1: [INCIDENT]}, signature=f"s{self.ticks}")
        return tick(self.git, found, at, cfg(Mode.HEADLESS), self.claude)

    @property
    def launches(self) -> int:
        return len(self.claude.started)


def test_s089_11_error_ends_back_off_15_minutes_1_hour_4_hours_then_retry_hours(checkout: Git) -> None:
    gate = Gate(checkout)
    at = NOW
    assert gate.tick(at).action is Action.LAUNCH
    for run, delay in enumerate((*BACKOFF, DAY), start=1):
        death = at + dt.timedelta(minutes=3)
        died(checkout, death)
        held = gate.tick(death + delay - dt.timedelta(minutes=1))  # a minute before the delay ends: nothing starts
        assert held.action is Action.SESSION_DEAD and gate.launches == run
        hand = handed(checkout)[KEY]
        assert (hand["errors"], hand["until"], hand["ended"]) == (run, (death + delay).isoformat(), "error")
        at = death + delay
        again = gate.tick(at)  # its delay ended: handed again, carrying the run
        assert again.action is Action.SESSION_DEAD and gate.launches == run + 1
        assert handed(checkout)[KEY] == {"session": SESSION, "at": at.isoformat(), "errors": run}
    assert (dt.timedelta(minutes=15), dt.timedelta(hours=1), dt.timedelta(hours=4)) == BACKOFF


def test_s089_11_the_hold_after_the_backoff_reads_session_dead_naming_when_it_ends(checkout: Git) -> None:
    Handed({KEY: Hand(SESSION, NOW, errors=len(BACKOFF))}).save(state_dir(checkout) / HANDED)
    gate = Gate(checkout)
    save_launch(state_dir(checkout) / RECORD, Launch(KEY, SESSION, NOW, Process(PID, STARTED)))
    death = NOW + dt.timedelta(minutes=2)
    died(checkout, death)
    decision = gate.tick(NOW + dt.timedelta(hours=5))
    assert decision.action is Action.SESSION_DEAD and gate.launches == 0
    until = (death + DAY).isoformat(timespec="minutes")
    assert f"no session starts for the same item until {until}" in decision.reason


def test_s089_11_an_error_hand_never_turns_idle(checkout: Git) -> None:
    head = Head("a" * 40, "SUCCESS")
    row = Finding("PRS_OPEN", REPO, "#3", False, ((3, "a" * 40),), "land")
    gone = NOW - dt.timedelta(hours=30)
    hands = {"PRS_OPEN #3": Hand("s0", gone, head, ended=End.ERROR, errors=4, until=gone + DAY)}
    Handed(hands).save(state_dir(checkout) / HANDED)
    source = Source({3: [row]}, pulls={3: Pull(head, gone - dt.timedelta(hours=1))})
    decision = tick(checkout, source, NOW, cfg(Mode.HEADLESS), FakeClaude())
    assert decision.action is Action.LAUNCH  # past its hold, unchanged, and still handed again, never idle
    assert handed(checkout)["PRS_OPEN #3"]["errors"] == 4


def test_s089_11_an_error_hand_past_its_hold_that_no_walk_hands_walks_once_not_every_tick(checkout: Git) -> None:
    head = Head("a" * 40, "SUCCESS")
    row = Finding("PRS_OPEN", REPO, "#3", False, ((3, "a" * 40),), "land")  # under observe: a row, no item
    gone = NOW - dt.timedelta(hours=30)
    hand = Hand("s0", gone, head, ended=End.ERROR, errors=1, until=gone + dt.timedelta(minutes=15))
    Handed({"PRS_OPEN #3": hand}).save(state_dir(checkout) / HANDED)
    source = Source({3: [row]}, pulls={3: Pull(head, gone - dt.timedelta(hours=1))}, signature="same")
    walks = []
    for minutes in (0, 10, 20):
        at = NOW + dt.timedelta(minutes=minutes)
        decision = tick(checkout, source, at, cfg(Mode.HEADLESS, land=Autonomy.OBSERVE), FakeClaude())
        walks.append(decision.walk is not None and decision.walk.change)
    assert walks == [True, False, False]  # its expiry is one change, not one per tick


def test_s089_11_an_ok_end_resets_the_run(checkout: Git) -> None:
    gate = Gate(checkout)
    gate.tick(NOW)
    died(checkout, NOW + dt.timedelta(minutes=2))
    later = NOW + dt.timedelta(minutes=20)
    gate.tick(later)  # handed again after 15 minutes
    died(checkout, later + dt.timedelta(minutes=5), OK)
    gate.tick(later + dt.timedelta(minutes=10))
    hand = handed(checkout)[KEY]
    assert hand["ended"] == "ok" and "errors" not in hand and "until" not in hand


def test_s089_11_the_run_survives_another_items_launch_in_between(checkout: Git) -> None:
    gate = Gate(checkout)
    both = Source({1: [INCIDENT], 2: [BOT_FAILED]})
    gate.tick(NOW, both)  # INCIDENT
    died(checkout, NOW + dt.timedelta(minutes=1))
    assert gate.tick(NOW + dt.timedelta(minutes=5), Source({1: [INCIDENT], 2: [BOT_FAILED]}, signature="b")).work == (
        BOT_FAILED,
    )  # INCIDENT backs off; the walk goes past it
    died(checkout, NOW + dt.timedelta(minutes=6), OK)  # BOT_FAILED's session ended ok
    decision = gate.tick(NOW + dt.timedelta(minutes=16), Source({1: [INCIDENT], 2: [BOT_FAILED]}, signature="c"))
    assert decision.work == (INCIDENT,)
    assert handed(checkout)[KEY]["errors"] == 1  # its run, not a fresh one, though gate.json named another item


def test_s089_11_the_watch_reads_a_backed_off_hand(ws: ModuleType, tmp_path: Path) -> None:
    hands = {"PRS_OPEN #3": Hand("s0", NOW, Head("a" * 40, None), ended=End.ERROR, errors=2, until=NOW + DAY)}
    Handed(hands).save(tmp_path / HANDED)
    assert ws.idle_rows(tmp_path / HANDED, NOW) == []
    for bad in (
        {"errors": 0},
        {"errors": True},
        {"until": NOW.isoformat()},
        {"ended": "ok", "errors": 1, "until": "x"},
    ):
        entry = {"session": "s0", "at": NOW.isoformat()} | bad
        (tmp_path / HANDED).write_text(json.dumps({"PRS_OPEN #3": entry}), encoding="utf-8")
        with pytest.raises(ws.Refused):
            ws.idle_rows(tmp_path / HANDED, NOW)
