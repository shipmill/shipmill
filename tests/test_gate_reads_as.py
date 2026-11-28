"""Spec 093: a gate tick's own GitHub reads (the hold check, the change check, the subjects'
updatedAt and waits-on markers, each tier and the sweep) run with GH_TOKEN the tick's read token
in the environment of that one command, never the gate's own; `gh api user` and the sessions
never get it; tick.json and `shipmill gate --json` record reads_as (S-093-1 to S-093-3, S-093-8
to S-093-13). No test reaches the network: GitHub is TickApi, and gh a stand-in"""

import datetime as dt
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill import cli
from shipmill.agents import AgentsConfig, Mode
from shipmill.autonomy import Hold
from shipmill.claude_token import Credential
from shipmill.cli import _gate_exit
from shipmill.errors import ReleaseError
from shipmill.gate import (
    ERROR,
    TICK,
    Action,
    ClaudeCli,
    Decision,
    Finding,
    StateRead,
    TickRecord,
    gate,
    host_login,
    load_tick,
    run_command,
    run_state,
    save_tick,
    state_dir,
    tick_hold,
    tick_lines,
    tick_record,
    tick_state,
)
from shipmill.gitrepo import Git
from shipmill.tick_read import AS_APP, NO_APP, WITHOUT_APP, Reader, ReadsAs, TickReads, settle

from .test_app import FakeSigner, key_file
from .test_gate import ISSUES, NO_PRUNE, NOW, FakeClaude, FakeNotifier, cfg, checkout, host
from .test_gate_walk import graphql_answer
from .test_tick_read import WITH_APP, TickApi

__all__ = ["checkout"]  # the fixture, imported for the tests below

REPO = "romamo/demo"
TOKEN = "ghs_tick-read-token-not-real"
BOT = "demo-agent[bot]"
RUNS = f"repos/{REPO}/actions/workflows/release-bot.yml/runs?per_page=10"
LATER = NOW + dt.timedelta(minutes=15)


def as_app() -> tuple[ReadsAs, str | None]:
    return AS_APP, TOKEN


def as_host() -> tuple[ReadsAs, str | None]:
    return WITHOUT_APP, None


@dataclass
class Gh:
    """gh as WatchState runs it, recording each command's env: the change check's query, each
    workflow's runs, the subjects' updatedAt, and the waits-on markers' comments"""

    seen: list[tuple[str, Mapping[str, str] | None]] = field(default_factory=list)

    def __call__(self, cmd: list[str], cwd: Path, env: Mapping[str, str] | None) -> str:
        if cmd[:3] == ["gh", "api", "graphql"]:
            query = next(a for a in cmd if a.startswith("query="))
            if "comments(last: 50)" in query:
                self.seen.append(("waited", env))
                return json.dumps({"data": {"repository": {"i3": {"comments": {"nodes": []}}}}})
            if "i3: issueOrPullRequest" in query:
                self.seen.append(("issues", env))
                return json.dumps({"data": {"repository": {"i3": {"updatedAt": "2026-10-04T11:00:00Z"}}}})
            self.seen.append(("changes", env))
            return json.dumps(graphql_answer())
        if cmd[:2] == ["gh", "api"] and cmd[2] == RUNS:
            self.seen.append(("runs", env))
            return json.dumps({"workflow_runs": []})
        raise AssertionError(f"unexpected gh {cmd}")


@dataclass
class State:
    """watch_state.py as WatchState runs a tier or the sweep, recording each one's env"""

    seen: list[tuple[str, Mapping[str, str] | None]] = field(default_factory=list)

    def __call__(self, cmd: list[str], env: Mapping[str, str] | None) -> subprocess.CompletedProcess[str]:
        what = "sweep" if "--sweep" in cmd else f"tier {cmd[cmd.index('--tier') + 1]}"
        self.seen.append((what, env))
        return subprocess.CompletedProcess(cmd, 0, "", "")


@dataclass
class Issues:
    """GhCli as the hold check builds it, recording the env it was given"""

    envs: list[Mapping[str, str] | None] = field(default_factory=list)

    def __call__(self, root: Path, env: Mapping[str, str] | None) -> Issues:
        self.envs.append(env)
        return self

    def open_issues(self, label: str) -> list[str]:
        return []


def watched(root: Path) -> Path:
    """A checkout whose change check reads one workflow's runs, the release bot's"""
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / ".github" / "shipmill.toml").write_text('mode = "off"\n', encoding="utf-8")
    (root / ".github" / "workflows" / "release-bot.yml").write_text("on: push\n", encoding="utf-8")
    return root


def all_reads(reads: TickReads, root: Path, state: Path) -> tuple[Gh, State]:
    gh, run = Gh(), State()
    source = tick_state(REPO, root, state, NOW, reads, gh, run)(StateRead(bot_login=BOT))
    changes = source.changes(NOW - dt.timedelta(hours=1))
    source.issues([3])
    source.waited([3])
    source.tier(1, changes)
    source.sweep(changes)
    return gh, run


# -- S-093-1 ---------------------------------------------------------------------------------


def test_s093_1_the_change_check_and_subject_reads_run_with_the_read_token(tmp_path: Path) -> None:
    host_env = dict(os.environ)
    gh, _ = all_reads(TickReads(as_app), watched(tmp_path), tmp_path / "state")
    assert [what for what, _ in gh.seen] == ["changes", "runs", "issues", "waited"]
    for what, env in gh.seen:
        assert env is not None and env["GH_TOKEN"] == TOKEN, what
        assert {k: v for k, v in env.items() if k != "GH_TOKEN"} == {
            k: v for k, v in host_env.items() if k != "GH_TOKEN"
        }
    assert dict(os.environ) == host_env


def test_s093_1_the_hold_check_runs_with_the_read_token(tmp_path: Path) -> None:
    issues = Issues()
    assert tick_hold(tmp_path, TickReads(as_app), issues)() == Hold()
    [env] = issues.envs
    assert env is not None and env["GH_TOKEN"] == TOKEN


def test_s093_1_gh_itself_gets_the_token_in_its_env_and_the_gates_keeps_none(tmp_path: Path) -> None:
    """The real GhCli and run_command, a stand-in gh that writes the GH_TOKEN it got"""
    tools = tmp_path / "tools"
    tools.mkdir()
    seen = tmp_path / "seen"
    gh = tools / "gh"
    gh.write_text(f'#!/bin/sh\nprintf "%s\\n" "$GH_TOKEN" >> "{seen}"\necho "[]"\n', encoding="utf-8")
    gh.chmod(0o755)
    environ = {"PATH": os.pathsep.join([str(tools), "/usr/bin", "/bin"])}
    reads = TickReads(as_app, environ)
    before = dict(os.environ)
    assert tick_hold(tmp_path, reads)() == Hold()
    assert run_command(["gh", "api", "graphql"], tmp_path, reads.env()) == "[]\n"
    assert seen.read_text(encoding="utf-8").splitlines() == [TOKEN, TOKEN]
    assert dict(os.environ) == before


# -- S-093-2 ---------------------------------------------------------------------------------


def test_s093_2_each_tier_and_the_sweep_get_the_read_token(tmp_path: Path) -> None:
    _, run = all_reads(TickReads(as_app), watched(tmp_path), tmp_path / "state")
    assert [what for what, _ in run.seen] == ["tier 1", "sweep"]
    assert all(env is not None and env["GH_TOKEN"] == TOKEN for _, env in run.seen)


def test_s093_2_watch_state_and_the_scripts_it_runs_inherit_the_env_given() -> None:
    """run_state's subprocess gets env whole; a child it starts in turn inherits it"""
    grandchild = "import os; print(os.environ['GH_TOKEN'])"
    child = f"import subprocess, sys; subprocess.run([sys.executable, '-c', {grandchild!r}])"
    done = run_state([sys.executable, "-c", child], {**os.environ, "GH_TOKEN": TOKEN})
    assert (done.returncode, done.stdout) == (0, f"{TOKEN}\n")
    assert os.environ.get("GH_TOKEN") != TOKEN


# -- S-093-3 ---------------------------------------------------------------------------------


@dataclass
class Bg:
    """ClaudeCli's runner for an interactive tick, and host_login's, recording os.environ at each
    call: `gh api user`, `claude agents`, and `claude --bg` run in the gate's own environment"""

    seen: list[tuple[str, str | None]] = field(default_factory=list)

    def __call__(self, cmd: list[str], cwd: Path) -> str:
        self.seen.append((" ".join(cmd[:3]), os.environ.get("GH_TOKEN")))
        if cmd[:3] == ["gh", "api", "user"]:
            return "amy\n"
        if cmd[:2] == ["claude", "agents"]:
            return "[]"
        if cmd[:2] == ["claude", "--bg"]:
            assert not any(TOKEN in arg for arg in cmd)
            return "started; claude attach s9\n"
        raise AssertionError(f"unexpected command {cmd}")


@pytest.mark.parametrize("settled", [as_app, as_host], ids=["as the app", "as the host"])
def test_s093_3_gh_api_user_and_the_session_run_without_the_token_and_os_environ_is_unchanged(
    checkout: Git, settled: Callable[[], tuple[ReadsAs, str | None]]
) -> None:
    before = dict(os.environ)
    reads = TickReads(settled)
    issues = Issues()
    used: list[Mapping[str, str] | None] = []

    def findings(read: StateRead) -> list[Finding]:
        used.append(reads.env())
        return [ISSUES]

    runner = Bg()
    decision, launched, _, _ = gate(
        checkout,
        REPO,
        cfg,
        ClaudeCli(run=runner),
        findings,
        NOW,
        tick_hold(checkout.root, reads, issues),
        FakeNotifier(),
        NO_PRUNE,
        login=lambda: host_login(checkout.root, runner),
        reads=reads,
    )
    assert (decision.action, launched) == (Action.LAUNCH, "s9")
    assert [what for what, _ in runner.seen] == ["claude agents --json", "gh api user", "claude --bg -n"]
    assert all(token != TOKEN for _, token in runner.seen)
    assert dict(os.environ) == before
    token = TOKEN if settled is as_app else None
    assert [None if e is None else e.get("GH_TOKEN") for e in [*issues.envs, *used]] == [token, token]
    assert TOKEN not in json.dumps(json.loads((state_dir(checkout) / TICK).read_text(encoding="utf-8")))


def test_s093_3_a_headless_session_starts_without_the_token(checkout: Git) -> None:
    started: list[tuple[list[str], Mapping[str, str]]] = []

    def spawn(cmd: list[str], cwd: Path, log: Path, env: Mapping[str, str]) -> int:
        started.append((cmd, env))
        return os.getpid()

    reads = TickReads(as_app)

    def findings(read: StateRead) -> list[Finding]:
        reads.env()
        return [ISSUES]

    headless = AgentsConfig(prompt="/t", prs=False, retry_hours=24, mode=Mode.HEADLESS)
    claude = ClaudeCli(run=Bg(), spawn=spawn)
    decision, launched, _, _ = gate(
        checkout, REPO, lambda: headless, claude, findings, NOW, Hold, FakeNotifier(), NO_PRUNE, login=host, reads=reads
    )
    assert decision.action is Action.LAUNCH and launched is not None
    [(cmd, env)] = started
    assert env.get("GH_TOKEN") != TOKEN and not any(TOKEN in arg for arg in cmd)


# -- S-093-8 ---------------------------------------------------------------------------------


def test_s093_8_without_app_id_the_reads_keep_the_gates_env_and_record_why(checkout: Git, tmp_path: Path) -> None:
    api = TickApi()
    reads = TickReads(
        settle(checkout.root, REPO, state_dir(checkout), None, tmp_path, lambda: NOW, FakeSigner(), api, True)
    )
    gh, run = all_reads(reads, watched(checkout.root), state_dir(checkout))
    assert [env for _, env in gh.seen + run.seen] == [None] * 6  # None: the gate's own env, nothing added
    assert api.calls == [] and api.posts == []
    assert reads.reads_as == ReadsAs(Reader.HOST, "no [agents] app_id")
    decision = tick(checkout, reads)
    assert written(checkout)["reads_as"] == {"identity": "host", "why": "no [agents] app_id"}
    assert "reads as" not in tick_lines(decision, None, (), (), dry_run=False)[0]


# -- S-093-9 ---------------------------------------------------------------------------------


def app_checkout(root: Path) -> Git:
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    git = Git(root)
    git.run("remote", "add", "origin", f"https://github.com/{REPO}.git")
    (root / ".github").mkdir()
    (root / ".github" / "shipmill.toml").write_text(WITH_APP, encoding="utf-8")
    return git


def tick(
    git: Git,
    reads: TickReads,
    findings: Callable[[StateRead], Sequence[Finding]] | None = None,
    credential: Callable[[], Credential] | None = None,
) -> Decision:
    """A real tick whose hold check and findings read through reads, as the CLI's do"""

    def read_issues(read: StateRead) -> list[Finding]:
        reads.env()
        return [ISSUES]

    decision, _, _, _ = gate(
        git,
        REPO,
        cfg,
        FakeClaude(),
        read_issues if findings is None else findings,
        NOW,
        tick_hold(git.root, reads, Issues()),
        FakeNotifier(),
        NO_PRUNE,
        login=host,
        credential=credential,
        reads=reads,
    )
    return decision


def written(git: Git) -> dict[str, object]:
    found = json.loads((state_dir(git) / TICK).read_text(encoding="utf-8"))
    assert isinstance(found, dict)
    return found


def test_s093_9_a_failed_mint_reads_as_the_host_with_the_same_decision_and_exit(tmp_path: Path) -> None:
    failed = app_checkout(tmp_path / "failed")
    api = TickApi()
    missing = tmp_path / "missing.pem"
    reads = TickReads(
        settle(failed.root, REPO, state_dir(failed), missing, tmp_path, lambda: NOW, FakeSigner(), api, True)
    )
    decision = tick(failed, reads)
    why = f"no App private key at {missing}; download it from the App's settings to that path"
    assert reads.reads_as == ReadsAs(Reader.HOST, why) and reads.env() is None
    assert api.posts == []
    hosted = app_checkout(tmp_path / "hosted")
    same = tick(hosted, TickReads(as_host))
    assert (decision.action, decision.reason, _gate_exit(decision)) == (same.action, same.reason, _gate_exit(same))
    assert written(failed)["reads_as"] == {"identity": "host", "why": why}
    assert tick_lines(decision, "s1", (), (), dry_run=False)[0].endswith(f"; reads as host: {why}")
    assert "reads as" not in tick_lines(same, "s1", (), (), dry_run=False)[0]  # no App: the line as before


def test_s093_9_a_product_of_another_owner_reads_as_the_host_naming_it(tmp_path: Path) -> None:
    git = app_checkout(tmp_path / "home")
    config = git.root / ".github" / "shipmill.toml"
    config.write_text(WITH_APP + '\n[product]\nrepos = ["other/web"]\n', encoding="utf-8")
    api = TickApi()
    key = key_file(tmp_path)
    reads = TickReads(settle(git.root, REPO, state_dir(git), key, tmp_path, lambda: NOW, FakeSigner(), api, True))
    assert reads.env() is None and api.calls == []
    assert reads.reads_as == ReadsAs(Reader.HOST, "the product lists other/web of another owner")


def test_s093_9_a_malformed_tick_cache_is_no_failed_mint_and_ends_the_tick_error(tmp_path: Path) -> None:
    """Q-1, as S-004-8's app-token.json: a malformed app-token-tick.json stops the tick naming its
    path, rather than reading as the host on every tick while the file stays as it is"""
    git = app_checkout(tmp_path / "demo")
    state_dir(git).mkdir(parents=True, exist_ok=True)
    (state_dir(git) / "app-token-tick.json").write_text("{", encoding="utf-8")
    api = TickApi(now=NOW)
    key = key_file(tmp_path)
    reads = TickReads(settle(git.root, REPO, state_dir(git), key, tmp_path, lambda: NOW, FakeSigner(), api, True))
    with pytest.raises(ReleaseError, match="app-token-tick.json"):
        tick(git, reads)
    assert api.posts == [] and written(git)["action"] == ERROR


# -- S-093-10 --------------------------------------------------------------------------------


def test_s093_10_a_minted_token_records_reads_as_app_and_no_reads_as_on_the_line(tmp_path: Path) -> None:
    git = app_checkout(tmp_path / "demo")
    api = TickApi(now=NOW)
    key = key_file(tmp_path)
    reads = TickReads(settle(git.root, REPO, state_dir(git), key, tmp_path, lambda: NOW, FakeSigner(), api, True))
    decision = tick(git, reads)
    assert reads.reads_as == AS_APP and api.minted() == [["demo"]]
    env = reads.env()
    assert env is not None and env["GH_TOKEN"] == "token-1"
    assert written(git)["reads_as"] == {"identity": "app", "why": None}
    assert tick_record(decision, "s1", (), (), dry_run=False)["reads_as"] == {"identity": "app", "why": None}
    assert "reads as" not in tick_lines(decision, "s1", (), (), dry_run=False)[0]
    assert "token-1" not in json.dumps(written(git)) and "token-1" not in repr(reads)


# -- S-093-11 --------------------------------------------------------------------------------


def test_s093_11_a_failed_read_as_the_app_ends_the_tick_error_and_is_not_read_as_the_host(checkout: Git) -> None:
    reads = TickReads(as_app)
    envs: list[Mapping[str, str] | None] = []

    def limited(read: StateRead) -> Sequence[Finding]:
        envs.append(reads.env())
        raise ReleaseError("gh api graphql failed: API rate limit already exceeded for installation ID 55")

    with pytest.raises(ReleaseError, match="rate limit"):
        tick(checkout, reads, findings=limited)
    assert len(envs) == 1 and envs[0] is not None and envs[0]["GH_TOKEN"] == TOKEN  # read once, as the App
    record = written(checkout)
    assert (record["action"], record["reads_as"]) == (ERROR, {"identity": "app", "why": None})
    assert record["reason"] == "gh api graphql failed: API rate limit already exceeded for installation ID 55"


def test_s093_12_the_cli_records_null_for_an_error_before_any_read(checkout: Git, tmp_path: Path) -> None:
    """The CLI end to end: the checkout's origin is another repo, so the tick ends on its error,
    exit 2, as a failed read as the App ends it, and read nothing from GitHub"""
    env = {**os.environ, "HOME": str(tmp_path / "home")}
    command = [sys.executable, "-c", "from shipmill.cli import run; run()", "--repo", str(checkout.root)]
    done = subprocess.run([*command, "gate", "romamo/other"], capture_output=True, text=True, env=env)
    assert done.returncode == 2
    assert (written(checkout)["action"], written(checkout)["reads_as"]) == (ERROR, None)


# -- S-093-12 --------------------------------------------------------------------------------


def test_s093_12_a_tick_that_reads_nothing_records_reads_as_null(checkout: Git, tmp_path: Path) -> None:
    def unread() -> tuple[ReadsAs, str | None]:
        raise AssertionError("a CLAUDE_AUTH refusal reads nothing from GitHub")

    reads = TickReads(unread)
    refused = cli._credential(tmp_path / "missing-token", tmp_path)
    decision = tick(checkout, reads, credential=lambda: refused)
    assert decision.action is Action.CLAUDE_AUTH and reads.reads_as is None
    assert written(checkout)["reads_as"] is None
    assert tick_record(decision, None, (), (), dry_run=False)["reads_as"] is None


def test_s093_12_a_tick_json_without_reads_as_loads_as_null(tmp_path: Path) -> None:
    path = tmp_path / TICK
    old = {"at": NOW.isoformat(), "action": "QUIET", "reason": "r", "fix": None, "failing": None, "running": None}
    path.write_text(json.dumps(old | {"in_flight": None}), encoding="utf-8")
    found = load_tick(path)
    assert found is not None and found.reads_as is None
    for reads_as in (AS_APP, ReadsAs(Reader.HOST, NO_APP), None):
        record = TickRecord(LATER, "QUIET", "r", None, None, reads_as=reads_as)
        save_tick(path, record)
        assert load_tick(path) == record
    path.write_text(
        json.dumps(old | {"in_flight": None, "reads_as": {"identity": "bot", "why": None}}), encoding="utf-8"
    )
    with pytest.raises(ReleaseError, match="tick.json is malformed"):
        load_tick(path)


# -- S-093-13 --------------------------------------------------------------------------------


def test_s093_13_install_says_whose_budget_the_gates_reads_draw_on() -> None:
    text = (Path(__file__).resolve().parents[1] / "docs" / "install.md").read_text(encoding="utf-8")
    assert "The gate's own reads still use your `gh` login" not in text
    assert "the gate's own reads go as the App with a read-only token" in " ".join(text.split())
    assert "without one, as your `gh` login" in " ".join(text.split())
