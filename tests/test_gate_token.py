"""Spec 035: gate sessions authenticate with a long-lived Claude token from a file. Never the
real claude and never a real token: the files hold a sentinel, the runners and spawners are
fakes, and every output the gate writes is scanned for any 8 characters of it"""

import datetime as dt
import json
import os
import plistlib
import re
import subprocess
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from shipmill import cli, status
from shipmill.agents import AgentsConfig
from shipmill.app import Identity
from shipmill.autonomy import Hold
from shipmill.claude_auth import COMMAND, ClaudeAuth, preflight_auth, token_auth
from shipmill.claude_token import (
    DEFAULT,
    OAUTH,
    OUTRANKING,
    REJECTED_SHAPE,
    SCRUB,
    Credential,
    Kind,
    Token,
    TokenSource,
    inspect,
    read_token,
    rejected_fix,
)
from shipmill.doctor import auth_check, doctor, token_check
from shipmill.gate import (
    BG_WAIT_CEILING,
    RECORD,
    WAITING,
    Action,
    ClaudeCli,
    Decision,
    Finding,
    Session,
    Wait,
    gate,
    headless_env,
    save_waiting,
    state_dir,
    tick_lines,
    tick_record,
)
from shipmill.gitrepo import Git
from shipmill.hooks import HookTest
from shipmill.launchd import build, cli_fix
from tests.conftest import Repo
from tests.test_agent_as_person import add_agents
from tests.test_status_picture import checked, facts, job, lines
from tests.test_status_picture import gate as status_gate

from .test_app import REPO
from .test_gate import ISSUES, NO_PRUNE, NOW, FakeClaude, FakeNotifier
from .test_gate_auth import FakeAuth, died, launched_at
from .test_gate_headless import GATE_ENV, LOGIN, SESSION, Reads, checkout, headless, interactive
from .test_gate_plugin import FakeRunner, markers_of, plugin_host

__all__ = ["checkout"]  # the fixture, imported for the tests below

SENTINEL = "sk-ant-oat01-Q7zX9wKp3Lm5Nr8Tv2Yb6Hd4Jf1Gc0Ue"
PASSED = HookTest(None, None, "self-test: refused")
LOGGED_IN = '{"loggedIn": true, "authMethod": "oauth_token"}'
WATCH = Path(__file__).resolve().parents[1] / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"


def pieces(secret: str) -> set[str]:
    """Every 8-character substring of secret: none may show anywhere the gate writes"""
    return {secret[i : i + 8] for i in range(len(secret) - 7)}


def leaks(text: str, secret: str = SENTINEL) -> set[str]:
    return {piece for piece in pieces(secret) if piece in text}


def token_file(home: Path, text: str = SENTINEL + "\n", mode: int = 0o600) -> Path:
    """The token saved at the default path under home"""
    path = home / DEFAULT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


def raw_file(home: Path, data: bytes) -> Path:
    path = token_file(home)
    path.write_bytes(data)
    return path


def credential_of(home: Path, given: Path | None = None) -> Credential:
    return inspect(TokenSource.of(given, home))


@dataclass
class Unopened:
    """A file system whose stat is the host's and whose read fails the test (S-035-5)"""

    opened: list[Path] = field(default_factory=list)

    def stat(self, path: Path) -> os.stat_result:
        return os.stat(path)

    def read(self, path: Path) -> bytes:
        self.opened.append(path)
        raise AssertionError(f"{path} was opened for reading")


@dataclass
class Launcher:
    """ClaudeCli's runners: run is the gate's own env (claude agents, claude stop, a launch
    without a token), run_in the env an interactive launch with a token gets, spawn a headless
    start's. Each records what it ran"""

    listed: str = "[]"
    run_calls: list[list[str]] = field(default_factory=list)
    run_in_calls: list[tuple[list[str], dict[str, str]]] = field(default_factory=list)
    spawned: list[tuple[list[str], dict[str, str]]] = field(default_factory=list)

    def run(self, cmd: list[str], cwd: Path) -> str:
        self.run_calls.append(cmd)
        if cmd[:2] == ["claude", "agents"]:
            return self.listed
        if cmd[:2] == ["claude", "--bg"]:
            return "started; claude attach s9\n"
        if cmd[:2] == ["claude", "stop"]:
            return ""
        raise AssertionError(f"unexpected command {cmd}")

    def run_in(self, cmd: list[str], cwd: Path, env: Mapping[str, str]) -> str:
        self.run_in_calls.append((cmd, dict(env)))
        assert cmd[:2] == ["claude", "--bg"], cmd
        return "started; claude attach s9\n"

    def spawn(self, cmd: list[str], cwd: Path, log: Path, env: Mapping[str, str]) -> int:
        self.spawned.append((cmd, dict(env)))
        return 4242

    def claude(self, environ: Mapping[str, str] = GATE_ENV) -> ClaudeCli:
        return ClaudeCli([], run=self.run, spawn=self.spawn, environ=environ, run_in=self.run_in)


def tick(
    git: Git,
    agents: AgentsConfig,
    claude: FakeClaude | ClaudeCli,
    found: Credential | None,
    reads: Reads | None = None,
    auth: FakeAuth | None = None,
    notifier: FakeNotifier | None = None,
    dry_run: bool = False,
) -> tuple[Decision, str | None, list[str], dict[str, object]]:
    decision, launched, waiting, pruned = gate(
        git,
        REPO,
        lambda: agents,
        claude,
        reads or Reads(),
        NOW,
        Hold,
        notifier or FakeNotifier(),
        NO_PRUNE,
        dry_run=dry_run,
        login=lambda: LOGIN,
        started=lambda pid: None,
        new_session=lambda: SESSION,
        auth=auth,
        credential=None if found is None else (lambda: found),
    )
    lines_ = tick_lines(decision, launched, waiting, pruned, dry_run)
    return decision, launched, lines_, tick_record(decision, launched, waiting, pruned, dry_run)


# S-035-1


def test_s035_1_without_a_token_file_sessions_get_the_gates_env_unchanged_and_auth_reads_login(
    checkout: Git, tmp_path: Path
) -> None:
    found = credential_of(tmp_path / "home")
    assert (found.kind, found.token, found.refused) == (Kind.LOGIN, None, None)
    runner = Launcher()
    decision, _, _, record = tick(checkout, headless(), runner.claude(), found)
    assert decision.action is Action.LAUNCH and record["auth"] == "login"
    [(_, env)] = runner.spawned
    assert env == headless_env(GATE_ENV)  # the env every headless session got before spec 035
    (state_dir(checkout) / RECORD).unlink()
    runner = Launcher()
    decision, launched, _, record = tick(checkout, interactive(), runner.claude(), found)
    assert (decision.action, launched, record["auth"]) == (Action.LAUNCH, "s9", "login")
    assert runner.run_in_calls == []  # `claude --bg` ran through the gate's own runner and env
    assert [cmd[:2] for cmd in runner.run_calls] == [["claude", "agents"], ["claude", "--bg"]]


# S-035-2


def test_s035_2_a_headless_session_gets_the_token_without_its_newline_and_the_scrub(
    checkout: Git, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    token_file(home)
    runner = Launcher()
    decision, _, lines_, record = tick(checkout, headless(), runner.claude(), credential_of(home))
    assert decision.action is Action.LAUNCH and record["auth"] == "token-file"
    [(cmd, env)] = runner.spawned
    assert cmd[:2] == ["claude", "-p"]
    assert (env[OAUTH], env[SCRUB], env[BG_WAIT_CEILING]) == (SENTINEL, "1", "0")
    assert lines_[0].endswith(" as token file")


# S-035-3


def test_s035_3_an_interactive_launch_runs_claude_bg_with_the_token_and_the_scrub(
    checkout: Git, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    token_file(home)
    runner = Launcher()
    decision, launched, _, _ = tick(checkout, interactive(), runner.claude(), credential_of(home))
    assert (decision.action, launched) == (Action.LAUNCH, "s9")
    [(cmd, env)] = runner.run_in_calls
    assert cmd[:2] == ["claude", "--bg"]
    assert (env[OAUTH], env[SCRUB]) == (SENTINEL, "1")
    assert GATE_ENV.items() <= env.items()


# S-035-4


def test_s035_4_no_launch_argument_holds_any_8_characters_of_the_token(tmp_path: Path) -> None:
    token = read_token(TokenSource(token_file(tmp_path)))
    assert token is not None
    runner = Launcher()
    claude = runner.claude()
    settings = {"PATH": "/state/bin:/usr/bin", "GIT_AUTHOR_NAME": "shipmill[bot]"}  # spec 004's --settings env
    claude.launch(tmp_path, "n", "the prompt", settings, token)
    claude.start(tmp_path, "n", "the prompt", uuid.UUID(int=1), tmp_path / "s.log", settings, token)
    [(bg, _)] = runner.run_in_calls
    [(p, _)] = runner.spawned
    assert "--settings" in bg and "--settings" in p
    assert leaks(json.dumps([bg, p])) == set()
    assert repr(token).count(SENTINEL[:8]) == 0  # nor its repr, which a traceback could show


# S-035-5


def stuck_session(git: Git) -> FakeClaude:
    """A blocked session past max_wait_minutes, which the waiting step would stop"""
    save_waiting(state_dir(git) / WAITING, {"b1": Wait(NOW - dt.timedelta(hours=1), None)})
    return FakeClaude(listed=[Session("b1", f"shipmill {REPO} x", "idle", "blocked")])


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o660, 0o644, 0o620, 0o601])
def test_s035_5_a_file_with_a_group_or_other_bit_exits_2_unopened_starting_and_stopping_none(
    checkout: Git, tmp_path: Path, mode: int
) -> None:
    path = token_file(tmp_path / "home", mode=mode)
    fs = Unopened()
    found = inspect(TokenSource(path), fs)
    claude = stuck_session(checkout)
    decision, launched, lines_, record = tick(checkout, headless(), claude, found)
    assert (decision.action, launched, claude.started, claude.launched, claude.stopped) == (
        Action.CLAUDE_AUTH,
        None,
        [],
        [],
        [],
    )
    assert fs.opened == []
    assert f"{path} has mode {mode:03o}" in lines_[0] and lines_[0].endswith(f"; fix: chmod 600 {path}")
    assert cli._gate_exit(decision) == 2 and record["auth"] == "token-file"


def test_s035_5_mode_400_is_accepted(tmp_path: Path) -> None:
    token = read_token(TokenSource(token_file(tmp_path, mode=0o400)))
    assert token is not None and token.value == SENTINEL


# S-035-6


@pytest.mark.parametrize("text", ["", "\n", "   \n\t\n"])
def test_s035_6_an_empty_or_blank_file_exits_2_naming_the_path(checkout: Git, tmp_path: Path, text: str) -> None:
    path = token_file(tmp_path / "home", text)
    claude = stuck_session(checkout)
    decision, launched, lines_, _ = tick(checkout, interactive(), claude, inspect(TokenSource(path)))
    assert (decision.action, launched, claude.launched, claude.stopped) == (Action.CLAUDE_AUTH, None, [], [])
    assert f"({path} is empty)" in lines_[0] and "claude setup-token" in lines_[0]
    assert cli._gate_exit(decision) == 2


# S-035-7


@pytest.mark.parametrize(
    ("data", "rule"),
    [
        (f"{SENTINEL}\nsk-ant-oat01-Bb8Cc7Dd6Ee5Ff4\n".encode(), "holds more than one non-empty line"),
        (b"sk-ant-oat01-Xx1Yy2 Zz3Ww4Vv5Uu6\n", "has whitespace in the token"),
        ("sk-ant-oat01-Ää9Öö8Üü7Ss6Tt5\n".encode(), "holds a non-ASCII or control byte"),
        (b"xoxb-1234567890-abcdefghijkl\n", "doesn't start with sk-ant-oat"),
        (b"sk-ant-api03-Kk9Jj8Hh7Gg6Ff5Ee4\n", "doesn't start with sk-ant-oat"),
    ],
)
def test_s035_7_a_malformed_token_exits_2_naming_the_rule_and_none_of_its_bytes(
    checkout: Git, tmp_path: Path, data: bytes, rule: str
) -> None:
    path = raw_file(tmp_path / "home", data)
    claude = FakeClaude()
    decision, launched, lines_, record = tick(checkout, headless(), claude, inspect(TokenSource(path)))
    assert (decision.action, launched, claude.started) == (Action.CLAUDE_AUTH, None, [])
    assert f"{path} {rule}" in lines_[0]
    shown = "\n".join(lines_) + json.dumps(record)
    secret = re.sub(rb"\s", b"", data).decode("utf-8", errors="replace")
    assert leaks(shown, secret) == set()
    assert cli._gate_exit(decision) == 2


# S-035-8


def test_s035_8_a_folder_or_a_file_of_another_user_exits_2_naming_the_path(checkout: Git, tmp_path: Path) -> None:
    folder = tmp_path / "home" / DEFAULT
    folder.mkdir(parents=True)
    for found, said in (
        (inspect(TokenSource(folder)), f"{folder} is not a regular file"),
        (
            inspect(TokenSource(token_file(tmp_path / "other")), uid=os.getuid() + 1),
            f"{tmp_path / 'other' / DEFAULT} is owned by uid {os.getuid()}",
        ),
    ):
        claude = FakeClaude()
        decision, launched, lines_, _ = tick(checkout, headless(), claude, found)
        assert (decision.action, launched, claude.started) == (Action.CLAUDE_AUTH, None, [])
        assert said in lines_[0]


@pytest.mark.skipif(os.getuid() == 0, reason="root reads a file of any mode")
@pytest.mark.parametrize("mode", [0o200, 0o000])
def test_s035_8_a_file_its_owner_cant_read_exits_2_rather_than_crashing(
    checkout: Git, tmp_path: Path, mode: int
) -> None:
    path = token_file(tmp_path / "home", mode=mode)
    found = inspect(TokenSource(path))  # raised PermissionError past every caller before
    claude = FakeClaude()
    decision, launched, lines_, _ = tick(checkout, headless(), claude, found)
    assert (decision.action, launched, claude.started) == (Action.CLAUDE_AUTH, None, [])
    assert f"{path} can't be read" in lines_[0] and lines_[0].endswith(f"; fix: chmod 600 {path}")
    assert cli._gate_exit(decision) == 2


# S-035-9


def test_s035_9_claude_token_reads_that_file_and_a_missing_one_never_falls_back(checkout: Git, tmp_path: Path) -> None:
    home = tmp_path / "home"
    token_file(home, "sk-ant-oat01-the-default-one\n")
    other = tmp_path / "elsewhere" / "token"
    other.parent.mkdir()
    other.write_text(SENTINEL + "\n", encoding="utf-8")
    other.chmod(0o600)
    args = cli._parser().parse_args(["--repo", str(checkout.root), "gate", REPO, "--claude-token", str(other)])
    found = cli._credential(args.claude_token, home)
    assert found.token is not None and found.token.value == SENTINEL and found.source.named
    missing = (tmp_path / "nowhere" / "token").resolve()
    refused = cli._credential(missing, home)
    assert (refused.kind, refused.token) == (Kind.TOKEN_FILE, None)
    claude = FakeClaude()
    decision, launched, lines_, _ = tick(checkout, interactive(), claude, refused)
    assert (decision.action, launched, claude.launched) == (Action.CLAUDE_AUTH, None, [])
    assert f"{missing}, named by --claude-token, doesn't exist" in lines_[0]
    assert lines_[0].endswith(f"fix: create {missing}, or drop --claude-token")
    assert cli._gate_exit(decision) == 2


# S-035-10


def test_s035_10_launchd_writes_the_flag_and_path_never_the_token(tmp_path: Path) -> None:
    folder = tmp_path / "bin"
    folder.mkdir()
    for name in ("claude", "gh", "git", "uvx"):
        (folder / name).write_text("#!/bin/sh\n", encoding="utf-8")
        (folder / name).chmod(0o755)
    path = token_file(tmp_path / "home")
    given = path.parent / ".." / path.parent.name / path.name
    args = cli._parser().parse_args(["launchd", REPO, "--claude-token", str(given)])
    resolved = TokenSource.of(args.claude_token, tmp_path).path  # as _launchd resolves it
    assert resolved == path.resolve()
    made = build(REPO, tmp_path / "gate", 15, "x", [], tmp_path, str(folder), lambda _: False, claude_token=resolved)
    plist = plistlib.loads(made.document)
    program = plist["ProgramArguments"]
    assert program[program.index("--claude-token") + 1] == str(resolved)
    assert OAUTH not in made.document.decode() and OAUTH not in plist["EnvironmentVariables"]
    assert leaks(made.document.decode()) == set()
    # a job rewritten by the latest shipmill keeps its token file's path (#570)
    assert f"--claude-token {resolved}" in cli_fix(plist, REPO)


# S-035-11


def test_s035_11_claude_agents_stop_plugin_and_the_hooks_self_test_run_without_the_token(
    checkout: Git, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    token_file(home)
    finished = json.dumps([{"id": "old", "name": f"shipmill {REPO} x", "kind": "background", "state": "done"}])
    runner = Launcher(listed=finished)
    plugin = FakeRunner(checkout.root)
    seen: list[str | None] = []

    def plugin_run(cmd: list[str], cwd: Path) -> str:
        seen.append(os.environ.get(OAUTH))
        return plugin(cmd, cwd)

    def hooks() -> HookTest:
        seen.append(os.environ.get(OAUTH))
        return PASSED

    host = replace(plugin_host(plugin, markers_of(checkout)), run=plugin_run)
    decision, launched, waiting, pruned = gate(
        checkout,
        REPO,
        interactive,
        runner.claude(),
        Reads(),
        NOW,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        login=lambda: LOGIN,
        started=lambda pid: None,
        plugin=host,
        hooks=hooks,
        credential=lambda: credential_of(home),
    )
    assert (decision.action, launched) == (Action.LAUNCH, "s9")
    # claude agents and claude stop ran through the gate's own runner, which takes no env
    assert [cmd[:2] for cmd in runner.run_calls] == [["claude", "agents"], ["claude", "stop"]]
    assert [cmd[:2] for cmd, _ in runner.run_in_calls] == [["claude", "--bg"]]  # the only one with the token
    assert plugin.calls and len(seen) == len(plugin.calls) + 1  # every plugin call, then the self-test
    assert seen == [None] * len(seen) and OAUTH not in os.environ  # the gate never changes its own env


# S-035-12


@pytest.mark.parametrize(
    ("reply", "problem"),
    [
        ('{"loggedIn": false, "authMethod": "none"}', "claude auth status says not logged in"),
        ('{"loggedIn": true, "authMethod": "claude.ai"}', "claude auth status names auth method 'claude.ai'"),
        ('{"loggedIn": true, "authMethod": "api_key"}', "claude auth status names auth method 'api_key'"),
    ],
)
def test_s035_12_the_preflight_runs_with_the_token_and_refuses_another_method(
    checkout: Git, tmp_path: Path, reply: str, problem: str
) -> None:
    home = tmp_path / "home"
    path = token_file(home)
    asked: list[tuple[list[str], dict[str, str]]] = []

    def run_in(cmd: list[str], env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
        asked.append((cmd, dict(env)))
        return subprocess.CompletedProcess(cmd, 0, reply, "")

    def unasked(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("with a token the preflight never runs in the gate's own env")

    auth = preflight_auth(GATE_ENV, "/bin/claude", unasked, run_in)
    claude = FakeClaude()
    decision, launched, waiting, pruned = gate(
        checkout,
        REPO,
        headless,
        claude,
        Reads(),
        NOW,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        login=lambda: LOGIN,
        started=lambda pid: None,
        auth=auth,
        credential=lambda: credential_of(home),
    )
    [(cmd, env)] = asked
    assert cmd == ["/bin/claude", *COMMAND[1:]] and env[OAUTH] == SENTINEL
    assert (decision.action, launched, claude.started) == (Action.CLAUDE_AUTH, None, [])
    line = tick_lines(decision, launched, waiting, pruned, False)[0]
    assert problem in line and line.endswith(f"fix: {rejected_fix(path)}") and "claude setup-token" in line
    assert cli._gate_exit(decision) == 2
    # status passes the token's fix on from the gate's log, not `claude auth login`
    found = facts(gate=status_gate(job=job(last=line)))
    assert [r.fix for r in status.report(found).reasons] == [rejected_fix(path)]


def test_s035_12_the_preflight_passes_on_the_environment_token(tmp_path: Path) -> None:
    token = read_token(TokenSource(token_file(tmp_path)))
    assert token is not None
    for reply in (LOGGED_IN, '{"loggedIn": true}'):  # an answer that names no method passes on loggedIn

        def run_in(cmd: list[str], env: Mapping[str, str], out: str = reply) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 0, out, "")

        found = token_auth(token, run_in, "/bin/claude", GATE_ENV)
        assert found.ok and auth_check(found).status == "PASS" and leaks(found.line()) == set()


# S-035-13


def test_s035_13_a_dead_session_with_an_auth_failure_names_the_token_fix(checkout: Git, tmp_path: Path) -> None:
    home = tmp_path / "home"
    path = token_file(home)
    first = uuid.UUID("11111111-1111-4111-8111-111111111111")
    launched_at(checkout, first, NOW - dt.timedelta(minutes=5))
    died(checkout, first, NOW - dt.timedelta(minutes=5), dt.timedelta(seconds=1), "Failed to authenticate\n")
    claude = FakeClaude()
    auth = FakeAuth([ClaudeAuth(None, token=path)])
    decision, launched, lines_, _ = tick(checkout, headless(), claude, credential_of(home), auth=auth)
    assert decision.action is Action.SESSION_DEAD and launched == str(SESSION)
    assert lines_[0].endswith(f"; fix: {rejected_fix(path)}") and "claude auth login" not in lines_[0]
    assert auth.tokens and auth.tokens[0] is not None and auth.tokens[0].path == path
    # status and the watch pass that fix on, as the gate wrote it last on the line
    found = facts(gate=status_gate(job=job(last=lines_[0])))
    assert [r.fix for r in status.report(found).reasons] == [rejected_fix(path)]
    assert REJECTED_SHAPE in WATCH.read_text(encoding="utf-8")  # watch_state.py's TOKEN_FIX is this shape


# S-035-14


def test_s035_14_a_tick_with_a_sentinel_token_writes_none_of_it_anywhere(checkout: Git, tmp_path: Path) -> None:
    home = tmp_path / "home"
    token_file(home)
    runner = Launcher()
    notifier = FakeNotifier()
    reads = Reads(rows=[ISSUES, Finding("NEEDS_DECISION", "items", "#7", False)])
    auth = FakeAuth([ClaudeAuth(None, token=home / DEFAULT)])
    decision, launched, lines_, record = tick(
        checkout, headless(), runner.claude(), credential_of(home), reads, auth, notifier
    )
    assert decision.action is Action.LAUNCH and launched == str(SESSION) and notifier.sent
    written = [p.read_text(encoding="utf-8", errors="replace") for p in state_dir(checkout).rglob("*") if p.is_file()]
    assert any(RECORD in str(p) for p in state_dir(checkout).rglob("*"))  # gate.json is among them
    sent = [f"{title}\n{body}" for title, body in notifier.sent]
    spoken = "\n".join([*lines_, json.dumps(record), *written, *sent, json.dumps([c for c, _ in runner.spawned])])
    assert leaks(spoken) == set()
    # a refused tick's text and record hold none of it either
    path = token_file(home, mode=0o644)
    decision, _, lines_, record = tick(checkout, headless(), FakeClaude(), inspect(TokenSource(path)))
    assert decision.action is Action.CLAUDE_AUTH and leaks("\n".join(lines_) + json.dumps(record)) == set()


# S-035-15


def test_s035_15_status_names_the_kind_or_the_refusal_never_the_token(tmp_path: Path) -> None:
    home = tmp_path / "home"
    with_token = facts(gate=status_gate(credential=credential_of(home), home=home))
    assert "  claude auth    login" in checked(with_token)
    path = token_file(home)
    found = facts(gate=status_gate(credential=credential_of(home), home=home))
    assert "  claude auth    token file ~/.config/shipmill/claude-token" in checked(found)
    path.chmod(0o644)
    refused = checked(facts(gate=status_gate(credential=credential_of(home), home=home)))
    said = f"{path} has mode 644, which group or others can read"
    at = refused.index(f"  claude auth    token file ~/.config/shipmill/claude-token: {said}")
    assert refused[at + 1] == f"                 fix: chmod 600 {path}"
    assert leaks("\n".join(lines(found) + checked(found) + refused)) == set()


def test_s035_15_status_reads_the_token_file_the_launchd_job_names(tmp_path: Path) -> None:
    home = tmp_path / "home"
    other = token_file(tmp_path / "other")
    root = tmp_path / "repo"
    (root / ".github").mkdir(parents=True)
    (root / ".github" / "shipmill.toml").write_text('[agents]\nprompt = "/t"\n', encoding="utf-8")

    def no_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("off a Mac status runs no launchctl")

    def no_app(app_id: int, key: Path) -> Identity:
        raise AssertionError("no app_id: no App check")

    read = status.read_gate(REPO, root, home, "linux", no_run, no_app, os.getuid())
    assert read.credential is not None and read.credential.kind is Kind.LOGIN
    found = TokenSource.of_job(["uvx", "gate", REPO, "--claude-token", str(other), "--refresh"], home)
    assert found == TokenSource(other, named=True)


# S-035-16


def test_s035_16_doctor_reports_the_kind_the_refusal_the_login_and_an_old_token(tmp_path: Path) -> None:
    home = tmp_path / "home"
    login = credential_of(home)
    assert token_check(login, False, NOW).status == "PASS"
    warned = token_check(login, True, NOW)
    assert (warned.status, warned.name) == ("WARN", "claude auth") and "claude setup-token" in warned.detail
    path = token_file(home)
    now = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC)
    ok = token_check(credential_of(home), True, now + dt.timedelta(days=30))
    assert (ok.status, ok.detail) == ("PASS", f"token file {path}")
    old = token_check(credential_of(home), True, now + dt.timedelta(days=331))
    assert old.status == "WARN" and "331 days ago" in old.detail and "claude setup-token" in old.detail
    path.chmod(0o640)
    failed = token_check(credential_of(home), True, now)
    assert failed.status == "FAIL" and failed.detail.endswith(f"fix: chmod 600 {path}")
    assert leaks(" ".join(c.detail for c in (ok, old, failed))) == set()


def test_s035_16_doctor_runs_the_token_check_with_agents_and_skips_the_preflight_on_a_refusal(
    repo: Repo, tmp_path: Path
) -> None:
    add_agents(repo, None)
    home = tmp_path / "home"
    path = token_file(home, mode=0o644)
    auth = FakeAuth([])
    checks = doctor(repo.root, auth=auth, credential=lambda: credential_of(home), launchd_job=True, now=NOW)
    [check] = [c for c in checks if c.name == "claude auth"]
    assert check.status == "FAIL" and str(path) in check.detail and auth.asked == 0
    path.chmod(0o600)
    auth = FakeAuth([ClaudeAuth(None, token=path)])
    checks = doctor(repo.root, auth=auth, credential=lambda: credential_of(home), launchd_job=True, now=NOW)
    assert [c.status for c in checks if c.name == "claude auth"] == ["PASS", "PASS"]
    assert auth.tokens[0] is not None and auth.tokens[0].value == SENTINEL  # the preflight got the token


# S-035-17


def test_s035_17_the_docs_and_the_setup_skill_name_the_token_steps() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in ("docs/install.md", "docs/design/agent-modes.md", "skills/shipmill-setup/SKILL.md"):
        text = " ".join((root / name).read_text(encoding="utf-8").split())
        for needed in ("claude setup-token", "~/.config/shipmill/claude-token", "`600`", "--claude-token"):
            assert needed in text, (name, needed)
        assert "never goes in the plist or the repo" in text, name
    skill = " ".join((root / "skills/shipmill-setup/SKILL.md").read_text(encoding="utf-8").split())
    assert "Tell the person to run `claude setup-token` themselves" in skill
    assert "Never run `claude setup-token` yourself" in skill


# S-035-18


def test_s035_18_a_token_file_drops_the_api_key_and_auth_token_from_sessions_and_the_preflight(
    checkout: Git, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    token_file(home)
    environ = {**GATE_ENV, "ANTHROPIC_API_KEY": "sk-ant-api03-x", "ANTHROPIC_AUTH_TOKEN": "bearer-y"}
    preflights: list[dict[str, str]] = []

    def run_in(cmd: list[str], env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
        preflights.append(dict(env))
        return subprocess.CompletedProcess(cmd, 0, LOGGED_IN, "")

    def unasked(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("with a token the preflight never runs in the gate's own env")

    envs: list[dict[str, str]] = []
    for config in (headless, interactive):
        runner = Launcher()
        decision, _, waiting, pruned = gate(
            checkout,
            REPO,
            config,
            runner.claude(environ),
            Reads(),
            NOW,
            Hold,
            FakeNotifier(),
            NO_PRUNE,
            login=lambda: LOGIN,
            started=lambda pid: None,
            new_session=lambda: SESSION,
            auth=preflight_auth(environ, "/bin/claude", unasked, run_in),
            credential=lambda: credential_of(home),
        )
        assert decision.action is Action.LAUNCH
        envs += [env for _, env in runner.spawned] + [env for _, env in runner.run_in_calls]
        (state_dir(checkout) / RECORD).unlink()
    assert len(envs) == 2 and len(preflights) == 2
    for env in envs + preflights:
        assert env[OAUTH] == SENTINEL and not set(OUTRANKING) & set(env)
    # without a token file both keys pass through unchanged (spec 035, Behaviour)
    assert Token(home, SENTINEL, NOW).env(environ).keys() & set(OUTRANKING) == set()
    plain = Launcher()
    plain.claude(environ).start(tmp_path, "n", "p", uuid.UUID(int=1), tmp_path / "s.log")
    assert set(OUTRANKING) <= set(plain.spawned[0][1])
