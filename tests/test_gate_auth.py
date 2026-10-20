"""#500: the gate asks whether Claude Code can authenticate before a launch, and a session that
ended dead doesn't count toward retry_hours. Never the real claude: a fake runner answers
`claude auth status --json`, and gate.json and the session logs are written by hand"""

import datetime as dt
import json
import os
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig
from shipmill.autonomy import Hold
from shipmill.claude_auth import COMMAND, ClaudeAuth, claude_auth, parse_auth
from shipmill.doctor import auth_check
from shipmill.errors import ReleaseError
from shipmill.gate import (
    AUTH,
    RECORD,
    Action,
    Deaths,
    Launch,
    Process,
    Session,
    fingerprint,
    gate,
    load_launch,
    save_launch,
    state_dir,
    tick_lines,
    tick_record,
)
from shipmill.gitrepo import Git

from .test_gate import ISSUES, NO_PRUNE, NOW, FakeClaude, FakeNotifier
from .test_gate_headless import LOGIN, PID, STARTED, Reads, checkout, headless, interactive, log_of

__all__ = ["checkout"]  # the fixture, imported for the tests below

FIRST = uuid.UUID("11111111-1111-4111-8111-111111111111")
SECOND = uuid.UUID("22222222-2222-4222-8222-222222222222")
EXPIRED = "Failed to authenticate: OAuth session expired and could not be refreshed"
LOGGED_OUT = ClaudeAuth("claude auth status says not logged in")
LOGGED_IN = ClaudeAuth(None)
SECRET = "sk-ant-oat01-not-a-real-token"


def done(code: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(COMMAND, code, stdout, stderr)


@dataclass
class FakeAuth:
    """`claude auth status --json`, answered from a list, one answer per call"""

    answers: list[ClaudeAuth]
    asked: int = 0

    def __call__(self) -> ClaudeAuth:
        self.asked += 1
        return self.answers.pop(0)


@dataclass
class Clock:
    sessions: list[uuid.UUID] = field(default_factory=lambda: [FIRST, SECOND])

    def next(self) -> uuid.UUID:
        return self.sessions.pop(0)


def gone(pid: int) -> str | None:
    """A process table where no recorded session runs any more"""
    return None


def tick(
    git: Git,
    agents: AgentsConfig,
    claude: FakeClaude,
    auth: Callable[[], ClaudeAuth] | None,
    notifier: FakeNotifier,
    now: dt.datetime = NOW,
    dry_run: bool = False,
    new_session: Callable[[], uuid.UUID] = lambda: FIRST,
    started: Callable[[int], str | None] = gone,
) -> tuple[Action, str | None, list[str]]:
    decision, launched, waiting, pruned = gate(
        git,
        "romamo/demo",
        lambda: agents,
        claude,
        Reads(),
        now,
        Hold,
        notifier,
        NO_PRUNE,
        dry_run=dry_run,
        login=lambda: LOGIN,
        started=started,
        new_session=new_session,
        auth=auth,
    )
    return decision.action, launched, tick_lines(decision, launched, waiting, pruned, dry_run)


def died(git: Git, session: uuid.UUID, at: dt.datetime, after: dt.timedelta, text: str) -> Path:
    """A session's log as `claude -p` leaves it, last written `after` its launch at `at`"""
    log = log_of(git, session)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(text, encoding="utf-8")
    moment = (at + after).timestamp()
    os.utime(log, (moment, moment))
    return log


def launched_at(git: Git, session: uuid.UUID, at: dt.datetime, deaths: Deaths | None = None) -> None:
    """gate.json as a headless launch recorded it"""
    save_launch(state_dir(git) / RECORD, Launch(fingerprint([ISSUES]), str(session), at, Process(PID, STARTED), deaths))


# the preflight's reading of `claude auth status --json`


def test_logged_in_reads_ok() -> None:
    assert parse_auth(done(0, '{"loggedIn": true, "authMethod": "claude.ai"}')).ok


def test_not_logged_in_reads_as_the_problem_whatever_the_exit_code() -> None:
    for code in (0, 1):
        assert parse_auth(done(code, '{"loggedIn": false}')) == LOGGED_OUT


def test_a_failed_command_names_its_exit_and_first_stderr_line_never_its_output() -> None:
    found = parse_auth(done(1, f'{{"token": "{SECRET}"}}', "Error: keychain locked\nmore"))
    assert found.problem == "claude auth status exited 1: Error: keychain locked"
    assert SECRET not in found.line() and SECRET not in found.reason()


@pytest.mark.parametrize("stdout", ["", "not json", "[]", '{"loggedIn": "yes"}', '{"email": "a@b"}'])
def test_an_answer_without_a_boolean_logged_in_fails(stdout: str) -> None:
    assert parse_auth(done(0, stdout)).problem == "claude auth status --json printed no loggedIn true or false"


def test_claude_missing_is_a_problem_doctor_only_warns_about() -> None:
    def missing(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(cmd[0])

    for found in (claude_auth(missing), claude_auth(missing, None)):
        assert (found.missing, auth_check(found).status) == (True, "WARN")


def test_doctor_passes_a_login_and_fails_a_lost_one_with_the_fix() -> None:
    asked: list[list[str]] = []

    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        asked.append(cmd)
        return done(0, '{"loggedIn": true}')

    assert auth_check(claude_auth(run, "/bin/claude")).status == "PASS"
    assert asked == [["/bin/claude", "auth", "status", "--json"]]
    failed = auth_check(LOGGED_OUT)
    assert (failed.status, failed.name, failed.detail) == (
        "FAIL",
        "claude auth",
        "claude auth status says not logged in: claude auth login",
    )


# point 1: the preflight


@pytest.mark.parametrize("agents", [headless(), interactive()])
def test_a_lost_login_starts_no_session_and_notifies_once_per_episode(checkout: Git, agents: AgentsConfig) -> None:
    claude, notifier = FakeClaude(), FakeNotifier()
    auth = FakeAuth([LOGGED_OUT, LOGGED_OUT, LOGGED_IN, LOGGED_OUT])
    action, launched, lines = tick(checkout, agents, claude, auth, notifier)
    assert (action, launched, claude.launched, claude.started) == (Action.CLAUDE_AUTH, None, [], [])
    assert lines[:2] == [
        "CLAUDE_AUTH: Claude Code can't authenticate on this host (claude auth status says not logged in):"
        " no session starts; fix: claude auth login",
        "  notified",
    ]
    assert not (state_dir(checkout) / RECORD).exists()  # no launch recorded: the next tick tries again
    assert notifier.sent == [
        (
            "shipmill romamo/demo",
            "Claude Code can't authenticate on this host: claude auth login; the gate starts no session until then",
        )
    ]
    action, _, lines = tick(checkout, agents, claude, auth, notifier, NOW + dt.timedelta(minutes=5))
    assert action is Action.CLAUDE_AUTH and "  notified" not in lines
    assert len(notifier.sent) == 1  # the same episode: no second notification
    action, launched, _ = tick(checkout, agents, claude, auth, notifier, NOW + dt.timedelta(minutes=10))
    assert action is Action.LAUNCH and launched is not None
    assert not (state_dir(checkout) / AUTH).exists()  # the passing preflight ended the episode
    (state_dir(checkout) / RECORD).unlink()  # new findings, not UNCHANGED
    assert tick(checkout, agents, claude, auth, notifier, NOW + dt.timedelta(hours=1))[0] is Action.CLAUDE_AUTH
    assert len(notifier.sent) == 2  # a new episode notifies again


def test_claude_missing_from_the_gate_path_starts_nothing_and_names_the_install(checkout: Git) -> None:
    # not a silent skip, and not `claude auth login`, which can't run without claude
    claude, missing = FakeClaude(), claude_auth(program=None)
    action, launched, lines = tick(checkout, headless(), claude, lambda: missing, FakeNotifier())
    assert (action, launched, claude.started) == (Action.CLAUDE_AUTH, None, [])
    assert lines[0] == (
        "CLAUDE_AUTH: Claude Code can't authenticate on this host (claude isn't on PATH):"
        " no session starts; fix: install claude, then rerun shipmill launchd"
    )


def test_a_failed_notification_is_reported_and_tried_again(checkout: Git) -> None:
    notifier = FakeNotifier(fail="osascript failed")
    auth = FakeAuth([LOGGED_OUT, LOGGED_OUT])
    lines = tick(checkout, headless(), FakeClaude(), auth, notifier)[2]
    assert lines[1] == "  notify failed: osascript failed"
    notifier.fail = None
    lines = tick(checkout, headless(), FakeClaude(), auth, notifier, NOW + dt.timedelta(minutes=5))[2]
    assert lines[1] == "  notified" and len(notifier.sent) == 1


def test_notify_off_sends_nothing(checkout: Git) -> None:
    notifier = FakeNotifier()
    quiet = AgentsConfig(prompt="/t", prs=False, retry_hours=24, notify=False, mode=headless().mode)
    action, _, lines = tick(checkout, quiet, FakeClaude(), FakeAuth([LOGGED_OUT]), notifier)
    assert (action, notifier.sent, len(lines)) == (Action.CLAUDE_AUTH, [], 2)  # the head and the finding


def test_a_dry_run_asks_but_writes_and_sends_nothing(checkout: Git) -> None:
    notifier = FakeNotifier()
    action, _, lines = tick(checkout, headless(), FakeClaude(), FakeAuth([LOGGED_OUT]), notifier, dry_run=True)
    assert (action, lines[1], notifier.sent) == (Action.CLAUDE_AUTH, "  would notify", [])
    assert not (state_dir(checkout) / AUTH).exists()


def test_a_tick_with_nothing_to_launch_asks_nothing(checkout: Git) -> None:
    launched_at(checkout, FIRST, NOW - dt.timedelta(hours=1))
    died(checkout, FIRST, NOW - dt.timedelta(hours=1), dt.timedelta(minutes=30), "done\n")
    auth = FakeAuth([])
    assert tick(checkout, headless(), FakeClaude(), auth, FakeNotifier())[0] is Action.UNCHANGED
    assert auth.asked == 0


def test_the_tick_record_carries_the_preflight(checkout: Git) -> None:
    decision, launched, waiting, pruned = gate(
        checkout,
        "romamo/demo",
        headless,
        FakeClaude(),
        Reads(),
        NOW,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        login=lambda: LOGIN,
        started=gone,
        auth=FakeAuth([LOGGED_OUT]),
    )
    record = tick_record(decision, launched, waiting, pruned, False)
    assert record["auth"] == {
        "ok": False,
        "problem": "claude auth status says not logged in",
        "fix": "claude auth login",
    }
    assert record["dead"] is None


# point 2: a dead session isn't an attempt


def test_a_session_that_died_in_a_second_is_no_attempt_and_the_next_tick_launches(checkout: Git) -> None:
    # #500: one dead session held its findings for retry_hours, reading UNCHANGED until tomorrow
    launched_at(checkout, FIRST, NOW - dt.timedelta(minutes=5))
    died(checkout, FIRST, NOW - dt.timedelta(minutes=5), dt.timedelta(seconds=1), f"{SECRET}\n{EXPIRED}\n")
    claude = FakeClaude()
    action, launched, lines = tick(
        checkout, headless(), claude, FakeAuth([LOGGED_IN]), FakeNotifier(), new_session=Clock([SECOND]).next
    )
    assert (action, launched) == (Action.SESSION_DEAD, str(SECOND))
    assert lines[0] == (
        f"SESSION_DEAD: session {FIRST} ended 1 s after its launch, its log shows an authentication failure;"
        f" its log's last line: {EXPIRED!r}; starting another for 1 finding(s); fix: claude auth login"
    )
    assert not any(SECRET in line for line in lines)  # only the log's last line is ever shown
    record = json.loads((state_dir(checkout) / RECORD).read_text(encoding="utf-8"))
    assert record["session"] == str(SECOND)
    assert record["dead"] == {"count": 1, "since": (NOW - dt.timedelta(minutes=5)).isoformat()}


def test_sessions_dying_one_after_another_read_as_one_run(checkout: Git) -> None:
    first_at = NOW - dt.timedelta(minutes=10)
    launched_at(checkout, SECOND, NOW - dt.timedelta(minutes=5), Deaths(1, first_at))
    died(checkout, SECOND, NOW - dt.timedelta(minutes=5), dt.timedelta(seconds=3), "")
    action, _, lines = tick(checkout, headless(), FakeClaude(), FakeAuth([LOGGED_IN]), FakeNotifier())
    assert action is Action.SESSION_DEAD
    log = log_of(checkout, SECOND)
    since = first_at.isoformat(timespec="minutes")
    assert lines[0] == (
        f"SESSION_DEAD: session {SECOND} ended 3 s after its launch, 2 in a row since {since};"
        f" its log is empty; starting another for 1 finding(s); fix: tail -n 20 {log}"
    )
    assert load_launch(state_dir(checkout) / RECORD) == Launch(
        fingerprint([ISSUES]), str(FIRST), NOW, Process(PID, None), Deaths(2, first_at)
    )


def test_a_third_dead_session_in_a_row_holds_the_same_findings_for_retry_hours(checkout: Git) -> None:
    # without a cap, every tick started a real `claude -p` that died the same way
    first_at, at = NOW - dt.timedelta(minutes=10), NOW - dt.timedelta(minutes=5)
    launched_at(checkout, SECOND, at, Deaths(2, first_at))
    died(checkout, SECOND, at, dt.timedelta(seconds=3), "")
    claude, auth = FakeClaude(), FakeAuth([])
    action, launched, lines = tick(checkout, headless(), claude, auth, FakeNotifier())
    assert (action, launched, claude.started, auth.asked) == (Action.SESSION_DEAD, None, [], 0)
    since, again = first_at.isoformat(timespec="minutes"), (at + dt.timedelta(hours=24)).isoformat(timespec="minutes")
    assert lines[0] == (
        f"SESSION_DEAD: session {SECOND} ended 3 s after its launch, 3 in a row since {since}; its log is empty;"
        f" no session starts for the same findings until {again}; fix: tail -n 20 {log_of(checkout, SECOND)}"
    )
    after = NOW + dt.timedelta(hours=24)  # past retry_hours, it tries once more and counts on
    action, launched, _ = tick(checkout, headless(), claude, FakeAuth([LOGGED_IN]), FakeNotifier(), after)
    assert (action, launched) == (Action.SESSION_DEAD, str(FIRST))
    assert load_launch(state_dir(checkout) / RECORD) == Launch(
        fingerprint([ISSUES]), str(FIRST), after, Process(PID, None), Deaths(3, first_at)
    )


def test_a_healthy_session_that_finished_in_seconds_is_an_attempt(checkout: Git) -> None:
    launched_at(checkout, FIRST, NOW - dt.timedelta(minutes=5))
    died(checkout, FIRST, NOW - dt.timedelta(minutes=5), dt.timedelta(seconds=20), "Nothing needed a change.\n")
    assert tick(checkout, headless(), FakeClaude(), None, FakeNotifier())[0] is Action.UNCHANGED


def test_a_quick_session_whose_only_line_is_an_error_ended_dead(checkout: Git) -> None:
    launched_at(checkout, FIRST, NOW - dt.timedelta(minutes=5))
    died(checkout, FIRST, NOW - dt.timedelta(minutes=5), dt.timedelta(seconds=2), "API Error: 529 Overloaded\n")
    assert tick(checkout, headless(), FakeClaude(), FakeAuth([LOGGED_IN]), FakeNotifier())[0] is Action.SESSION_DEAD


def test_a_long_session_whose_log_shows_an_auth_failure_ended_dead(checkout: Git) -> None:
    launched_at(checkout, FIRST, NOW - dt.timedelta(hours=3))
    died(checkout, FIRST, NOW - dt.timedelta(hours=3), dt.timedelta(hours=2), f"work\n{EXPIRED}\n")
    assert tick(checkout, headless(), FakeClaude(), None, FakeNotifier())[0] is Action.SESSION_DEAD


def test_a_session_that_ran_still_holds_its_findings_for_retry_hours(checkout: Git) -> None:
    launched_at(checkout, FIRST, NOW - dt.timedelta(hours=1))
    died(checkout, FIRST, NOW - dt.timedelta(hours=1), dt.timedelta(seconds=61), "Done: triaged #12\n")
    action, launched, _ = tick(checkout, headless(), FakeClaude(), None, FakeNotifier())
    assert (action, launched) == (Action.UNCHANGED, None)


def test_a_dead_session_while_the_login_fails_starts_nothing_and_names_it(checkout: Git) -> None:
    launched_at(checkout, FIRST, NOW - dt.timedelta(minutes=5))
    log = died(checkout, FIRST, NOW - dt.timedelta(minutes=5), dt.timedelta(seconds=1), f"{EXPIRED}\n")
    claude = FakeClaude()
    action, _, lines = tick(checkout, headless(), claude, FakeAuth([LOGGED_OUT]), FakeNotifier())
    assert (action, claude.started) == (Action.CLAUDE_AUTH, [])
    assert lines[2] == (
        f"  session {FIRST} ended 1 s after its launch, its log shows an authentication failure;"
        f" its log's last line: {EXPIRED!r}; fix: claude auth login"
    )
    assert log.is_file() and load_launch(state_dir(checkout) / RECORD) is not None  # the record stays as it was


def test_a_session_that_still_runs_is_never_read_dead(checkout: Git) -> None:
    launched_at(checkout, FIRST, NOW - dt.timedelta(minutes=5))
    died(checkout, FIRST, NOW - dt.timedelta(minutes=5), dt.timedelta(seconds=1), f"{EXPIRED}\n")
    action = tick(checkout, headless(), FakeClaude(), None, FakeNotifier(), started=lambda pid: STARTED)[0]
    assert action is Action.RUNNING


def test_an_interactive_launch_claude_agents_no_longer_lists_is_an_attempt(checkout: Git) -> None:
    save_launch(state_dir(checkout) / RECORD, Launch(fingerprint([ISSUES]), "s1", NOW - dt.timedelta(minutes=5)))
    assert tick(checkout, interactive(), FakeClaude(), None, FakeNotifier())[0] is Action.UNCHANGED


# point 2 for an interactive session: `claude agents` shows how it ended, as it leaves no log

OLD = "0b8f"  # the last interactive session's id, as `claude --bg` printed it


def listed(state: str | None, status: str | None = "idle") -> FakeClaude:
    """`claude agents --json` listing the last interactive gate session with this state"""
    return FakeClaude(listed=[Session(OLD, "shipmill romamo/demo 2026-10-04 11:55", status, state)])


def launched_interactive(git: Git, at: dt.datetime, deaths: Deaths | None = None) -> None:
    """gate.json as an interactive launch records it: no mode, pid, or log"""
    save_launch(state_dir(git) / RECORD, Launch(fingerprint([ISSUES]), OLD, at, None, deaths))


def test_an_interactive_session_that_failed_is_no_attempt_and_the_next_tick_launches(checkout: Git) -> None:
    # #500: a `claude --bg` session that died still held its findings for retry_hours
    launched_interactive(checkout, NOW - dt.timedelta(minutes=5))
    claude = listed("failed")
    action, launched, lines = tick(checkout, interactive(), claude, FakeAuth([LOGGED_IN]), FakeNotifier())
    assert (action, launched, claude.stopped) == (Action.SESSION_DEAD, "s1", [OLD])
    assert lines[0] == (
        f"SESSION_DEAD: session {OLD} ended failed in claude agents; starting another for 1 finding(s);"
        f" fix: claude logs {OLD}"
    )
    record = json.loads((state_dir(checkout) / RECORD).read_text(encoding="utf-8"))
    assert record["session"] == "s1" and "mode" not in record and "pid" not in record
    assert record["dead"] == {"count": 1, "since": (NOW - dt.timedelta(minutes=5)).isoformat()}


def test_an_interactive_session_done_within_a_minute_of_its_launch_ended_dead(checkout: Git) -> None:
    launched_interactive(checkout, NOW - dt.timedelta(seconds=40))
    action, _, lines = tick(checkout, interactive(), listed("done"), FakeAuth([LOGGED_IN]), FakeNotifier())
    assert action is Action.SESSION_DEAD
    assert lines[0].startswith(f"SESSION_DEAD: session {OLD} ended done in claude agents, within 40 s of its launch;")


def test_an_interactive_session_done_after_a_long_run_is_an_attempt(checkout: Git) -> None:
    # the gate can't tell when a session became done, only that it was by this tick: never dead then
    launched_interactive(checkout, NOW - dt.timedelta(seconds=61))
    claude = listed("done")
    action, launched, lines = tick(checkout, interactive(), claude, None, FakeNotifier())
    assert (action, launched, claude.stopped) == (Action.UNCHANGED, None, [])
    assert not any("ended" in line for line in lines)


@pytest.mark.parametrize(
    ("state", "status", "action"), [("blocked", "idle", Action.WAITING), ("working", "busy", Action.RUNNING)]
)
def test_an_interactive_session_that_waits_or_works_is_not_dead(
    checkout: Git, state: str, status: str, action: Action
) -> None:
    launched_interactive(checkout, NOW - dt.timedelta(seconds=10))
    assert tick(checkout, interactive(), listed(state, status), None, FakeNotifier())[0] is action


def test_a_third_dead_interactive_session_in_a_row_holds_the_same_findings_for_retry_hours(checkout: Git) -> None:
    first_at, at = NOW - dt.timedelta(minutes=30), NOW - dt.timedelta(minutes=5)
    launched_interactive(checkout, at, Deaths(2, first_at))
    claude, auth = listed("failed"), FakeAuth([])
    action, launched, lines = tick(checkout, interactive(), claude, auth, FakeNotifier())
    assert (action, launched, claude.launched, claude.stopped, auth.asked) == (Action.SESSION_DEAD, None, [], [], 0)
    since, again = first_at.isoformat(timespec="minutes"), (at + dt.timedelta(hours=24)).isoformat(timespec="minutes")
    assert lines[0] == (
        f"SESSION_DEAD: session {OLD} ended failed in claude agents, 3 in a row since {since};"
        f" no session starts for the same findings until {again}; fix: claude logs {OLD}"
    )
    after = NOW + dt.timedelta(hours=24)  # past retry_hours, it tries once more and counts on
    action, launched, _ = tick(checkout, interactive(), claude, FakeAuth([LOGGED_IN]), FakeNotifier(), after)
    assert (action, launched) == (Action.SESSION_DEAD, "s1")
    assert load_launch(state_dir(checkout) / RECORD) == Launch(
        fingerprint([ISSUES]), "s1", after, None, Deaths(3, first_at)
    )


def test_the_tick_record_names_a_dead_interactive_session_by_its_state(checkout: Git) -> None:
    launched_interactive(checkout, NOW - dt.timedelta(minutes=5))
    decision, launched, waiting, pruned = gate(
        checkout,
        "romamo/demo",
        interactive,
        listed("failed"),
        Reads(),
        NOW,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        login=lambda: LOGIN,
        started=gone,
        auth=FakeAuth([LOGGED_IN]),
    )
    assert tick_record(decision, launched, waiting, pruned, False)["dead"] == {
        "session": OLD,
        "log": None,
        "seconds": None,
        "auth": False,
        "last_line": "",
        "count": 1,
        "since": (NOW - dt.timedelta(minutes=5)).isoformat(),
        "state": "failed",
    }


def test_a_gate_json_from_before_500_still_reads(checkout: Git) -> None:
    path = state_dir(checkout) / RECORD
    path.parent.mkdir(parents=True)
    old = {"fingerprint": "f", "session": str(FIRST), "at": NOW.isoformat(), "mode": "headless", "pid": 7}
    path.write_text(json.dumps({**old, "started": STARTED}), encoding="utf-8")
    assert load_launch(path) == Launch("f", str(FIRST), NOW, Process(7, STARTED))


@pytest.mark.parametrize("dead", [[], {"count": 1}, {"count": 0, "since": NOW.isoformat()}, {"count": 1, "since": "x"}])
def test_a_malformed_dead_record_is_refused(checkout: Git, dead: object) -> None:
    path = state_dir(checkout) / RECORD
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"fingerprint": "f", "session": "s1", "at": NOW.isoformat(), "dead": dead}))
    with pytest.raises(ReleaseError, match="is malformed"):
        load_launch(path)
