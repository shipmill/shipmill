"""Spec 089: how a headless session ended, read from its stream-json log once its process is
gone (S-089-1), and handed.json recording it on each hand as `ended` (S-089-2)"""

import datetime as dt
import json
import os
import uuid
from pathlib import Path
from types import ModuleType

import pytest

from shipmill.agents import Mode
from shipmill.errors import ReleaseError
from shipmill.gate import RECORD, Action, Launch, Process, save_launch, session_end, session_log, state_dir
from shipmill.gitrepo import Git
from shipmill.walk import HANDED, End, Hand, Handed, Head, item_key

from .test_gate import FakeClaude, checkout
from .test_gate_headless import PID, STARTED
from .test_gate_walk import BOT_FAILED, INCIDENT, LATER, NOW, Source, cfg, handed, tick
from .test_watch_gate_idle import ws

__all__ = ["checkout", "ws"]  # the fixtures, imported for the tests below

SESSION = "22222222-2222-4222-8222-222222222222"
INIT = {"type": "system", "subtype": "init", "session_id": SESSION}
SAID = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Working on #9"}]}}
OK = {"type": "result", "subtype": "success", "is_error": False, "result": "Done"}
FAILED = {"type": "result", "subtype": "error_during_execution", "is_error": True}
# a usage limit's result reads success, with is_error true (spec 089's Problem)
LIMITED = {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 429, "result": "limit"}
REJECTED = {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": 1764000000}}
ALLOWED = {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "resetsAt": 1764000000}}
REFUSED = {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 401, "result": "401"}


def logged(state: Path, *lines: object, session: str = SESSION, seconds: int = 5) -> Path:
    """A session's log of these lines, an event as its JSON and a str as written, last written
    seconds after NOW"""
    log = session_log(state, session)
    log.parent.mkdir(parents=True, exist_ok=True)
    text = "".join((line if isinstance(line, str) else json.dumps(line)) + "\n" for line in lines)
    log.write_text(text, encoding="utf-8")
    os.utime(log, (NOW.timestamp() + seconds, NOW.timestamp() + seconds))
    return log


def launch(stopped: dt.datetime | None = None) -> Launch:
    return Launch(item_key(INCIDENT), SESSION, NOW, Process(PID, STARTED), None, None, stopped)


# -- S-089-1: the end, from the log


@pytest.mark.parametrize("seconds", [5, 3600])
def test_s089_1_a_last_result_without_error_ends_ok(tmp_path: Path, seconds: int) -> None:
    logged(tmp_path, INIT, SAID, FAILED, ALLOWED, OK, seconds=seconds)
    assert session_end(tmp_path, launch(), SESSION) is End.OK


@pytest.mark.parametrize(
    "lines",
    [
        (INIT, SAID, LIMITED),  # api_error_status 429, its result success with is_error true
        (INIT, REJECTED, SAID, OK),  # a rejected rate_limit_event, whatever the result says
        (INIT, {**SAID, "api_error_status": 429}, OK),  # on any event
        (INIT, REJECTED, REFUSED),  # a limit is read before auth
    ],
)
@pytest.mark.parametrize("seconds", [5, 3600])
def test_s089_1_a_429_or_a_rejected_rate_limit_ends_limit_however_long_it_ran(
    tmp_path: Path, lines: tuple[object, ...], seconds: int
) -> None:
    logged(tmp_path, *lines, seconds=seconds)
    assert session_end(tmp_path, launch(), SESSION) is End.LIMIT


@pytest.mark.parametrize(
    "lines",
    [
        (INIT, REFUSED),  # api_error_status 401
        (INIT, "Failed to authenticate. API Error: 401", FAILED),  # Claude Code's stderr (#822)
        (INIT, {"type": "result", "subtype": "success", "is_error": True, "result": "Invalid API key"}),
        (INIT, "Invalid API key · Please run /login", OK),  # auth is read before ok
    ],
)
def test_s089_1_a_401_or_an_auth_failure_line_ends_auth(tmp_path: Path, lines: tuple[object, ...]) -> None:
    logged(tmp_path, *lines)
    assert session_end(tmp_path, launch(), SESSION) is End.AUTH


def test_s089_1_an_auth_failure_a_tool_or_the_assistant_quotes_is_no_auth(tmp_path: Path) -> None:
    quoted = {"type": "assistant", "message": {"content": [{"type": "text", "text": "it said Invalid API key"}]}}
    logged(tmp_path, INIT, quoted, OK)
    assert session_end(tmp_path, launch(), SESSION) is End.OK


@pytest.mark.parametrize(
    "lines",
    [
        (INIT, SAID, FAILED),  # a result with is_error true
        (INIT, OK, SAID, FAILED),  # the last result counts
        (INIT, SAID),  # no result at all
        (),  # an empty log
        ("some text claude -p printed before spec 048",),  # a log not stream-json
        (INIT, SAID, '{"type": "result", "subtype": "succ'),  # a result cut off mid-write
    ],
)
@pytest.mark.parametrize("seconds", [5, 600])
def test_s089_1_any_other_session_ends_error_one_without_a_result_past_60_s_included(
    tmp_path: Path, lines: tuple[object, ...], seconds: int
) -> None:
    logged(tmp_path, *lines, seconds=seconds)
    assert session_end(tmp_path, launch(), SESSION) is End.ERROR


def test_s089_1_a_session_without_a_log_or_one_a_stalled_tick_stopped_ends_error(tmp_path: Path) -> None:
    assert session_end(tmp_path, launch(), SESSION) is End.ERROR
    logged(tmp_path, INIT, OK, seconds=900)
    assert session_end(tmp_path, launch(stopped=NOW + dt.timedelta(minutes=10)), SESSION) is End.ERROR
    # only the last launch's stop counts: another session's log is read as it is
    assert session_end(tmp_path, launch(stopped=NOW), str(uuid.UUID(int=1))) is End.ERROR
    other = Launch("f", str(uuid.UUID(int=1)), NOW, Process(PID, STARTED), None, None, NOW)
    assert session_end(tmp_path, other, SESSION) is End.OK


@pytest.mark.parametrize(
    "event",
    [
        {"type": "result", "subtype": "success", "result": "Done"},  # no is_error
        {"type": "result", "subtype": "success", "is_error": "false"},
        {"type": "result", "subtype": "success", "is_error": None},
        {"type": "result", "is_error": True, "api_error_status": "429"},
        {"type": "assistant", "api_error_status": True},
        {"type": "rate_limit_event", "rate_limit_info": "rejected"},
        {"type": "rate_limit_event", "rate_limit_info": {"resetsAt": 1764000000}},
    ],
)
def test_s089_1_a_malformed_log_fails_fast_instead_of_guessing_an_end(tmp_path: Path, event: object) -> None:
    log = logged(tmp_path, INIT, event)
    with pytest.raises(ReleaseError, match="malformed") as raised:
        session_end(tmp_path, launch(), SESSION)
    assert raised.value.fix == f"tail -n 20 {log}"


# -- S-089-2: handed.json records the end


def test_s089_2_a_hand_records_its_end_and_one_without_it_loads_as_written_before(tmp_path: Path) -> None:
    path = tmp_path / HANDED
    before = {"session": "s0", "at": NOW.isoformat()}
    path.write_text(json.dumps({item_key(INCIDENT): before}), encoding="utf-8")
    assert Handed.load(path) == Handed({item_key(INCIDENT): Hand("s0", NOW)})
    hands = {item_key(INCIDENT): Hand("s0", NOW, ended=End.LIMIT), "PRS_OPEN #3": Hand("s1", NOW, idle=True)}
    Handed(hands).save(path)
    assert json.loads(path.read_text())[item_key(INCIDENT)] == before | {"ended": "limit"}
    assert "ended" not in json.loads(path.read_text())["PRS_OPEN #3"]
    assert Handed.load(path) == Handed(hands)
    for bad in ("dead", None, 1):
        path.write_text(json.dumps({item_key(INCIDENT): before | {"ended": bad}}), encoding="utf-8")
        with pytest.raises(ReleaseError, match="malformed"):
            Handed.load(path)


def test_s089_2_the_watch_reads_a_hand_with_its_end_as_the_gate_writes_it(ws: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / HANDED
    hands = {
        "ISSUES VERIFY_DUE #842": Hand("s0", NOW, idle=True, ended=End.OK),
        "PRS_OPEN #12": Hand("s1", NOW, Head("a" * 40, None), ended=End.LIMIT),
        "ISSUES VERIFY_DUE #900": Hand("s2", NOW),
    }
    Handed(hands).save(path)
    assert [r.subject for r in ws.idle_rows(path, LATER)] == ["ISSUES VERIFY_DUE #842"]
    assert set(ws.ENDS) == {e.value for e in End}
    for bad in ("dead", None):
        path.write_text(json.dumps({"PRS_OPEN #12": {"session": "s", "at": NOW.isoformat(), "ended": bad}}))
        with pytest.raises(ws.Refused, match="ended must be one of"):
            ws.idle_rows(path, LATER)


def test_s089_2_each_hand_reads_its_sessions_end_once_and_keeps_one_it_has() -> None:
    hands = {
        "ISSUES VERIFY_DUE #1": Hand("a", NOW),
        "ISSUES VERIFY_DUE #2": Hand("a", NOW),
        "ISSUES VERIFY_DUE #3": Hand("b", NOW, ended=End.LIMIT),
    }
    read: list[str] = []

    def end(session: str) -> End:
        read.append(session)
        return End.OK

    assert Handed(hands).ending(end) == Handed(
        {
            "ISSUES VERIFY_DUE #1": Hand("a", NOW, ended=End.OK),
            "ISSUES VERIFY_DUE #2": Hand("a", NOW, ended=End.OK),
            "ISSUES VERIFY_DUE #3": Hand("b", NOW, ended=End.LIMIT),
        }
    )
    assert read == ["a"]


def ended_session(git: Git, *lines: object, seconds: int) -> None:
    """A headless launch of INCIDENT at NOW whose session is gone, its log these lines, and an
    older hand of BOT_FAILED, as written before spec 089, whose session left no log"""
    state = state_dir(git)
    save_launch(state / RECORD, launch())
    hands = {item_key(INCIDENT): Hand(SESSION, NOW), item_key(BOT_FAILED): Hand("s0", NOW - dt.timedelta(hours=1))}
    Handed(hands).save(state / HANDED)
    logged(state, *lines, seconds=seconds)


def test_s089_2_a_headless_tick_records_each_gone_sessions_end_on_its_hands(checkout: Git) -> None:
    ended_session(checkout, INIT, SAID, OK, seconds=600)
    decision = tick(checkout, Source({1: [INCIDENT], 2: [BOT_FAILED]}), LATER, cfg(Mode.HEADLESS), FakeClaude())
    found = handed(checkout)
    assert found[item_key(INCIDENT)] == {"session": SESSION, "at": NOW.isoformat(), "ended": "ok"}
    # BOT_FAILED's session left no log: it ended error, so its hand dropped (S-089-4) and the tick
    # handed it again, to a new session whose hand records no end while it runs
    assert decision.action is Action.LAUNCH and "BOT_FAILED" in decision.reason
    assert "ended" not in found[item_key(BOT_FAILED)] and found[item_key(BOT_FAILED)]["session"] != "s0"


def test_s089_2_a_session_with_no_result_past_60_s_ends_error(checkout: Git) -> None:
    ended_session(checkout, INIT, SAID, seconds=600)
    decision = tick(checkout, Source({1: [INCIDENT], 2: [BOT_FAILED]}), LATER, cfg(Mode.HEADLESS), FakeClaude())
    assert decision.action is Action.SESSION_DEAD and decision.dead is not None
    assert decision.dead.end is End.ERROR and decision.dead.seconds == 600


def test_s089_2_an_interactive_gates_hands_record_no_end(checkout: Git) -> None:
    # interactive sessions leave no log (spec 089's Out of scope): listed_dead reads them as before
    ended_session(checkout, INIT, SAID, OK, seconds=600)
    save_launch(state_dir(checkout) / RECORD, Launch(item_key(INCIDENT), SESSION, NOW, None, None))
    decision = tick(checkout, Source({1: [INCIDENT], 2: [BOT_FAILED]}), LATER, cfg(), FakeClaude())
    assert decision.action is Action.UNCHANGED
    assert all("ended" not in h for h in handed(checkout).values())
