"""Spec 089: while a usage limit pauses a credential, each tick asks `claude -p "/usage"`, with
the sessions' own credential, whether a window has room, and lifts the pause on the first that
shows none full (S-089-7); a probe that fails or can't be read falls back to the clock, the
pause's resetsAt or retry_hours (S-089-8)"""

import datetime as dt
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from shipmill.claude_pause import LOGIN, Pause, credential_id, load_pause, save_pause, usage_probe, usage_room
from shipmill.claude_token import OAUTH, Token
from shipmill.gate import Action
from shipmill.gitrepo import Git
from shipmill.walk import End

from .test_gate import checkout
from .test_gate_pause import LATER, LIMITED, Gate, ended, folder, token_at
from .test_gate_walk import NOW

__all__ = ["checkout", "folder"]  # the fixtures, imported for the tests below

# the window lines `claude -p "/usage"` prints, the rest of its output left out
ROOM = """You are currently using your subscription to power your Claude Code usage

Current session: 24% used · resets Nov 25 at 2:59am (Asia/Nicosia)
Current week (all models): 62% used · resets Nov 25 at 7:59am (Asia/Nicosia)
Current week (Fable): 27% used · resets Nov 25 at 7:59am (Asia/Nicosia)

What's contributing to your usage?
  58%  Review the plugin
"""
FULL = ROOM.replace("Current week (all models): 62% used", "Current week (all models): 100% used")
RESETS = NOW + dt.timedelta(hours=3)


class Probe:
    """`/usage`'s answers, one per tick: True, room; False, a window full; None, unread"""

    def __init__(self, *answers: bool | None) -> None:
        self.answers = list(answers)
        self.tokens: list[Token | None] = []

    def __call__(self, token: Token | None) -> bool | None:
        self.tokens.append(token)
        return self.answers.pop(0)


def limited(folder: Path, credential: str = LOGIN, resets: dt.datetime | None = RESETS) -> None:
    save_pause(folder, credential, Pause(End.LIMIT, "s0", NOW, resets))


# -- reading /usage


def test_s089_7_usage_shows_room_only_when_every_window_is_under_100() -> None:
    assert usage_room(ROOM) is True
    assert usage_room(FULL) is False
    assert usage_room(ROOM.replace("24% used", "101% used")) is False
    for unread in ("", "Unknown command: /usage", "Current session: n/a"):
        assert usage_room(unread) is None


def test_s089_7_the_probe_runs_usage_with_the_token_as_the_sessions_get_it(tmp_path: Path) -> None:
    token = token_at(tmp_path / "claude-token").token
    calls: list[tuple[list[str], Mapping[str, str]]] = []

    def run(cmd: list[str], env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, env))
        return subprocess.CompletedProcess(cmd, 0, ROOM, "")

    probe = usage_probe({"PATH": "/bin", "ANTHROPIC_API_KEY": "outranks"}, "/opt/claude", run)
    assert probe(token) is True
    ((cmd, env),) = calls
    assert cmd == ["/opt/claude", "-p", "/usage"]
    assert token is not None and env[OAUTH] == token.value and "ANTHROPIC_API_KEY" not in env


@pytest.mark.parametrize(
    "answer",
    [
        subprocess.CompletedProcess(["claude"], 1, ROOM, "error"),  # it exits non-zero, whatever it printed
        subprocess.CompletedProcess(["claude"], 0, "nothing it can read", ""),
        subprocess.TimeoutExpired(["claude"], 60),
        FileNotFoundError("claude"),
    ],
    ids=["non-zero", "unread", "timeout", "missing"],
)
def test_s089_8_a_probe_that_fails_or_cant_be_read_answers_none(answer: object) -> None:
    def run(cmd: list[str], env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
        if isinstance(answer, BaseException):
            raise answer
        assert isinstance(answer, subprocess.CompletedProcess)
        return answer

    assert usage_probe({}, "/opt/claude", run)(None) is None
    assert usage_probe({}, None, run)(None) is None  # claude isn't on PATH


# -- the gate


def test_s089_7_the_first_tick_whose_probe_shows_room_lifts_the_pause_and_launches(
    checkout: Git, folder: Path, tmp_path: Path
) -> None:
    credential = token_at(tmp_path / "claude-token")
    named = credential_id(credential.token)
    limited(folder, named)
    gate = Gate(checkout, folder, credential)
    gate.usage = probe = Probe(False, False, True)
    assert gate.tick(NOW).action is Action.PAUSED
    assert gate.tick(NOW + dt.timedelta(minutes=10), "b").action is Action.PAUSED
    assert gate.tick(NOW + dt.timedelta(minutes=20), "c").action is Action.LAUNCH
    assert probe.tokens == [credential.token] * 3  # the sessions' own token, never the host login
    found = load_pause(folder, named)
    assert found is not None and found.lifted == NOW + dt.timedelta(minutes=20)


def test_s089_7_a_probe_showing_a_window_full_holds_past_resets_at(checkout: Git, folder: Path) -> None:
    limited(folder)
    gate = Gate(checkout, folder)
    gate.usage = Probe(False)
    decision = gate.tick(RESETS + dt.timedelta(hours=1))
    assert decision.action is Action.PAUSED and decision.reason.endswith("; /usage shows a window full")


def test_s089_7_a_limit_a_session_hit_is_probed_from_the_next_tick(checkout: Git, folder: Path) -> None:
    gate = Gate(checkout, folder)
    gate.tick(NOW)
    ended(checkout, *LIMITED)
    gate.usage = Probe(False, True)
    assert gate.tick(LATER).action is Action.PAUSED
    assert gate.tick(LATER + dt.timedelta(minutes=10)).action is Action.SESSION_DEAD  # lifted, handed again


@pytest.mark.parametrize("resets", [RESETS, None], ids=["resetsAt", "retry_hours"])
def test_s089_8_an_unread_probe_holds_until_resets_at_or_retry_hours(
    checkout: Git, folder: Path, resets: dt.datetime | None
) -> None:
    limited(folder, resets=resets)
    lifts = resets or NOW + dt.timedelta(hours=24)
    gate = Gate(checkout, folder)
    gate.usage = Probe(None, None)
    decision = gate.tick(lifts - dt.timedelta(minutes=1))
    assert decision.action is Action.PAUSED and decision.reason.endswith("; /usage can't be read")
    assert gate.tick(lifts, "next").action is Action.LAUNCH


def test_s089_7_an_auth_pause_runs_no_probe(checkout: Git, folder: Path) -> None:
    save_pause(folder, LOGIN, Pause(End.AUTH, "s0", NOW))
    gate = Gate(checkout, folder)
    gate.logged_in = False
    gate.usage = probe = Probe()
    assert gate.tick(NOW).action is Action.PAUSED and probe.tokens == []


def test_s089_7_a_full_window_names_no_clock_the_pause_wont_lift_at(checkout: Git, folder: Path) -> None:
    limited(folder)
    gate = Gate(checkout, folder)
    gate.usage = Probe(False)
    reason = gate.tick(RESETS + dt.timedelta(hours=1)).reason
    assert RESETS.isoformat(timespec="minutes") not in reason  # passed, and a full window holds past it
    assert reason.endswith("no session starts until /usage shows room; /usage shows a window full")
