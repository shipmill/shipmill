"""Spec 089: a credential's pause, shared by every gate on the host. A session that ended limit
or auth writes it for the credential it ran with (S-089-5); while it holds, no gate using that
credential starts a session, and the item counts no attempt (S-089-6); a new token, or a login
for a gate without one, ends it (S-089-9); an auth pause notifies once (S-089-10)"""

import datetime as dt
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from shipmill.agents import Mode
from shipmill.claude_auth import ClaudeAuth
from shipmill.claude_pause import (
    LOGIN,
    Pause,
    UsageProbe,
    credential_id,
    load_pause,
    newest_reset,
    pause_path,
    pauses_dir,
    save_pause,
)
from shipmill.claude_token import Credential, Token, TokenSource
from shipmill.errors import ReleaseError
from shipmill.gate import DEAD_STREAK, RECORD, Action, Decision, load_launch, session_log, state_dir
from shipmill.gitrepo import Git
from shipmill.walk import End

from .test_gate import FakeClaude, FakeNotifier, checkout
from .test_gate_walk import INCIDENT, NOW, ONE, Source, cfg, tick

__all__ = ["checkout"]  # the fixture, imported for the tests below

TOKEN = "sk-ant-oat01-first\n"  # not a real token
RESETS = 1795608000  # 2026-11-25T06:40:00Z
EARLIER = 1795448400
LIMITED = (
    {"type": "system", "subtype": "init"},
    {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed_warning", "resetsAt": EARLIER}},
    {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": RESETS}},
    {"type": "assistant", "api_error_status": 429},
    {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 429},
)
REFUSED = (
    {"type": "system", "subtype": "init"},
    {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 401},
)
OK = ({"type": "result", "subtype": "success", "is_error": False},)
SESSION = str(ONE)  # the session every headless launch here gets
LATER = NOW + dt.timedelta(minutes=10)


def token_at(path: Path, text: str = TOKEN) -> Credential:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return Credential(TokenSource(path, named=True), Token(path, text.removesuffix("\n"), NOW))


def ended(git: Git, *events: object) -> None:
    """The launched session's log: these events, written a minute after NOW"""
    log = session_log(state_dir(git), SESSION)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    moment = (NOW + dt.timedelta(minutes=1)).timestamp()
    os.utime(log, (moment, moment))


class Gate:
    """A headless gate on one checkout whose pauses live in folder, its credential given"""

    def __init__(self, git: Git, folder: Path, credential: Credential | None = None, **keys: Any) -> None:
        self.git, self.folder, self.credential = git, folder, credential
        self.claude, self.notifier = FakeClaude(), FakeNotifier()
        self.agents = cfg(Mode.HEADLESS, **keys)
        self.asked: list[Token | None] = []
        self.logged_in = True
        self.usage: UsageProbe | None = None  # spec 089's /usage probe; None: the gate runs none

    def auth(self, token: Token | None) -> ClaudeAuth:
        self.asked.append(token)
        return ClaudeAuth(None if self.logged_in else "claude auth status says not logged in")

    def tick(self, now: dt.datetime, signature: str = "sig") -> Decision:
        found = self.credential
        return tick(
            self.git,
            Source({1: [INCIDENT]}, signature=signature),
            now,
            self.agents,
            self.claude,
            self.notifier,
            pauses=self.folder,
            auth=self.auth,
            credential=None if found is None else (lambda: found),
            usage=self.usage,
        )


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return tmp_path / "state" / "shipmill" / "claude"


# -- S-089-5: the record


def test_s089_5_the_pause_lives_under_xdg_state_home_or_local_state(tmp_path: Path) -> None:
    assert pauses_dir({"XDG_STATE_HOME": "/x/state"}, tmp_path) == Path("/x/state/shipmill/claude")
    for unset in ({}, {"XDG_STATE_HOME": ""}):
        assert pauses_dir(unset, tmp_path) == tmp_path / ".local" / "state" / "shipmill" / "claude"
    with pytest.raises(ReleaseError, match="absolute"):
        pauses_dir({"XDG_STATE_HOME": "state"}, tmp_path)


def test_s089_5_a_credential_is_named_by_its_token_files_hash_or_login(tmp_path: Path) -> None:
    found = token_at(tmp_path / "claude-token")
    assert credential_id(found.token) == hashlib.sha256(TOKEN.encode()).hexdigest()[:16]
    assert credential_id(None) == LOGIN


def test_s089_5_a_limit_end_writes_its_credentials_pause_without_the_token(
    checkout: Git, folder: Path, tmp_path: Path
) -> None:
    credential = token_at(tmp_path / "claude-token")
    gate = Gate(checkout, folder, credential)
    assert gate.tick(NOW).action is Action.LAUNCH
    launch = load_launch(state_dir(checkout) / RECORD)
    named = credential_id(credential.token)
    assert launch is not None and launch.credential == named  # gate.json records what it ran with
    ended(checkout, *LIMITED)
    gate.tick(LATER)
    path = pause_path(folder, named)
    assert json.loads(path.read_text()) == {
        "cause": "limit",
        "session": SESSION,
        "at": (NOW + dt.timedelta(minutes=1)).isoformat(),
        "resets_at": dt.datetime.fromtimestamp(RESETS, tz=dt.UTC).isoformat(),  # the newest of the two
    }
    assert "sk-ant" not in path.read_text()


def test_s089_5_an_auth_end_writes_its_pause_with_no_resets_at(checkout: Git, folder: Path) -> None:
    gate = Gate(checkout, folder)  # no token file: the login
    gate.tick(NOW)
    ended(checkout, *REFUSED)
    gate.logged_in = False
    gate.tick(LATER)
    found = load_pause(folder, LOGIN)
    assert found is not None and (found.cause, found.session, found.resets_at) == (End.AUTH, SESSION, None)


# -- S-089-6: a pause starts nothing and counts no attempt


def test_s089_6_while_its_credentials_pause_holds_a_tick_starts_nothing_and_reads_paused(
    checkout: Git, folder: Path, tmp_path: Path
) -> None:
    credential = token_at(tmp_path / "claude-token")
    gate = Gate(checkout, folder, credential)
    gate.tick(NOW)
    ended(checkout, *LIMITED)
    started = len(gate.claude.started)
    for minutes in (10, 20, 30):
        decision = gate.tick(NOW + dt.timedelta(minutes=minutes))
        assert decision.action is Action.PAUSED and len(gate.claude.started) == started
        resets = dt.datetime.fromtimestamp(RESETS, tz=dt.UTC).isoformat(timespec="minutes")
        assert decision.reason == f"limit: a usage limit stopped session {SESSION}; no session starts until {resets}"


def test_s089_6_any_gate_on_the_host_with_that_credential_reads_the_pause(
    checkout: Git, folder: Path, tmp_path: Path
) -> None:
    credential = token_at(tmp_path / "claude-token")
    named = credential_id(credential.token)
    save_pause(folder, named, Pause(End.LIMIT, "another-gates-session", NOW, NOW + dt.timedelta(hours=2)))
    gate = Gate(checkout, folder, credential)  # a gate that never launched: no dead session of its own
    decision = gate.tick(NOW)
    assert decision.action is Action.PAUSED and not gate.claude.started
    other = Gate(checkout, folder, token_at(tmp_path / "other-token", "sk-ant-oat01-other\n"))
    assert other.tick(NOW).action is Action.LAUNCH  # another credential is not paused


def test_s089_6_a_pause_counts_no_attempt_against_the_item_that_hit_it(checkout: Git, folder: Path) -> None:
    gate = Gate(checkout, folder)
    gate.tick(NOW)
    for round in range(DEAD_STREAK + 1):  # past DEAD_STREAK limit ends in a row: never held for retry_hours
        ended(checkout, *LIMITED)
        at = NOW + dt.timedelta(days=round + 1)
        save_pause(folder, LOGIN, Pause(End.LIMIT, SESSION, at, None, None, at))  # its pause, as a lift leaves it
        decision = gate.tick(at)
        assert decision.action is Action.SESSION_DEAD and decision.work == (INCIDENT,)  # handed again at once
        launch = load_launch(state_dir(checkout) / RECORD)
        assert launch is not None and launch.deaths is None


# -- S-089-9: a new token or a login ends it


@pytest.mark.parametrize("events", [LIMITED, REFUSED], ids=["limit", "auth"])
def test_s089_9_a_new_token_ends_the_pause_and_the_held_item_launches(
    checkout: Git, folder: Path, tmp_path: Path, events: tuple[object, ...]
) -> None:
    path = tmp_path / "claude-token"
    gate = Gate(checkout, folder, token_at(path))
    gate.tick(NOW)
    ended(checkout, *events)
    assert gate.tick(LATER).action is Action.PAUSED
    gate.credential = token_at(path, "sk-ant-oat01-second\n")
    decision = gate.tick(LATER + dt.timedelta(minutes=10))
    assert decision.action is Action.SESSION_DEAD and decision.work == (INCIDENT,)  # launched, naming the death
    launch = load_launch(state_dir(checkout) / RECORD)
    assert launch is not None and launch.credential == credential_id(gate.credential.token)


def test_s089_9_a_gate_without_a_token_lifts_an_auth_pause_once_claude_reports_a_login(
    checkout: Git, folder: Path
) -> None:
    gate = Gate(checkout, folder)
    gate.tick(NOW)
    ended(checkout, *REFUSED)
    gate.logged_in = False
    assert gate.tick(LATER).action is Action.PAUSED
    assert gate.tick(LATER + dt.timedelta(minutes=10)).action is Action.PAUSED
    gate.logged_in = True
    assert gate.tick(LATER + dt.timedelta(minutes=20)).action is Action.SESSION_DEAD
    found = load_pause(folder, LOGIN)
    assert found is not None and not found.holds  # kept, lifted, so the same end never writes it again


def test_s089_9_a_token_files_auth_pause_holds_however_the_login_reads(
    checkout: Git, folder: Path, tmp_path: Path
) -> None:
    gate = Gate(checkout, folder, token_at(tmp_path / "claude-token"))
    gate.tick(NOW)
    ended(checkout, *REFUSED)
    decision = gate.tick(LATER)
    assert decision.action is Action.PAUSED
    assert decision.reason.endswith(
        f"no session starts until the token changes; fix: the token in {tmp_path / 'claude-token'} was not"
        f" accepted; run claude setup-token and save it to {tmp_path / 'claude-token'}"
    )


def test_s089_8_a_limit_pause_lifts_by_the_clock_at_resets_at_or_after_retry_hours(checkout: Git, folder: Path) -> None:
    resets = dt.datetime.fromtimestamp(RESETS, tz=dt.UTC)
    save_pause(folder, LOGIN, Pause(End.LIMIT, "s0", NOW, resets))
    gate = Gate(checkout, folder)
    assert gate.tick(resets - dt.timedelta(minutes=1)).action is Action.PAUSED
    assert gate.tick(resets, signature="next").action is Action.LAUNCH
    save_pause(folder, LOGIN, Pause(End.LIMIT, "s1", NOW))
    late = Gate(checkout, folder)
    assert late.tick(NOW + dt.timedelta(hours=23)).action is Action.PAUSED
    found = load_pause(folder, LOGIN)
    assert found is not None and found.until(LOGIN, dt.timedelta(hours=24)) == (NOW + dt.timedelta(hours=24)).isoformat(
        timespec="minutes"
    )


# -- S-089-10: one notification per auth pause


def test_s089_10_an_auth_pause_notifies_once_and_later_ticks_send_none(checkout: Git, folder: Path) -> None:
    gate = Gate(checkout, folder, notify=True)
    gate.tick(NOW)
    ended(checkout, *REFUSED)
    gate.logged_in = False
    for minutes in (10, 20, 30):
        gate.tick(NOW + dt.timedelta(minutes=minutes))
    assert len(gate.notifier.sent) == 1
    assert "claude auth login" in gate.notifier.sent[0][1]
    found = load_pause(folder, LOGIN)
    assert found is not None and found.notified == NOW + dt.timedelta(minutes=10)


def test_s089_10_a_failed_notification_is_sent_on_the_next_tick(checkout: Git, folder: Path) -> None:
    gate = Gate(checkout, folder, notify=True)
    gate.tick(NOW)
    ended(checkout, *REFUSED)
    gate.logged_in = False
    gate.notifier.fail = "no notifier"
    assert gate.tick(LATER).auth_notice == "notify failed: no notifier"
    gate.notifier.fail = None
    assert gate.tick(LATER + dt.timedelta(minutes=10)).auth_notice == "notified"
    assert gate.tick(LATER + dt.timedelta(minutes=20)).auth_notice is None


def test_s089_5_a_pause_file_shipmill_doesnt_write_is_refused(folder: Path) -> None:
    folder.mkdir(parents=True)
    pause_path(folder, LOGIN).write_text(json.dumps({"cause": "dead", "session": "s", "at": NOW.isoformat()}))
    with pytest.raises(ReleaseError, match="malformed"):
        load_pause(folder, LOGIN)


def test_s089_10_two_gates_on_one_token_whose_sessions_both_ended_auth_notify_once(
    checkout: Git, folder: Path, tmp_path: Path
) -> None:
    """Each gate's gate.json names its own dead session: neither replaces the other's held
    pause, so its notified mark stays and no tick of either sends another"""
    credential = token_at(tmp_path / "claude-token")
    root = tmp_path / "other"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    other = Git(root)
    other.run("remote", "add", "origin", "https://github.com/romamo/demo.git")
    first, second = Gate(checkout, folder, credential, notify=True), Gate(other, folder, credential, notify=True)
    first.tick(NOW)
    second.tick(NOW)
    ended(checkout, *REFUSED)
    record = state_dir(other) / RECORD
    launched = json.loads(record.read_text(encoding="utf-8"))
    launched["session"] = "22222222-2222-2222-2222-222222222222"
    record.write_text(json.dumps(launched), encoding="utf-8")
    log = session_log(state_dir(other), launched["session"])
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("".join(json.dumps(e) + "\n" for e in REFUSED), encoding="utf-8")
    for minutes in (10, 20, 30):
        at = NOW + dt.timedelta(minutes=minutes)
        assert first.tick(at).action is Action.PAUSED and second.tick(at).action is Action.PAUSED
    assert len(first.notifier.sent) + len(second.notifier.sent) == 1


def test_s089_5_a_gate_json_credential_that_isnt_a_credentials_name_is_refused(checkout: Git, folder: Path) -> None:
    """gate.json's credential names the pause file: one that could leave the folder is malformed"""
    gate = Gate(checkout, folder)
    gate.tick(NOW)
    record = state_dir(checkout) / RECORD
    launched = json.loads(record.read_text(encoding="utf-8"))
    launched["credential"] = "../../escaped"
    record.write_text(json.dumps(launched), encoding="utf-8")
    ended(checkout, *REFUSED)
    with pytest.raises(ReleaseError, match="malformed"):
        load_launch(record)
    with pytest.raises(ValueError, match="16 hex digits"):
        pause_path(folder, "../../escaped")
    assert not (folder.parent.parent / "escaped.json").exists()


def test_s089_5_resets_at_is_the_rejected_limits_not_a_later_windows_warning() -> None:
    def event(status: str, at: int) -> dict[str, object]:
        return {"type": "rate_limit_event", "rate_limit_info": {"status": status, "resetsAt": at}}

    stamp = dt.datetime.fromtimestamp
    found = newest_reset([event("allowed_warning", RESETS), event("rejected", EARLIER)])
    assert found == stamp(EARLIER, tz=dt.UTC)
    assert newest_reset([event("allowed", EARLIER), event("allowed_warning", RESETS)]) == stamp(RESETS, tz=dt.UTC)
    assert newest_reset([{"type": "result", "is_error": False}]) is None
