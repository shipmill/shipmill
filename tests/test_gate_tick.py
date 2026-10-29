"""Spec 048: a failing tick exits 2, and every real tick leaves its decision or its error, its
fix, and its run of failing ticks in tick.json before the prune (#816)"""

import datetime as dt
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig, Mode
from shipmill.autonomy import Hold
from shipmill.claude_auth import FIX as LOGIN_FIX
from shipmill.claude_auth import ClaudeAuth
from shipmill.claude_token import Kind, Token
from shipmill.cli import _gate_exit
from shipmill.errors import ReleaseError
from shipmill.gate import (
    DRY_RUN_FIX,
    ERROR,
    RECORD,
    TICK,
    Action,
    Decision,
    Failing,
    Finding,
    StateRead,
    TickRecord,
    decision_fix,
    gate,
    load_tick,
    require_dedicated,
    save_tick,
    state_dir,
)
from shipmill.github_auth import GitHubAuth
from shipmill.gitrepo import Git
from shipmill.hooks import HookTest
from shipmill.worktrees import Judged

from .test_gate import ISSUES, NO_PRUNE, NOW, FakeClaude, FakeNotifier, cfg, checkout, host, on_hold

__all__ = ["checkout"]  # the fixture, imported for the tests below

REPO = "romamo/demo"
LATER = NOW + dt.timedelta(minutes=15)
LOGGED_OUT = ClaudeAuth("claude auth status says not logged in")
BROKEN = HookTest("the PreToolUse hook exited 1", "update the plugin")
Rows = Callable[[StateRead], Sequence[Finding]]


def issues(_: StateRead) -> list[Finding]:
    return [ISSUES]


def tick(
    git: Git,
    now: dt.datetime = NOW,
    findings: Rows = issues,
    agents: AgentsConfig | None = None,
    hold: Callable[[], Hold] = Hold,
    auth: Callable[[Token | None], ClaudeAuth] | None = None,
    hooks: Callable[[], HookTest] | None = None,
    worktrees: Callable[[dt.datetime, bool], list[Judged]] = NO_PRUNE,
    dry_run: bool = False,
) -> Decision:
    config = cfg() if agents is None else agents
    decision, _, _, _ = gate(
        git,
        REPO,
        lambda: config,
        FakeClaude(),
        findings,
        now,
        hold,
        FakeNotifier(),
        worktrees,
        dry_run=dry_run,
        login=host,
        auth=auth,
        hooks=hooks,
    )
    return decision


def logged_out(token: Token | None) -> ClaudeAuth:
    return LOGGED_OUT


def written(git: Git) -> dict[str, object]:
    found = json.loads((state_dir(git) / TICK).read_text(encoding="utf-8"))
    assert isinstance(found, dict)
    return found


@pytest.mark.parametrize(
    ("decision", "code"),
    [
        (Decision(Action.CLAUDE_AUTH, "r", (), credential=Kind.LOGIN), 2),
        (Decision(Action.CLAUDE_AUTH, "r", (), credential=Kind.TOKEN_FILE), 2),
        (Decision(Action.GITHUB_AUTH, "r", ()), 2),
        (Decision(Action.HOOKS_FAILED, "r", ()), 2),
        *[
            (Decision(action, "r", ()), 0)
            for action in Action
            if action not in (Action.CLAUDE_AUTH, Action.GITHUB_AUTH, Action.HOOKS_FAILED)
        ],
    ],
    ids=lambda value: value.action.value + "-" + value.credential.value if isinstance(value, Decision) else str(value),
)
def test_s048_6_a_failing_decision_exits_2_and_every_other_one_0(decision: Decision, code: int) -> None:
    """PYPI_WAIT and STALLED among the 0s: the first clears itself, the gate cleared the second"""
    assert _gate_exit(decision) == code


def test_s048_6_a_login_claude_auth_tick_exits_2(checkout: Git) -> None:
    """Spec 035 let #500's login failure exit 0; spec 048 makes it a failing tick"""
    decision = tick(checkout, auth=logged_out)
    assert (decision.action, decision.credential, _gate_exit(decision)) == (Action.CLAUDE_AUTH, Kind.LOGIN, 2)


def test_s048_6_a_tick_a_release_error_ends_exits_2(checkout: Git, tmp_path: Path) -> None:
    """The CLI end to end: the checkout's origin is another repo, so the tick ends on its error"""
    env = {**os.environ, "HOME": str(tmp_path / "home")}
    command = [sys.executable, "-c", "from shipmill.cli import run; run()", "--repo", str(checkout.root)]
    done = subprocess.run([*command, "gate", "romamo/other"], capture_output=True, text=True, env=env)
    assert done.returncode == 2
    assert done.stderr.startswith(f"shipmill: {checkout.root}'s origin is https://github.com/romamo/demo.git")
    assert written(checkout)["fix"] == "run the gate in a checkout of romamo/other"


def test_s048_7_a_real_tick_writes_tick_json_and_a_dry_run_none(checkout: Git) -> None:
    tick(checkout, hold=on_hold, dry_run=True)
    assert not (state_dir(checkout) / TICK).exists()
    decision = tick(checkout, hold=on_hold)
    assert written(checkout) == {
        "at": NOW.isoformat(),
        "action": "HELD",
        "reason": decision.reason,
        "fix": None,
        "failing": None,
        "running": None,
        "in_flight": None,
    }
    assert not any(p.name.endswith(".tmp") for p in state_dir(checkout).iterdir())  # written whole


def test_s048_7_a_failing_decision_records_its_fix(checkout: Git) -> None:
    tick(checkout, auth=logged_out)
    record = written(checkout)
    assert (record["action"], record["fix"]) == ("CLAUDE_AUTH", LOGIN_FIX)
    assert record["failing"] == {"since": NOW.isoformat(), "count": 1}
    headless = AgentsConfig(prompt="/t", prs=False, retry_hours=24, mode=Mode.HEADLESS)
    decision = tick(checkout, LATER, agents=headless, hooks=lambda: BROKEN)
    assert decision.action is Action.HOOKS_FAILED and _gate_exit(decision) == 2
    record = written(checkout)
    assert (record["action"], record["reason"], record["fix"]) == ("HOOKS_FAILED", decision.reason, "update the plugin")


def test_s048_7_the_prunes_failure_changes_neither_tick_json_nor_the_exit_code(checkout: Git) -> None:
    def fails(now: dt.datetime, dry_run: bool) -> list[Judged]:
        raise ReleaseError("gh pr list failed: HTTP 502")

    decision = tick(checkout, hold=on_hold, worktrees=fails)
    assert decision.prune is not None and decision.prune.error == "gh pr list failed: HTTP 502"
    assert (written(checkout)["action"], written(checkout)["failing"], _gate_exit(decision)) == ("HELD", None, 0)


def test_s048_8_a_failing_tick_after_a_failing_one_keeps_since_and_counts_one_more(checkout: Git) -> None:
    tick(checkout, auth=logged_out)
    tick(checkout, LATER, auth=logged_out)
    assert written(checkout)["failing"] == {"since": NOW.isoformat(), "count": 2}

    def unreadable(_: StateRead) -> list[Finding]:
        raise ReleaseError("watch_state.py failed (exit 2)")

    third = LATER + dt.timedelta(minutes=15)
    with pytest.raises(ReleaseError):
        tick(checkout, third, findings=unreadable)
    assert written(checkout)["failing"] == {"since": NOW.isoformat(), "count": 3}  # an error counts in the run


def test_s048_8_a_tick_that_doesnt_fail_ends_the_run(checkout: Git) -> None:
    tick(checkout, auth=logged_out)
    tick(checkout, LATER, hold=on_hold)
    assert written(checkout)["failing"] is None
    again = LATER + dt.timedelta(minutes=15)
    tick(checkout, again, auth=logged_out)
    assert written(checkout)["failing"] == {"since": again.isoformat(), "count": 1}


def test_s048_8_a_malformed_tick_json_fails_the_tick_and_stays(checkout: Git) -> None:
    """As the gate's other state files: the tick ends on an error naming the file and its fix,
    and the file stays for a person to read"""
    path = state_dir(checkout) / TICK
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"at": "2026-10-04T12:00:00+00:00"}\n', encoding="utf-8")

    def unused(now: dt.datetime, dry_run: bool) -> list[Judged]:
        raise AssertionError("a tick its record fails prunes nothing")

    with pytest.raises(ReleaseError, match="tick.json is malformed .*; delete it to start over") as raised:
        tick(checkout, hold=on_hold, worktrees=unused)
    assert raised.value.fix == f"rm {path}"
    assert path.read_text(encoding="utf-8") == '{"at": "2026-10-04T12:00:00+00:00"}\n'


def test_s048_8_a_malformed_tick_json_fails_the_tick_before_it_launches(checkout: Git) -> None:
    """Read before the tick acts: a tick that started a session must not then end on its record"""
    path = state_dir(checkout) / TICK
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]\n", encoding="utf-8")
    claude = FakeClaude()
    with pytest.raises(ReleaseError, match="tick.json is malformed"):
        gate(checkout, REPO, cfg, claude, issues, NOW, Hold, FakeNotifier(), NO_PRUNE, login=host)
    assert (claude.launched, claude.started) == ([], [])
    assert not (state_dir(checkout) / RECORD).exists()


def test_s048_8_tick_json_round_trips() -> None:
    record = TickRecord(NOW, "GITHUB_AUTH", "r", "f", Failing(NOW, 3))
    with pytest.raises(ValueError, match="positive"):
        Failing(NOW, 0)
    with pytest.raises(ValueError, match="action"):
        TickRecord(NOW, "NOPE", "r", None, None)
    assert record.record()["failing"] == {"since": NOW.isoformat(), "count": 3}


def test_s048_8_load_tick_reads_what_save_tick_wrote(tmp_path: Path) -> None:
    path = tmp_path / TICK
    assert load_tick(path) is None
    record = TickRecord(NOW, ERROR, "boom", DRY_RUN_FIX, Failing(NOW, 2))
    save_tick(path, record)
    assert load_tick(path) == record


def test_s048_9_a_release_error_records_error_its_first_line_and_the_dry_run_fix(checkout: Git) -> None:
    def unreadable(_: StateRead) -> list[Finding]:
        raise ReleaseError("watch_state.py failed (exit 2): boom\nTraceback, more")

    def unused(now: dt.datetime, dry_run: bool) -> list[Judged]:
        raise AssertionError("a tick a ReleaseError ends prunes nothing (D-56)")

    with pytest.raises(ReleaseError, match="watch_state.py failed"):
        tick(checkout, findings=unreadable, worktrees=unused)
    assert written(checkout) == {
        "at": NOW.isoformat(),
        "action": ERROR,
        "reason": "watch_state.py failed (exit 2): boom",
        "fix": DRY_RUN_FIX,
        "failing": {"since": NOW.isoformat(), "count": 1},
        "running": None,
        "in_flight": None,
    }


def test_s048_9_an_error_with_a_fix_records_it(checkout: Git) -> None:
    """A malformed gate.json names its fix, so tick.json carries it, not the dry run"""
    record = state_dir(checkout) / RECORD
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ReleaseError, match="gate.json is malformed"):
        tick(checkout)
    assert (written(checkout)["action"], written(checkout)["fix"]) == (ERROR, f"rm {record}")


def test_s048_9_a_dry_run_that_errors_writes_no_tick_json(checkout: Git) -> None:
    def unreadable(_: StateRead) -> list[Finding]:
        raise ReleaseError("watch_state.py failed (exit 2)")

    with pytest.raises(ReleaseError):
        tick(checkout, findings=unreadable, dry_run=True)
    assert not (state_dir(checkout) / TICK).exists()


def test_s048_9_the_tick_paths_errors_carry_their_fix(checkout: Git) -> None:
    """The errors spec 048 names: a checkout on a branch, an --app-key without app_id"""
    checkout.run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "one")
    with pytest.raises(ReleaseError) as raised:
        require_dedicated(checkout, "main")
    assert raised.value.fix == f"git -C {checkout.root} switch --detach origin/main"
    with pytest.raises(ReleaseError, match="sets no app_id") as keyless:
        gate(checkout, REPO, cfg, FakeClaude(), issues, NOW, Hold, FakeNotifier(), NO_PRUNE, app_key_named=True)
    assert keyless.value.fix is not None and "app_id" in keyless.value.fix
    assert written(checkout)["fix"] == keyless.value.fix


def test_s048_10_any_other_exception_writes_no_tick_json_and_propagates(checkout: Git) -> None:
    def buggy(_: StateRead) -> list[Finding]:
        raise KeyError("a bug")

    with pytest.raises(KeyError):
        tick(checkout, findings=buggy)
    assert not (state_dir(checkout) / TICK).exists()


def test_s048_7_a_github_auth_decision_records_its_fix() -> None:
    """decision_fix reads the decision's own preflight"""
    failed = GitHubAuth("amy can't reach romamo/demo: HTTP 404", "gh auth login")
    assert decision_fix(Decision(Action.GITHUB_AUTH, failed.reason(), (), github=failed)) == "gh auth login"
    assert decision_fix(Decision(Action.QUIET, "nothing needs an agent", ())) is None
