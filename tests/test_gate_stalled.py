"""Spec 048: a headless session whose log stayed silent for [agents] stall_minutes is STALLED,
and the gate stops it with SIGTERM to its process group; `shipmill gate --json` names the
session a RUNNING or STALLED tick waits on. The clock, the process table, and the stop are
injected, so no test signals a process it didn't start"""

import datetime as dt
import json
import signal
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.app import Identity
from shipmill.autonomy import Hold
from shipmill.claude_auth import ClaudeAuth
from shipmill.claude_token import Token
from shipmill.cli import _gate_exit
from shipmill.errors import ReleaseError
from shipmill.gate import (
    DEAD_WITHIN,
    RECORD,
    Action,
    Finding,
    Launch,
    Process,
    Running,
    busy,
    ended_dead,
    fingerprint,
    gate,
    load_launch,
    save_launch,
    state_dir,
    stop_group,
    tick_record,
)
from shipmill.github_auth import GitHubAuth
from shipmill.gitrepo import Git
from shipmill.walk import CURSOR, HANDED

from .test_app import REPO
from .test_gate import ISSUES, NO_PRUNE, NOW, FakeClaude, FakeNotifier, bg
from .test_gate_headless import (
    PID,
    SESSION,
    STARTED,
    Reads,
    checkout,
    headless,
    interactive,
    log_of,
    login,
    same,
    tick,
    unasked,
    unread,
)
from .test_gate_running import INIT, SAID, stream, written

__all__ = ["checkout"]  # the fixture, imported for the tests below

ITEM = ISSUES.brief()
MINUTE = dt.timedelta(minutes=1)


@dataclass
class Stops:
    """The stop the gate is given: records each pid it was asked to signal; gone, the group
    it found no longer there"""

    gone: bool = False
    pids: list[int] = field(default_factory=list)

    def __call__(self, pid: int) -> bool:
        self.pids.append(pid)
        return not self.gone


def never(pid: int) -> bool:
    raise AssertionError("nothing should be stopped")


def reads(*answers: str | None) -> Callable[[int], str | None]:
    """A process table that answers each lookup in turn"""
    it: Iterator[str | None] = iter(answers)

    def read(pid: int) -> str | None:
        return next(it)

    return read


def launched(git: Git) -> None:
    """A real headless launch at NOW (gate.json, handed.json, cursor.json), whose log last grew a
    minute after it"""
    decision, *_ = tick(git, headless(), FakeClaude(), Reads())
    assert decision.action is Action.LAUNCH
    written(log_of(git), stream(INIT, SAID), NOW + MINUTE)


def files(git: Git) -> dict[str, bytes]:
    return {name: (state_dir(git) / name).read_bytes() for name in (HANDED, CURSOR)}


def stalled_reason(git: Git, ran: int, silent: int, then: str) -> str:
    return (
        f"session {SESSION} on {ITEM}, running {ran} min, its log silent for {silent} min; {then}; "
        f"fix: tail -n 20 {log_of(git)}"
    )


# S-048-18 is in tests/test_config.py, with the rest of [agents]


# S-048-19


def test_s048_19_a_log_silent_for_stall_minutes_makes_the_tick_stalled(checkout: Git) -> None:
    launched(checkout)
    stops = Stops()
    decision, started, _, _ = tick(checkout, headless(), FakeClaude(), unread, now=NOW + 31 * MINUTE, stop=stops)
    assert (decision.action, started) == (Action.STALLED, None)
    assert decision.reason == stalled_reason(checkout, 31, 30, "stopped it")


def test_s048_19_a_log_silent_for_less_reads_running(checkout: Git) -> None:
    launched(checkout)
    decision, *_ = tick(checkout, headless(), FakeClaude(), unread, now=NOW + 30 * MINUTE, stop=never)
    assert decision.action is Action.RUNNING
    assert decision.reason.endswith(f"log grew 29 min ago: tail -f {log_of(checkout)}")


def test_s048_19_stall_minutes_0_reads_running_however_long_the_log_is_silent(checkout: Git) -> None:
    launched(checkout)
    later = NOW + dt.timedelta(days=2)
    decision, *_ = tick(checkout, headless(stall_minutes=0), FakeClaude(), unread, now=later, stop=never)
    assert decision.action is Action.RUNNING


def test_s048_19_the_limit_is_the_configs(checkout: Git) -> None:
    launched(checkout)
    decision, *_ = tick(checkout, headless(stall_minutes=5), FakeClaude(), unread, now=NOW + 6 * MINUTE, stop=Stops())
    assert decision.action is Action.STALLED


def test_s048_19_a_launch_after_the_mode_went_interactive_is_still_stopped(checkout: Git) -> None:
    """The last launch was headless (D-17), whatever the mode is now; stall_minutes is the config's"""
    launched(checkout)
    stops = Stops()
    decision, *_ = tick(checkout, interactive(), FakeClaude(), unread, now=NOW + 40 * MINUTE, stop=stops)
    assert (decision.action, stops.pids) == (Action.STALLED, [PID])


def test_s048_19_an_interactive_session_is_never_stalled(checkout: Git) -> None:
    save_launch(state_dir(checkout) / RECORD, Launch(fingerprint([ISSUES]), "s1", NOW, None, None, ITEM))
    claude = FakeClaude([bg("s1", "busy", "working")])
    later = NOW + dt.timedelta(days=2)
    decision, *_ = tick(checkout, interactive(), claude, unread, now=later, started=unasked, stop=never)
    assert decision.action is Action.RUNNING
    assert claude.stopped == []


# S-048-20


def test_s048_20_a_stalled_tick_stops_the_process_group_and_starts_nothing(checkout: Git) -> None:
    launched(checkout)
    before = files(checkout)
    stops, claude = Stops(), FakeClaude()
    decision, started, _, _ = tick(checkout, headless(), claude, unread, now=NOW + 40 * MINUTE, stop=stops)
    assert (decision.action, started, stops.pids) == (Action.STALLED, None, [PID])
    assert (claude.started, claude.launched, claude.stopped) == ([], [], [])
    assert files(checkout) == before  # no cursor.json, and the item stays handed in handed.json
    assert load_launch(state_dir(checkout) / RECORD).stopped == NOW + 40 * MINUTE  # type: ignore[union-attr]
    assert _gate_exit(decision) == 0


def test_s048_20_a_start_time_that_changed_since_the_first_read_is_never_signalled(checkout: Git) -> None:
    launched(checkout)
    reused = reads(STARTED, "Wed Oct  7 08:00:00 2026")  # still_working's read, then the stop's
    decision, *_ = tick(checkout, headless(), FakeClaude(), unread, now=NOW + 40 * MINUTE, started=reused, stop=never)
    assert decision.action is Action.STALLED
    assert decision.reason == stalled_reason(checkout, 40, 39, "it ended before the gate stopped it")
    assert load_launch(state_dir(checkout) / RECORD).stopped is None  # type: ignore[union-attr]


def test_s048_20_a_group_already_gone_is_said_so(checkout: Git) -> None:
    launched(checkout)
    stops = Stops(gone=True)
    decision, *_ = tick(checkout, headless(), FakeClaude(), unread, now=NOW + 40 * MINUTE, stop=stops)
    assert stops.pids == [PID]
    assert decision.reason == stalled_reason(checkout, 40, 39, "it ended before the gate stopped it")


def test_s048_20_a_dry_run_stops_nothing_and_says_would_stop_it(checkout: Git) -> None:
    launched(checkout)
    record = (state_dir(checkout) / RECORD).read_bytes()
    decision, *_ = tick(checkout, headless(), FakeClaude(), unread, now=NOW + 40 * MINUTE, dry_run=True, stop=never)
    assert decision.action is Action.STALLED
    assert decision.reason == stalled_reason(checkout, 40, 39, "would stop it")
    assert (state_dir(checkout) / RECORD).read_bytes() == record


def test_s048_20_a_real_tick_given_no_stop_exits_2_rather_than_stop_nothing(checkout: Git) -> None:
    launched(checkout)
    with pytest.raises(ReleaseError, match="no way to stop it was given"):
        tick(checkout, headless(), FakeClaude(), unread, now=NOW + 40 * MINUTE)


def test_s048_20_a_later_tick_stops_it_again_and_keeps_the_first_stop(checkout: Git) -> None:
    launched(checkout)
    stops = Stops()
    tick(checkout, headless(), FakeClaude(), unread, now=NOW + 40 * MINUTE, stop=stops)
    decision, *_ = tick(checkout, headless(), FakeClaude(), unread, now=NOW + 50 * MINUTE, stop=stops)
    assert (decision.action, stops.pids) == (Action.STALLED, [PID, PID])
    assert load_launch(state_dir(checkout) / RECORD).stopped == NOW + 40 * MINUTE  # type: ignore[union-attr]


def test_s048_20_a_stopped_session_isnt_dead_and_its_item_waits_for_retry_hours(checkout: Git) -> None:
    """Its log fell silent within DEAD_WITHIN of its launch, which alone would read it dead;
    stopped, it ran, so DEAD_STREAK doesn't count it and its item isn't retried at once"""
    tick(checkout, headless(), FakeClaude(), Reads())
    written(log_of(checkout), stream(INIT, SAID), NOW + DEAD_WITHIN / 2)
    tick(checkout, headless(), FakeClaude(), unread, now=NOW + 40 * MINUTE, stop=Stops())
    last = load_launch(state_dir(checkout) / RECORD)
    assert last is not None and last.stopped is not None
    state = state_dir(checkout)
    assert ended_dead(Launch(last.fingerprint, last.session, last.at, last.process, None, last.item), state) is not None
    assert ended_dead(last, state) is None
    gone = same(None)
    claude = FakeClaude()
    decision, started, _, _ = tick(checkout, headless(), claude, Reads(), now=NOW + 45 * MINUTE, started=gone)
    assert (decision.action, started, decision.dead) == (Action.UNCHANGED, None, None)
    decision, started, _, _ = tick(
        checkout, headless(), claude, Reads(), now=NOW + 25 * dt.timedelta(hours=1), started=gone
    )
    assert (decision.action, started) == (Action.LAUNCH, str(SESSION))


def no_claude_auth(token: Token | None) -> ClaudeAuth:
    raise AssertionError("a STALLED tick runs no Claude Code preflight")


def no_github(identity: Identity | None) -> GitHubAuth:
    raise AssertionError("a STALLED tick runs no GitHub preflight")


def test_s048_20_a_stalled_tick_runs_neither_preflight_and_still_prunes(checkout: Git) -> None:
    launched(checkout)
    decision, *_ = gate(
        checkout,
        REPO,
        lambda: headless(),
        FakeClaude(),
        unread,
        NOW + 40 * MINUTE,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        login=login,
        started=same(STARTED),
        auth=no_claude_auth,
        github=no_github,
        stop=Stops(),
    )
    assert decision.action is Action.STALLED
    assert decision.prune is not None  # D-56: the prune ran after the decision


def test_s048_20_stop_group_sends_sigterm_to_the_sessions_own_group() -> None:
    """The default stop, on a process this test starts in its own session, as the gate does"""
    child = subprocess.Popen(["sleep", "60"], start_new_session=True)
    try:
        assert stop_group(child.pid) is True
        assert child.wait(timeout=10) == -signal.SIGTERM
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


# S-048-16


def test_s048_16_json_names_a_headless_running_session(checkout: Git) -> None:
    launched(checkout)
    decision, started, waiting, pruned = tick(checkout, headless(), FakeClaude(), unread, now=NOW + 12 * MINUTE)
    record = json.loads(json.dumps(tick_record(decision, started, waiting, pruned, dry_run=False)))
    assert record["running"] == {"session": str(SESSION), "item": ITEM, "minutes": 12, "log_grew": 11}


def test_s048_16_json_names_a_stalled_session(checkout: Git) -> None:
    launched(checkout)
    tick_ = tick(checkout, headless(), FakeClaude(), unread, now=NOW + 40 * MINUTE, stop=Stops())
    record = tick_record(*tick_, dry_run=False)
    assert record["action"] == "STALLED"
    assert record["running"] == {"session": str(SESSION), "item": ITEM, "minutes": 40, "log_grew": 39}


def test_s048_16_json_names_an_interactive_running_session_with_no_log(checkout: Git) -> None:
    save_launch(state_dir(checkout) / RECORD, Launch(fingerprint([ISSUES]), "s1", NOW, None, None, ITEM))
    claude = FakeClaude([bg("s1", "busy", "working")])
    tick_ = tick(checkout, interactive(), claude, unread, now=NOW + 17 * MINUTE, started=unasked)
    record = tick_record(*tick_, dry_run=False)
    assert record["running"] == {"session": "s1", "item": ITEM, "minutes": 17, "log_grew": None}


def test_s048_16_a_session_the_gate_didnt_launch_has_no_item_or_minutes() -> None:
    last = Launch(fingerprint([ISSUES]), "s1", NOW, None, None, ITEM)
    decision = busy([bg("other", "busy", "working")], last, NOW + 5 * MINUTE)
    assert decision is not None and decision.running == Running("other", None, None, None)


def test_s048_16_a_record_without_its_item_prints_item_null(tmp_path: Path) -> None:
    launch = Launch(fingerprint([ISSUES]), "s1", NOW)
    decision = busy([bg("s1", "busy", "working")], launch, NOW + 3 * MINUTE)
    assert decision is not None and decision.running == Running("s1", None, 3, None)


@pytest.mark.parametrize("rows", [[ISSUES], []], ids=["LAUNCH", "QUIET"])
def test_s048_16_json_prints_running_null_on_any_other_decision(checkout: Git, rows: list[Finding]) -> None:
    tick_ = tick(checkout, headless(), FakeClaude(), Reads(rows=list(rows)))
    record = tick_record(*tick_, dry_run=False)
    assert record["action"] in ("LAUNCH", "QUIET")
    assert record["running"] is None


def test_s048_16_a_waiting_session_prints_running_null() -> None:
    decision = busy([bg("s1", "idle", "blocked")])
    assert decision is not None and decision.action is Action.WAITING and decision.running is None


def test_a_stopped_record_survives_a_save_and_a_load(tmp_path: Path) -> None:
    launch = Launch(fingerprint([ISSUES]), str(SESSION), NOW, Process(PID, STARTED), None, ITEM, NOW + MINUTE)
    save_launch(tmp_path / RECORD, launch)
    assert load_launch(tmp_path / RECORD) == launch


def test_an_interactive_record_that_says_stopped_is_malformed(tmp_path: Path) -> None:
    record = {"fingerprint": fingerprint([ISSUES]), "session": "s1", "at": NOW.isoformat(), "stopped": NOW.isoformat()}
    (tmp_path / RECORD).write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(ReleaseError, match="is malformed"):
        load_launch(tmp_path / RECORD)
