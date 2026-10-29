"""Spec 048: gate.json records the launch's item, a RUNNING line names it with how long the
session ran and when its log last grew, and a headless session writes stream-json, which
ended_dead reads. The clock is injected and each log's last write set with os.utime"""

import datetime as dt
import json
import os
from pathlib import Path

import pytest

from shipmill.errors import ReleaseError
from shipmill.gate import (
    DEAD_WITHIN,
    LOG_TAIL,
    RECORD,
    Action,
    ClaudeCli,
    Launch,
    Process,
    busy,
    ended_dead,
    fingerprint,
    load_launch,
    save_launch,
    session_log,
    state_dir,
    still_working,
)
from shipmill.gitrepo import Git

from .test_gate import ISSUES, NOW, FakeClaude, bg
from .test_gate_headless import (
    PID,
    SESSION,
    STARTED,
    Reads,
    Spawned,
    checkout,
    headless,
    interactive,
    log_of,
    record_of,
    same,
    tick,
    unasked,
)

__all__ = ["checkout"]  # the fixture, imported for the tests below

Event = dict[str, object]  # one stream-json line

ITEM = ISSUES.brief()
INIT: Event = {"type": "system", "subtype": "init", "session_id": str(SESSION)}
SAID: Event = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Triaging #12"}]}}
TOOL: Event = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}}
DONE: Event = {"type": "result", "subtype": "success", "is_error": False, "result": "Done: triaged #12"}
FAILED: Event = {"type": "result", "subtype": "error_during_execution", "is_error": True}
TOOL_OUTPUT: Event = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "GH_TOKEN=ghs_x"}]}}


def headless_launch(item: str | None = ITEM, at: dt.datetime = NOW) -> Launch:
    return Launch(fingerprint([ISSUES]), str(SESSION), at, Process(PID, STARTED), None, item)


def written(log: Path, text: str, at: dt.datetime) -> Path:
    """A session's log holding text, its last write at at"""
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(text, encoding="utf-8")
    os.utime(log, (at.timestamp(), at.timestamp()))
    return log


def stream(*events: Event, after: str = "") -> str:
    return "".join(json.dumps(e) + "\n" for e in events) + after


# S-048-14


@pytest.mark.parametrize("mode", ["headless", "interactive"])
def test_s048_14_a_launch_records_its_item_beside_its_fingerprint(checkout: Git, mode: str) -> None:
    agents = headless() if mode == "headless" else interactive()
    decision, *_ = tick(checkout, agents, FakeClaude(), Reads(), started=unasked if mode == "interactive" else None)
    assert decision.action is Action.LAUNCH
    record = record_of(checkout)
    assert (record["fingerprint"], record["item"]) == (fingerprint([ISSUES]), ITEM)
    assert load_launch(state_dir(checkout) / RECORD).item == ITEM  # type: ignore[union-attr]


def test_s048_14_a_record_written_before_spec_048_reads_item_not_recorded(tmp_path: Path) -> None:
    path = tmp_path / RECORD
    old = {"fingerprint": fingerprint([ISSUES]), "session": "s1", "at": NOW.isoformat()}
    path.write_text(json.dumps(old) + "\n", encoding="utf-8")
    launch = load_launch(path)
    assert launch == Launch(fingerprint([ISSUES]), "s1", NOW)
    assert (launch.item, launch.named) == (None, "item not recorded")


def test_s048_14_the_item_survives_a_save_and_a_load(tmp_path: Path) -> None:
    save_launch(tmp_path / RECORD, headless_launch())
    assert load_launch(tmp_path / RECORD) == headless_launch()


@pytest.mark.parametrize("item", [5, "", "  ", ["NEW #12"]])
def test_s048_14_a_record_whose_item_isnt_text_exits_2(tmp_path: Path, item: object) -> None:
    path = tmp_path / RECORD
    record = {"fingerprint": fingerprint([ISSUES]), "session": "s1", "item": item, "at": NOW.isoformat()}
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(ReleaseError, match="is malformed"):
        load_launch(path)


# S-048-15


def test_s048_15_a_headless_running_line_names_its_item_run_and_log(checkout: Git) -> None:
    save_launch(state_dir(checkout) / RECORD, headless_launch())
    log = written(log_of(checkout), stream(INIT, SAID), NOW + dt.timedelta(minutes=10))
    decision, *_ = tick(checkout, headless(), FakeClaude(), Reads(), now=NOW + dt.timedelta(minutes=42))
    assert decision.action is Action.RUNNING
    assert decision.reason == (f"session {SESSION} on {ITEM}, running 42 min, log grew 32 min ago: tail -f {log}")


def test_s048_15_a_headless_record_without_its_item_says_so(tmp_path: Path) -> None:
    log = written(session_log(tmp_path, str(SESSION)), "", NOW)
    decision = still_working(headless_launch(item=None), tmp_path, same(STARTED), NOW + dt.timedelta(minutes=3))
    assert decision is not None
    assert decision.reason == (
        f"session {SESSION} on item not recorded, running 3 min, log grew 3 min ago: tail -f {log}"
    )


def test_s048_15_an_interactive_running_line_for_the_last_launch_names_its_item_and_run(checkout: Git) -> None:
    save_launch(state_dir(checkout) / RECORD, Launch(fingerprint([ISSUES]), "s1", NOW, None, None, ITEM))
    claude = FakeClaude([bg("s1", "busy", "working")])
    decision, *_ = tick(checkout, interactive(), claude, Reads(), now=NOW + dt.timedelta(minutes=17), started=unasked)
    assert decision.action is Action.RUNNING
    assert decision.reason == f"session s1 on {ITEM}, running 17 min: claude attach s1"


def test_s048_15_a_session_the_gate_didnt_launch_keeps_its_line() -> None:
    last = Launch(fingerprint([ISSUES]), "s1", NOW, None, None, ITEM)
    decision = busy([bg("other", "busy", "working")], last, NOW + dt.timedelta(minutes=5))
    assert decision is not None
    assert decision.reason == "session other is still working: claude attach other"


def test_s048_15_an_interactive_record_without_its_item_says_so() -> None:
    last = Launch(fingerprint([ISSUES]), "s1", NOW)
    decision = busy([bg("s1", "busy", "working")], last, NOW + dt.timedelta(minutes=61))
    assert decision is not None
    assert decision.reason == "session s1 on item not recorded, running 61 min: claude attach s1"


# S-048-17


def test_s048_17_a_headless_session_starts_writing_stream_json(checkout: Git) -> None:
    spawned = Spawned()
    tick(checkout, headless(), ClaudeCli([], run=spawned.runner, spawn=spawned), Reads())
    [(cmd, _, _)] = spawned.commands
    at = cmd.index("--output-format")
    assert cmd[at : at + 3] == ["--output-format", "stream-json", "--verbose"]
    assert at < cmd.index("--")


QUICK = NOW + DEAD_WITHIN / 2  # a log last written within DEAD_WITHIN of the launch


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (stream(INIT, SAID), "Triaging #12"),  # no result event: it was cut off
        (stream(INIT, SAID, FAILED), "error_during_execution"),
        (stream(INIT, SAID, {**DONE, "is_error": True}), "Done: triaged #12"),
        (stream(INIT, {**DONE, "is_error": None}), "Done: triaged #12"),  # only false is a result
        (stream(INIT, TOOL), ""),
        (stream(INIT, SAID, after="API Error: 529 Overloaded\n"), "API Error: 529 Overloaded"),
        (stream(INIT, SAID, after=json.dumps(TOOL_OUTPUT)[:-5]), "Triaging #12"),  # a cut-off event isn't shown
    ],
)
def test_s048_17_a_stream_json_log_without_a_successful_result_ended_dead(
    tmp_path: Path, text: str, shown: str
) -> None:
    written(session_log(tmp_path, str(SESSION)), text, QUICK)
    dead = ended_dead(headless_launch(), tmp_path)
    assert dead is not None and not dead.auth
    assert dead.last_line == shown


def test_s048_17_a_stream_json_log_with_a_result_is_an_attempt(tmp_path: Path) -> None:
    written(session_log(tmp_path, str(SESSION)), stream(INIT, SAID, DONE), QUICK)
    assert ended_dead(headless_launch(), tmp_path) is None


def test_s048_17_an_auth_failure_reads_the_tail_as_before(tmp_path: Path) -> None:
    expired = "Failed to authenticate: OAuth session expired"
    log = written(session_log(tmp_path, str(SESSION)), stream(INIT, after=f"{expired}\n"), NOW + dt.timedelta(hours=2))
    dead = ended_dead(headless_launch(), tmp_path)
    assert dead is not None and dead.auth and dead.log == log
    assert dead.last_line == expired


def test_s048_17_the_result_text_is_cut_as_last_line_cuts_it(tmp_path: Path) -> None:
    long = {**FAILED, "result": "first line\n" + "x" * 300}
    written(session_log(tmp_path, str(SESSION)), stream(INIT, long), QUICK)
    dead = ended_dead(headless_launch(), tmp_path)
    assert dead is not None and dead.last_line == "x" * 199 + "…"


def test_s048_17_a_long_log_reads_its_result_from_its_tail(tmp_path: Path) -> None:
    said = {**SAID, "message": {"content": [{"type": "text", "text": "y" * (LOG_TAIL // 2)}]}}
    written(session_log(tmp_path, str(SESSION)), stream(INIT, said, said, DONE), QUICK)
    assert ended_dead(headless_launch(), tmp_path) is None
    written(session_log(tmp_path, str(SESSION)), stream(INIT, said, said), QUICK)
    dead = ended_dead(headless_launch(), tmp_path)
    assert dead is not None and dead.last_line == "y" * 199 + "…"  # its last message


@pytest.mark.parametrize(
    ("text", "dead"),
    [("Nothing needed a change.\n", False), ("API Error: 529 Overloaded\n", True), ("", True)],
)
def test_s048_17_a_text_log_written_before_spec_048_reads_as_before(tmp_path: Path, text: str, dead: bool) -> None:
    written(session_log(tmp_path, str(SESSION)), text, QUICK)
    assert (ended_dead(headless_launch(), tmp_path) is not None) is dead
