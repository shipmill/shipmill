"""Spec 048, The GitHub preflight: a launch first asks whether the identity a session writes
with reaches the repo, and a failing App check reads GITHUB_AUTH with its fix. Never GitHub:
a fake API answers the App's calls and a fake runner answers `gh api repos/<repo>`"""

import datetime as dt
import json
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig, Mode
from shipmill.app import CACHE, Answer, Identity, app_check, install_fix
from shipmill.autonomy import Hold
from shipmill.claude_auth import ClaudeAuth
from shipmill.claude_token import Token
from shipmill.cli import _gate_exit
from shipmill.errors import ReleaseError
from shipmill.gate import (
    RECORD,
    Action,
    Decision,
    Finding,
    Launch,
    StateRead,
    fingerprint,
    gate,
    save_launch,
    state_dir,
)
from shipmill.github_auth import HOST_FIX, GitHubAuth, github_auth, host_reach
from shipmill.gitrepo import Git
from shipmill.walk import CURSOR, HANDED

from .test_app import APP_ID, BOT, REPO, FakeApi, FakeSigner, key_file
from .test_gate import ISSUES, NO_PRUNE, NOW, FakeClaude, FakeNotifier, bg
from .test_gate_app import Prepared, gh_path
from .test_gate_headless import LOGIN, STARTED, Reads, checkout, unread

__all__ = ["checkout"]  # the fixture, imported for the tests below

ACCESS = "/app/installations/77/access_tokens"
SECRET = "ghs_not-a-real-token"
REPO_PATH = f"/repos/{REPO}"
GH_REPO = ["gh", "api", f"repos/{REPO}"]
LOGGED_IN = ClaudeAuth(None)
LOGGED_OUT = ClaudeAuth("claude auth status says not logged in")


def minted() -> Answer:
    expires = (NOW + dt.timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    return Answer(201, json.dumps({"token": SECRET, "expires_at": expires, "repositories": [{"full_name": REPO}]}))


@dataclass
class ReachApi(FakeApi):
    """FakeApi that also mints the session's token and answers the repo read, each call in events"""

    events: list[str] = field(default_factory=list)
    app: Answer | None = None  # GET /app's answer instead of the App's slug
    found: Answer | None = None  # the installation's answer instead of FakeApi's
    mint: Answer = field(default_factory=minted)
    repo: Answer = field(default_factory=lambda: Answer(200, json.dumps({"full_name": REPO})))

    def get(self, path: str, token: str | None) -> Answer:
        self.events.append(f"GET {path}")
        if path == "/app" and self.app is not None:
            self.calls.append((path, token))
            return self.app
        if path == f"{REPO_PATH}/installation" and self.found is not None:
            self.calls.append((path, token))
            return self.found
        if path == REPO_PATH:
            self.calls.append((path, token))
            return self.repo
        return super().get(path, token)

    def post(self, path: str, token: str, body: Mapping[str, object]) -> Answer:
        self.events.append(f"POST {path}")
        if path != ACCESS:
            raise AssertionError(f"unexpected POST {path}")
        return self.mint


@dataclass
class HostGh:
    """`gh api repos/<repo>` as the host's login, answered with code and stderr"""

    events: list[str]
    claude: FakeClaude
    code: int = 0
    stderr: str = ""
    before: list[int] = field(default_factory=list)  # sessions started or launched when it ran

    def __call__(self, cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        self.events.append(" ".join(cmd))
        self.before.append(len(self.claude.started) + len(self.claude.launched))
        return subprocess.CompletedProcess(cmd, self.code, '{"full_name": "romamo/demo"}', self.stderr)


def no_host(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    raise AssertionError(f"{cmd} ran: with an App the preflight never reads as the host's login (D-14)")


def auth_of(events: list[str], answer: ClaudeAuth = LOGGED_IN) -> Callable[[Token | None], ClaudeAuth]:
    def ask(token: Token | None) -> ClaudeAuth:
        events.append("claude auth status")
        return answer

    return ask


def unasked_auth(token: Token | None) -> ClaudeAuth:
    raise AssertionError("claude auth status ran")


def unasked_github(identity: Identity | None) -> GitHubAuth:
    raise AssertionError("the GitHub preflight ran")


def config(mode: Mode, app_id: int | None) -> AgentsConfig:
    return AgentsConfig(prompt="/t", prs=False, retry_hours=24, app_id=app_id, mode=mode)


def tick(
    git: Git,
    tmp_path: Path,
    agents: AgentsConfig,
    claude: FakeClaude,
    github: Callable[[Identity | None], GitHubAuth],
    auth: Callable[[Token | None], ClaudeAuth],
    api: FakeApi | None = None,
    reads: Callable[[StateRead], list[Finding]] | None = None,
    hold: Callable[[], Hold] = Hold,
    dry_run: bool = False,
    key_mode: int = 0o600,
) -> Decision:
    check = app_check(REPO, key_file(tmp_path, key_mode), tmp_path, FakeSigner(), api or ReachApi())
    decision, _, _, _ = gate(
        git,
        REPO,
        lambda: agents,
        claude,
        Reads() if reads is None else reads,
        NOW,
        hold,
        FakeNotifier(),
        NO_PRUNE,
        dry_run=dry_run,
        app=check,
        app_env=Prepared(git, gh_path(tmp_path)),
        login=lambda: LOGIN,
        started=lambda pid: STARTED,
        auth=auth,
        github=github,
    )
    return decision


def nothing_walked(git: Git) -> bool:
    """No cursor.json or handed.json: the next tick walks again (S-046-11)"""
    return not (state_dir(git) / CURSOR).exists() and not (state_dir(git) / HANDED).exists()


# S-048-1


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("mode", [Mode.HEADLESS, Mode.INTERACTIVE])
def test_s048_1_a_launch_as_the_app_mints_a_token_and_reads_the_repo_with_it(
    checkout: Git, tmp_path: Path, mode: Mode, dry_run: bool
) -> None:
    events: list[str] = []
    api = ReachApi(events=events)
    preflight = github_auth(REPO, checkout.root, FakeSigner(), api, run=no_host, clock=lambda: NOW)
    claude = FakeClaude()
    decision = tick(checkout, tmp_path, config(mode, APP_ID), claude, preflight, auth_of(events), api, dry_run=dry_run)
    assert decision.action is Action.LAUNCH and decision.github == GitHubAuth(None)
    assert len(claude.started) + len(claude.launched) == (0 if dry_run else 1)
    # the App check, then the Claude Code preflight, then the mint and the repo read with its token
    after = events[events.index("claude auth status") + 1 :]
    assert after[-2:] == [f"POST {ACCESS}", f"GET {REPO_PATH}"]
    assert (REPO_PATH, SECRET) in api.calls
    assert not (state_dir(checkout) / CACHE).exists()  # mint, never app_token: no cache, dry run or not


def test_s048_1_a_failing_claude_code_preflight_asks_github_nothing(checkout: Git, tmp_path: Path) -> None:
    claude = FakeClaude()
    decision = tick(checkout, tmp_path, config(Mode.HEADLESS, APP_ID), claude, unasked_github, auth_of([], LOGGED_OUT))
    assert decision.action is Action.CLAUDE_AUTH


# S-048-2


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("mode", [Mode.HEADLESS, Mode.INTERACTIVE])
def test_s048_2_a_launch_without_an_app_reads_the_repo_as_the_hosts_login_first(
    checkout: Git, tmp_path: Path, mode: Mode, dry_run: bool
) -> None:
    events: list[str] = []
    claude = FakeClaude()
    gh = HostGh(events, claude)
    preflight = github_auth(REPO, checkout.root, FakeSigner(), ReachApi(), run=gh)
    decision = tick(checkout, tmp_path, config(mode, None), claude, preflight, auth_of(events), dry_run=dry_run)
    assert decision.action is Action.LAUNCH
    assert events == ["claude auth status", " ".join(GH_REPO)]
    assert gh.before == [0]  # before any session started
    assert len(claude.started) + len(claude.launched) == (0 if dry_run else 1)


# S-048-3


def launch_failing(git: Git, tmp_path: Path, api: ReachApi, app_id: int | None, gh: HostGh | None = None) -> Decision:
    claude = gh.claude if gh is not None else FakeClaude([bg("old", "idle", "done")])
    preflight = github_auth(REPO, git.root, FakeSigner(), api, run=gh or no_host, clock=lambda: NOW)
    decision = tick(git, tmp_path, config(Mode.HEADLESS, app_id), claude, preflight, auth_of([]), api)
    assert (claude.started, claude.launched, claude.stopped) == ([], [], [])  # starts none, stops none
    assert nothing_walked(git) and not (state_dir(git) / RECORD).exists()
    assert (decision.stop, decision.identity, _gate_exit(decision)) == ((), None, 2)
    return decision


@pytest.mark.parametrize(
    ("api", "problem", "fix"),
    [
        (
            ReachApi(mint=Answer(401, '{"message": "A JSON web token could not be decoded"}')),
            f"GitHub refused the JWT for app_id {APP_ID} (POST {ACCESS}: 401"
            ' {"message": "A JSON web token could not be decoded"})',
            f"set the host's clock (`sntp -sS time.apple.com`), or use App {APP_ID}'s own private key",
        ),
        (
            ReachApi(mint=Answer(422, '{"message": "Validation Failed"}')),
            f'POST {ACCESS} for app_id {APP_ID} answered 422: {{"message": "Validation Failed"}}',
            install_fix(REPO),
        ),
        (
            ReachApi(repo=Answer(404, '{"message": "Not Found"}')),
            f'the token of {BOT} can\'t read {REPO} (GET {REPO_PATH} answered 404: {{"message": "Not Found"}})',
            install_fix(REPO),
        ),
    ],
)
def test_s048_3_a_failed_mint_or_repo_read_is_github_auth_with_the_tables_fix(
    checkout: Git, tmp_path: Path, api: ReachApi, problem: str, fix: str
) -> None:
    decision = launch_failing(checkout, tmp_path, api, APP_ID)
    assert decision.action is Action.GITHUB_AUTH
    assert decision.reason == f"{problem}: no session starts; fix: {fix}"
    assert decision.github == GitHubAuth(problem, fix)
    assert SECRET not in decision.reason


def test_s048_3_a_host_login_that_cant_read_the_repo_is_github_auth(checkout: Git, tmp_path: Path) -> None:
    gh = HostGh([], FakeClaude([bg("old", "idle", "done")]), 1, "gh: Not Found (HTTP 404)\nmore")
    decision = launch_failing(checkout, tmp_path, ReachApi(), None, gh)
    assert decision.reason == (
        f"the host's gh login can't read {REPO} (gh api repos/{REPO} exited 1: gh: Not Found (HTTP 404)):"
        f" no session starts; fix: {HOST_FIX}"
    )


def test_s048_3_gh_missing_is_an_error_not_a_verdict(tmp_path: Path) -> None:
    def missing(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(cmd[0])

    with pytest.raises(ReleaseError, match="gh is not on PATH"):
        host_reach(REPO, tmp_path, missing)


# S-048-4


def installation_of(**extra: object) -> Answer:
    granted = {"contents": "write", "metadata": "read"}
    return Answer(200, json.dumps({"id": 77, "permissions": granted, **extra}))


@pytest.mark.parametrize(
    ("mode", "api", "problem", "fix"),
    [
        (
            None,
            ReachApi(app=Answer(401, '{"message": "Bad credentials"}')),
            f'GitHub refused the JWT for app_id {APP_ID} (GET /app: 401 {{"message": "Bad credentials"}})',
            f"set the host's clock (`sntp -sS time.apple.com`), or use App {APP_ID}'s own private key",
        ),
        (None, ReachApi(installed=False), f"app demo-agent is not installed on {REPO}", install_fix(REPO)),
        (
            None,
            ReachApi(found=Answer(200, json.dumps({"id": 77, "suspended_at": "2026-10-01T00:00:00Z"}))),
            f"app demo-agent's installation on {REPO} is suspended",
            install_fix(REPO),
        ),
        (
            None,
            ReachApi(found=installation_of(html_url="https://github.com/settings/installations/77")),
            f"app demo-agent on {REPO} lacks these permissions: Pull requests: write, Issues: write,"
            " Actions: write, Workflows: write, Checks: read, Commit statuses: read, Discussions: read",
            "grant them in the App's settings, then accept them at https://github.com/settings/installations/77",
        ),
        (0o644, ReachApi(), "the App private key {key} is readable by group or others", "chmod 600 {key}"),
    ],
)
def test_s048_4_a_failed_app_check_is_github_auth_and_reads_no_state(
    checkout: Git, tmp_path: Path, mode: int | None, api: ReachApi, problem: str, fix: str
) -> None:
    claude = FakeClaude([bg("old", "idle", "done")])
    agents = config(Mode.HEADLESS, APP_ID)
    decision = tick(
        checkout, tmp_path, agents, claude, unasked_github, unasked_auth, api, unread, key_mode=mode or 0o600
    )
    key = tmp_path / "app.pem"
    problem, fix = problem.replace("{key}", str(key)), fix.replace("{key}", str(key))
    # unread raises: no watch_state.py and no change check, which runs inside the state read
    assert decision.action is Action.GITHUB_AUTH
    assert decision.reason == f"{problem}: no session starts; fix: {fix}"
    assert (claude.started, claude.launched, claude.stopped) == ([], [], [])
    assert nothing_walked(checkout) and _gate_exit(decision) == 2


def test_s048_4_a_missing_key_names_its_path_and_app_create(checkout: Git, tmp_path: Path) -> None:
    home = tmp_path / "home"
    check = app_check(REPO, None, home, FakeSigner(), ReachApi())
    decision, *_ = gate(
        checkout,
        REPO,
        lambda: config(Mode.INTERACTIVE, APP_ID),
        FakeClaude(),
        unread,
        NOW,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        app=check,
        auth=unasked_auth,
        github=unasked_github,
    )
    key = home / ".config" / "shipmill" / f"app-{APP_ID}.pem"
    assert decision.action is Action.GITHUB_AUTH
    assert decision.reason.startswith(f"no App private key at {key}: no session starts; fix: download")
    assert decision.reason.endswith(" app-create`")


# S-048-5


@pytest.mark.parametrize("app_id", [None, APP_ID])
@pytest.mark.parametrize("action", [Action.QUIET, Action.UNCHANGED, Action.RUNNING, Action.WAITING, Action.HELD])
def test_s048_5_a_tick_that_launches_nothing_runs_neither_preflight(
    checkout: Git, tmp_path: Path, app_id: int | None, action: Action
) -> None:
    api = FakeApi()  # raises on a POST and on any GET but the App check's: no mint, no repos/<repo>
    preflight = github_auth(REPO, checkout.root, FakeSigner(), api, run=no_host)
    claude, reads, hold = FakeClaude(), Reads(), Hold()
    if action is Action.QUIET:
        reads = Reads(rows=[])
    elif action is Action.UNCHANGED:
        launch = Launch(fingerprint([ISSUES]), "s0", NOW - dt.timedelta(hours=1))
        save_launch(state_dir(checkout) / RECORD, launch)
    elif action is Action.RUNNING:
        claude = FakeClaude([bg("a", "busy", "working")])
    elif action is Action.WAITING:
        claude = FakeClaude([bg("w", "idle", "blocked")])
    else:
        hold = Hold(("#5 hold",))
    decision = tick(
        checkout, tmp_path, config(Mode.INTERACTIVE, app_id), claude, preflight, unasked_auth, api, reads, lambda: hold
    )
    assert decision.action is action and decision.github is None
    assert all(not (path == REPO_PATH or path.endswith("/access_tokens")) for path, _ in api.calls)
    assert not (state_dir(checkout) / CACHE).exists()
