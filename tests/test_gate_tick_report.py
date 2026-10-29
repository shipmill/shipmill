"""Spec 048 (#817): `shipmill factory`'s gate line and `shipmill status`'s factory line read the
gate's tick.json: a failing tick's cause and fix with since when, STALLED, and RUNNING's
session, unless the launchd log has a later tick's line"""

import dataclasses
import datetime as dt
import json
import subprocess
from pathlib import Path

import pytest

from shipmill.cli import _with_tick
from shipmill.factory import as_json
from shipmill.gate import ERROR, TICK, Failing, Running, TickRecord, state_dir
from shipmill.gitrepo import Git
from shipmill.status import Check, Gate, Verdict, host_checks, report
from tests.test_factory import fake_host, run_checks
from tests.test_status_picture import NOW, facts, gate, job, lines

SINCE = NOW - dt.timedelta(minutes=45)
AT = NOW - dt.timedelta(minutes=5)
AUTH_FIX = "claude auth login"
AUTH_REASON = f"Claude Code can't authenticate (not logged in): no session starts; fix: {AUTH_FIX}"
AUTH = TickRecord(AT, "CLAUDE_AUTH", AUTH_REASON, AUTH_FIX, Failing(SINCE, 3))
ERROR_REASON = "/src/web is on branch fix-1; the gate needs its default branch"
ERRORED = TickRecord(AT, ERROR, ERROR_REASON, "git -C /src/web switch main", Failing(SINCE, 2))
LOG = "tail -n 50 /u/gate.log"


def ticked(record: TickRecord | None, last: str, exit_code: str = "2", failed: bool = False) -> Gate:
    """A gate whose launchd log's last decision or failure line is last, with tick.json record"""
    return gate(job=job(last=last, last_exit=exit_code, failed=failed), tick=record)


def gate_line(found: Gate) -> Check:
    (check,) = [c for c in run_checks(fake_host(found)) if c.check == "gate"]
    return check


def test_s048_11_a_failing_tick_is_the_gate_line_with_its_fix_and_no_exit_2() -> None:
    check = gate_line(ticked(AUTH, f"CLAUDE_AUTH: {AUTH_REASON}"))
    cause = "CLAUDE_AUTH: Claude Code can't authenticate (not logged in): no session starts"
    assert check.value == f"failing since 2026-10-07T11:15+00:00 (3 ticks): {cause}, launchd every 15 min"
    assert check.fixes == (AUTH_FIX,)
    assert not check.ok
    assert "failed" not in check.value  # neither `failed: exit 2` nor the log's line again
    (entry,) = [c for c in json.loads(as_json([check]))["checks"]]
    assert entry == {"check": "gate", "ok": False, "value": check.value, "fixes": [AUTH_FIX]}


def test_s048_11_an_errored_tick_replaces_the_failed_line_and_its_exit() -> None:
    check = gate_line(ticked(ERRORED, f"shipmill: {ERROR_REASON}", failed=True))
    assert check.value == f"failing since 2026-10-07T11:15+00:00 (2 ticks): ERROR: {ERROR_REASON}, launchd every 15 min"
    assert check.fixes == ("git -C /src/web switch main",)
    assert LOG not in check.fixes


def test_s048_11_another_exit_code_is_still_its_own_problem() -> None:
    check = gate_line(ticked(AUTH, f"CLAUDE_AUTH: {AUTH_REASON}", exit_code="78: EX_CONFIG"))
    assert check.value.startswith("failing since 2026-10-07T11:15+00:00 (3 ticks): CLAUDE_AUTH: ")
    assert "failed: exit 78: EX_CONFIG" in check.value


@pytest.mark.parametrize(
    "last",
    [
        "QUIET: nothing needs an agent",  # a later tick by a shipmill that writes no tick.json
        "CLAUDE_AUTH: Claude Code can't authenticate (token expired)",  # another reason: another tick
        "shipmill: the state file is malformed",
    ],
)
def test_s048_12_a_record_older_than_the_logs_last_line_is_ignored(last: str) -> None:
    failed = last.startswith("shipmill: ")
    stale = gate_line(ticked(AUTH, last, failed=failed))
    as_today = gate_line(ticked(None, last, failed=failed))
    assert stale == as_today
    assert "failing since" not in stale.value
    assert "failed: exit 2" in stale.value
    assert LOG in stale.fixes


def test_s048_12_a_crash_after_the_record_reads_the_traceback_as_spec_009_does() -> None:
    crashed = ticked(AUTH, "KeyError: 'x'", failed=True)  # S-048-10: a crash writes no tick.json
    check = gate_line(crashed)
    assert check.value == "failed: exit 2; failed: KeyError: 'x', launchd every 15 min"
    assert check.fixes == (LOG, LOG)


WAITS = [
    (AUTH, f"CLAUDE_AUTH: {AUTH_REASON}", False),
    (
        TickRecord(
            AT,
            "GITHUB_AUTH",
            "the App 7 has no installation on acme/web; fix: shipmill app-install acme/web",
            "shipmill app-install acme/web",
            Failing(AT, 1),
        ),
        "GITHUB_AUTH: the App 7 has no installation on acme/web; fix: shipmill app-install acme/web",
        False,
    ),
    (
        TickRecord(
            AT,
            "HOOKS_FAILED",
            "the hooks' self-test failed: uv missing; fix: brew install uv",
            "brew install uv",
            Failing(AT, 1),
        ),
        "HOOKS_FAILED: the hooks' self-test failed: uv missing; fix: brew install uv",
        False,
    ),
]


@pytest.mark.parametrize(("record", "last", "failed"), WAITS)
def test_s048_13_status_shows_the_cause_first_and_waits_on_you(record: TickRecord, last: str, failed: bool) -> None:
    found = facts(gate=ticked(record, last, failed=failed))
    assert report(found).verdict is Verdict.WAITS
    (line,) = [line for line in lines(found) if line.startswith("  factory ")]
    assert record.failing is not None
    since = record.failing.since.isoformat(timespec="minutes")
    count = record.failing.count
    assert line.startswith(
        f"  factory        1 problem(s): gate failing since {since} ({count} ticks): {record.action}: "
    )
    assert f"                 fix: {record.fix}" in lines(found)


def test_s048_13_an_errored_tick_is_stuck() -> None:
    found = facts(gate=ticked(ERRORED, f"shipmill: {ERROR_REASON}", failed=True))
    assert report(found).verdict is Verdict.STUCK
    (line,) = [line for line in lines(found) if line.startswith("  factory ")]
    assert line.startswith(
        "  factory        1 problem(s): gate failing since 2026-10-07T11:15+00:00 (2 ticks): ERROR: "
    )


STALL_FIX = "tail -n 20 /repo/.git/shipmill/sessions/s1.log"
STALL_REASON = f"session s1 on NEW #774, running 80 min, its log silent for 31 min; stopped it; fix: {STALL_FIX}"
STALLED = TickRecord(AT, "STALLED", STALL_REASON, None, None, Running("s1", "NEW #774", 80, 31))


def test_s048_13_a_stalled_tick_is_stuck_with_its_fix() -> None:
    stalled = ticked(STALLED, f"STALLED: {STALL_REASON}", exit_code="0")
    check = gate_line(stalled)
    shown = "stalled: session s1 on NEW #774, running 80 min, its log silent for 31 min; stopped it"
    assert check.value == f"{shown}, launchd every 15 min"
    assert check.fixes == (STALL_FIX,)
    found = facts(gate=stalled)
    assert report(found).verdict is Verdict.STUCK
    assert f"  factory        1 problem(s): gate {shown}, launchd every 15 min; shipmill factory" in lines(found)


@pytest.mark.parametrize(
    ("running", "shown"),
    [
        (Running("s1", "PRS_OPEN #12", 20, 2), "running: PRS_OPEN #12, 25 min, log grew 7 min ago"),  # headless
        (Running("s1", "PRS_OPEN #12", 20, None), "running: PRS_OPEN #12, 25 min"),  # interactive
        (Running("s1", None, 20, 2), "running: item not recorded, 25 min, log grew 7 min ago"),
        (Running("s9", None, None, None), "running: session s9"),  # a session the gate didn't launch
    ],
)
def test_a_running_tick_names_its_session_on_the_gate_line_and_is_no_problem(running: Running, shown: str) -> None:
    record = TickRecord(
        AT, "RUNNING", "session s1 on PRS_OPEN #12, running 20 min: claude attach s1", None, None, running
    )
    check = gate_line(ticked(record, f"RUNNING: {record.reason}", exit_code="0"))
    assert check.value == f"{shown}, launchd every 15 min"
    assert check.ok and check.fixes == ()


def test_a_record_of_a_tick_that_doesnt_fail_adds_no_problem() -> None:
    quiet = TickRecord(AT, "QUIET", "nothing needs an agent", None, None)
    check = gate_line(ticked(quiet, "QUIET: nothing needs an agent", exit_code="0"))
    assert check == gate_line(ticked(None, "QUIET: nothing needs an agent", exit_code="0"))
    assert check.value == "OK, launchd every 15 min"
    held = TickRecord(AT, "HELD", "#5 holds: no session starts", None, None)
    assert "held by" in gate_line(ticked(held, "HELD: #5 holds: no session starts", exit_code="0")).value


def checkout(tmp_path: Path) -> Git:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return Git(tmp_path)


def test_a_malformed_tick_json_is_the_gate_checks_error_and_the_rest_still_run(tmp_path: Path) -> None:
    git = checkout(tmp_path)
    path = state_dir(git) / TICK
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    broken = _with_tick(gate(), git)
    assert broken.tick is None and broken.tick_error is not None and TICK in broken.tick_error
    found = run_checks(fake_host(broken))
    (check,) = [c for c in found if c.check == "gate"]
    assert check.value == f"ERROR: {broken.tick_error}"
    assert [c.ok for c in found if c.check != "gate"] == [True] * 6  # the others still run
    assert report(facts(gate=broken)).verdict is Verdict.STUCK
    assert host_checks(facts(gate=broken))[0].value == check.value


def test_the_record_is_read_beside_the_job(tmp_path: Path) -> None:
    git = checkout(tmp_path)
    assert _with_tick(gate(), git).tick is None  # before a real tick wrote one
    path = state_dir(git) / TICK
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(AUTH.record()), encoding="utf-8")
    assert _with_tick(gate(), git).tick == AUTH
    off_job = dataclasses.replace(_with_tick(gate(job=None), git), tick_error="broken")
    assert not gate_line(off_job).value.startswith("ERROR")  # no job on this Mac: the record is no one's
