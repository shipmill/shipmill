"""Spec 031: the gate loads the latest release per session from a versioned cache. The
marketplace read, PyPI, and the clone are faked; the cache is a real folder"""

import json
import subprocess
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig, Mode
from shipmill.autonomy import Hold
from shipmill.errors import ReleaseError
from shipmill.gate import (
    PLUGIN_REFUSED,
    Action,
    ClaudeCli,
    Decision,
    Waiting,
    gate,
    tick_lines,
    tick_record,
)
from shipmill.gitrepo import Git
from shipmill.hooks import HookTest
from shipmill.plugin import READ_MARKETPLACE
from shipmill.plugin_cache import PYPI_URL, PluginDir, cache_root, resolve
from shipmill.worktrees import Judged

from .test_gate import ISSUES, NO_PRUNE, NOW, FakeClaude, FakeNotifier, bg, host
from .test_hooks_selftest import PASSED, FakeSelfTest

LATEST = "0.59.0"
OLDER = "0.58.0"
CLONE = ["git", "clone", "--quiet", "--depth", "1", "--branch", f"v{LATEST}", "https://github.com/shipmill/shipmill"]
NAME = f"shipmill romamo/demo {NOW:%Y-%m-%d %H:%M}"
SESSION = uuid.UUID("0b8f3c52-6a3e-4d55-9a8e-6d1f3f0b2a11")
Tick = tuple[Decision, str | None, tuple[Waiting, ...], tuple[Judged, ...]]


def marketplace(version: str) -> str:
    source = {"source": "github", "repo": "shipmill/shipmill", "ref": f"v{version}"}
    return json.dumps({"name": "shipmill", "plugins": [{"name": "shipmill", "source": source}]})


def plugin_folder(folder: Path, version: str, marker: str = "") -> Path:
    """A plugin's files: its .claude-plugin/plugin.json holding version, and a marker file"""
    (folder / ".claude-plugin").mkdir(parents=True)
    (folder / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "shipmill", "version": version}))
    (folder / "marker").write_text(marker)
    return folder


@dataclass
class FakeHost:
    """`gh api` for the marketplace and `git clone` of a tag. tagged is the version the tag's
    plugin.json holds; rival renames another gate's copy into the cache while this one clones"""

    latest: str = LATEST
    tagged: str | None = None
    marketplace_error: str | None = None
    clone_error: str | None = None
    rival: bool = False
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, cmd: list[str], cwd: Path) -> str:
        self.calls.append(cmd)
        if cmd[:2] == ["gh", "api"]:
            assert cmd == READ_MARKETPLACE
            if self.marketplace_error is not None:
                raise ReleaseError(self.marketplace_error)
            return marketplace(self.latest)
        if cmd[:2] == ["git", "clone"]:
            if self.clone_error is not None:
                raise ReleaseError(self.clone_error)
            dest = Path(cmd[-1])
            assert dest.is_dir() and not any(dest.iterdir())  # an empty temporary folder
            plugin_folder(dest, self.tagged or self.latest, "ours")
            (dest / ".git").mkdir()
            (dest / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
            if self.rival:
                plugin_folder(cwd / self.latest, self.latest, "rival")
            return ""
        raise AssertionError(f"unexpected command {cmd}")

    @property
    def clones(self) -> list[list[str]]:
        return [c for c in self.calls if c[:2] == ["git", "clone"]]


@dataclass
class FakePyPI:
    """PyPI's answers by version: a status, or an error raised as ReleaseError"""

    status: dict[str, int | str] = field(default_factory=lambda: {LATEST: 200, OLDER: 200})
    asked: list[str] = field(default_factory=list)

    def __call__(self, url: str) -> int:
        self.asked.append(url)
        version = url.split("/")[-2]
        answer = self.status.get(version, 404)
        if isinstance(answer, str):
            raise ReleaseError(answer)
        return answer


def cached(root: Path, version: str = OLDER) -> Path:
    return plugin_folder(root / version, version, "cached")


def leftovers(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir() if p.name.startswith(".tmp-"))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "shipmill" / "plugin"


@pytest.fixture
def checkout(tmp_path: Path) -> Git:
    folder = tmp_path / "demo"
    folder.mkdir()
    subprocess.run(["git", "init", "-q", str(folder)], check=True)
    git = Git(folder)
    git.run("remote", "add", "origin", "https://github.com/romamo/demo.git")
    return git


def tick(
    git: Git,
    claude: FakeClaude | ClaudeCli,
    cache: Callable[[], PluginDir] | None,
    mode: Mode = Mode.HEADLESS,
    tests: FakeSelfTest | None = None,
    dry_run: bool = False,
    env: Mapping[str, str] | None = None,
) -> Tick:
    agents = AgentsConfig(prompt="/t", prs=False, retry_hours=24, mode=mode)
    return gate(
        git,
        "romamo/demo",
        lambda: agents,
        claude,
        lambda _: [ISSUES],
        NOW,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        dry_run=dry_run,
        login=host,
        started=lambda pid: None,
        new_session=lambda: SESSION,
        hooks=tests,
        cache=cache,
    )


def resolver(root: Path, host_: FakeHost, pypi: FakePyPI, cwd: Path) -> Callable[[], PluginDir]:
    return lambda: resolve(root, host_, cwd, pypi)


# --- S-031-8: materialized once into the cache ----------------------------------------------


def test_s031_8_a_tick_clones_the_latest_tag_into_the_cache(root: Path, checkout: Git) -> None:
    host_, claude = FakeHost(), FakeClaude()
    decision, launched, waiting, pruned = tick(checkout, claude, resolver(root, host_, FakePyPI(), checkout.root))
    folder = root / LATEST
    assert decision.action is Action.LAUNCH and claude.plugin_dirs == [folder]
    [clone] = host_.clones
    temp = Path(clone[-1])
    assert clone[:-1] == CLONE and temp.parent == root and temp.name.startswith(".tmp-")
    assert (folder / "marker").read_text() == "ours" and not (folder / ".git").exists()
    assert leftovers(root) == []
    lines = tick_lines(decision, launched, waiting, pruned, dry_run=False)
    assert f"  plugin: cached {LATEST} in {folder}" in lines
    record = tick_record(decision, launched, waiting, pruned, dry_run=False)
    assert record["plugin_dir"] == {
        "latest": LATEST,
        "version": LATEST,
        "folder": str(folder),
        "cloned": True,
        "waits_for_pypi": False,
        "failure": None,
    }


def test_s031_8_a_second_tick_finds_the_folder_and_clones_nothing(root: Path, tmp_path: Path) -> None:
    host_, pypi = FakeHost(), FakePyPI()
    first = resolve(root, host_, tmp_path, pypi)
    second = resolve(root, host_, tmp_path, pypi)
    assert (first.folder, first.cloned) == (root / LATEST, True)
    assert (second.folder, second.cloned, second.lines()) == (root / LATEST, False, [])
    assert len(host_.clones) == 1


def test_s031_8_a_folder_another_gate_renamed_in_first_is_used(root: Path, tmp_path: Path) -> None:
    """The rival's folder appears between this tick's clone and its rename"""
    host_ = FakeHost(rival=True)
    found = resolve(root, host_, tmp_path, FakePyPI())
    assert (found.folder, found.cloned, found.failure) == (root / LATEST, False, None)
    assert (root / LATEST / "marker").read_text() == "rival"  # never written again
    assert leftovers(root) == []  # the tick's own temporary folder is removed


def test_s031_8_xdg_cache_home_moves_the_cache(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert cache_root({}, home) == home / ".cache" / "shipmill" / "plugin"
    assert cache_root({"XDG_CACHE_HOME": ""}, home) == home / ".cache" / "shipmill" / "plugin"
    assert cache_root({"XDG_CACHE_HOME": "/var/cache/amy"}, home) == Path("/var/cache/amy/shipmill/plugin")
    with pytest.raises(ReleaseError, match="XDG_CACHE_HOME must be an absolute path"):
        cache_root({"XDG_CACHE_HOME": "cache"}, home)


# --- S-031-9: the latest waits for PyPI -------------------------------------------------------


def test_s031_9_while_pypi_answers_404_the_session_loads_the_newest_cached(root: Path, checkout: Git) -> None:
    cached(root, "0.57.0")
    cached(root, OLDER)
    host_, pypi, claude = FakeHost(), FakePyPI({LATEST: 404}), FakeClaude()
    decision, launched, waiting, pruned = tick(checkout, claude, resolver(root, host_, pypi, checkout.root))
    assert decision.action is Action.LAUNCH and claude.plugin_dirs == [root / OLDER]
    assert pypi.asked == [PYPI_URL.format(version=LATEST)] and host_.clones == []
    lines = tick_lines(decision, launched, waiting, pruned, dry_run=False)
    assert f"  plugin: {LATEST} waits for PyPI; sessions load {OLDER}" in lines


def test_s031_9_with_nothing_cached_a_404_starts_no_session(root: Path, checkout: Git) -> None:
    claude = FakeClaude()
    decision, launched, _, _ = tick(checkout, claude, resolver(root, FakeHost(), FakePyPI({}), checkout.root))
    assert (decision.action, launched, claude.started) == (Action.PLUGIN_FAILED, None, [])
    assert f"{LATEST} isn't on PyPI yet" in decision.reason


# --- S-031-10: a failure falls back to the cache, or starts no session -----------------------

FAILURES = ["marketplace", "pypi error", "pypi 503", "clone", "check"]


def failing(case: str) -> tuple[FakeHost, FakePyPI, str]:
    """A host and PyPI on which one step fails, and that step"""
    if case == "marketplace":
        return FakeHost(marketplace_error="gh api failed: HTTP 502"), FakePyPI(), "the marketplace read"
    if case == "pypi error":
        return FakeHost(), FakePyPI({LATEST: "pypi.org is unreachable: timed out"}), "the PyPI read"
    if case == "pypi 503":
        return FakeHost(), FakePyPI({LATEST: 503}), "the PyPI read"
    if case == "clone":
        return FakeHost(clone_error="git clone --quiet failed: tag not found"), FakePyPI(), "the clone"
    return FakeHost(tagged="0.58.9"), FakePyPI(), "the version check"


@pytest.mark.parametrize("case", FAILURES)
def test_s031_10_a_failure_with_nothing_cached_is_plugin_failed(root: Path, checkout: Git, case: str) -> None:
    host_, pypi, step = failing(case)
    claude = FakeClaude([bg("old", "idle", "done")])
    tests = FakeSelfTest(PASSED)
    decision, launched, waiting, pruned = tick(
        checkout, claude, resolver(root, host_, pypi, checkout.root), tests=tests
    )
    assert (decision.action, launched) == (Action.PLUGIN_FAILED, None)
    assert (claude.started, claude.launched, claude.stopped, tests.runs) == ([], [], [], 0)
    failure = decision.plugin_dir.failure if decision.plugin_dir is not None else None
    assert failure is not None and failure.step == step
    assert decision.reason == (
        f"{step} failed: {failure.error}; the cache {root} holds no version PyPI serves,"
        f" so no session starts: {failure.fix}"
    )
    assert failure.error and failure.fix
    assert tick_lines(decision, launched, waiting, pruned, dry_run=False)[0] == f"PLUGIN_FAILED: {decision.reason}"
    assert not root.exists() or leftovers(root) == []


@pytest.mark.parametrize("case", FAILURES)
def test_s031_10_a_failure_with_a_cached_version_starts_the_session_on_it(root: Path, checkout: Git, case: str) -> None:
    host_, pypi, step = failing(case)
    cached(root)
    claude = FakeClaude()
    decision, launched, waiting, pruned = tick(checkout, claude, resolver(root, host_, pypi, checkout.root))
    assert decision.action is Action.LAUNCH and claude.plugin_dirs == [root / OLDER]
    failure = decision.plugin_dir.failure if decision.plugin_dir is not None else None
    assert failure is not None and failure.step == step
    lines = tick_lines(decision, launched, waiting, pruned, dry_run=False)
    assert f"  plugin: {step} failed, sessions load {OLDER}: {failure.line()}" in lines
    assert leftovers(root) == []


def test_s031_10_a_cache_folder_whose_plugin_json_isnt_its_name_fails_naming_it(root: Path, tmp_path: Path) -> None:
    plugin_folder(root / LATEST, "0.57.0")
    host_ = FakeHost()
    found = resolve(root, host_, tmp_path, FakePyPI())
    assert found.folder is None and found.failure is not None and host_.clones == []
    assert found.failure.step == "the version check"
    assert str(root / LATEST) in found.failure.error and found.failure.fix == f"rm -rf {root / LATEST}"
    cached(root)  # an older good one is used, the failure still reported
    again = resolve(root, host_, tmp_path, FakePyPI())
    assert again.folder == root / OLDER and again.failure == found.failure


# --- S-031-11: the commands carry --plugin-dir and enabledPlugins ----------------------------


@dataclass
class Commands:
    """ClaudeCli's runner and spawner: each command it ran or spawned"""

    ran: list[list[str]] = field(default_factory=list)
    spawned: list[list[str]] = field(default_factory=list)

    def run(self, cmd: list[str], cwd: Path) -> str:
        self.ran.append(cmd)
        if cmd[:2] == ["claude", "agents"]:
            return "[]"
        if cmd[:2] == ["claude", "--bg"]:
            return "started; claude attach s9\n"
        raise AssertionError(f"unexpected command {cmd}")

    def spawn(self, cmd: list[str], cwd: Path, log: Path, env: Mapping[str, str]) -> int:
        self.spawned.append(cmd)
        return 4242


APP_ENV = {"GH_TOKEN_HELPER": "/state/helpers/gh", "GIT_AUTHOR_NAME": "shipmill-gate[bot]"}
OFF = {"shipmill@shipmill": False}


def settings(cmd: list[str]) -> dict[str, object]:
    loaded: dict[str, object] = json.loads(cmd[cmd.index("--settings") + 1])
    return loaded


def test_s031_11_the_headless_command_carries_the_folder_and_the_setting(tmp_path: Path) -> None:
    commands = Commands()
    claude = ClaudeCli(["--model", "opus"], run=commands.run, spawn=commands.spawn, environ={})
    folder = tmp_path / LATEST
    claude.start(tmp_path, NAME, "do it", SESSION, tmp_path / "log", APP_ENV, folder)
    [cmd] = commands.spawned
    assert settings(cmd) == {"env": APP_ENV, "enabledPlugins": OFF}  # the env exactly as before, beside it
    at = cmd.index("--plugin-dir")
    assert cmd[at + 1] == str(folder) and at < cmd.index("--") and cmd[-2:] == ["--", "do it"]
    claude.start(tmp_path, NAME, "do it", SESSION, tmp_path / "log", None, folder)
    assert settings(commands.spawned[1]) == {"enabledPlugins": OFF}


def test_s031_11_the_interactive_command_carries_the_folder_and_the_setting(tmp_path: Path) -> None:
    commands = Commands()
    claude = ClaudeCli(["--permission-mode=auto"], run=commands.run, spawn=commands.spawn)
    folder = tmp_path / LATEST
    assert claude.launch(tmp_path, NAME, "do it", APP_ENV, folder) == "s9"
    [cmd] = commands.ran
    text = json.dumps({"env": APP_ENV, "enabledPlugins": OFF})
    assert cmd == [
        "claude",
        "--bg",
        "-n",
        NAME,
        "--settings",
        text,
        "--plugin-dir",
        str(folder),
        "--permission-mode=auto",
        "do it",
    ]


def test_s031_11_without_a_folder_the_commands_are_as_before(tmp_path: Path) -> None:
    commands = Commands()
    claude = ClaudeCli([], run=commands.run, spawn=commands.spawn)
    claude.launch(tmp_path, NAME, "do it", APP_ENV)
    assert commands.ran[0] == ["claude", "--bg", "-n", NAME, "--settings", json.dumps({"env": APP_ENV}), "do it"]
    claude.launch(tmp_path, NAME, "do it")
    assert commands.ran[1] == ["claude", "--bg", "-n", NAME, "do it"]


@pytest.mark.parametrize("mode", [Mode.HEADLESS, Mode.INTERACTIVE])
def test_s031_11_a_gate_tick_starts_either_session_on_the_cache_folder(root: Path, checkout: Git, mode: Mode) -> None:
    commands = Commands()
    claude = ClaudeCli([], run=commands.run, spawn=commands.spawn, environ={})
    tick(checkout, claude, resolver(root, FakeHost(), FakePyPI(), checkout.root), mode=mode)
    [cmd] = commands.spawned if mode is Mode.HEADLESS else [c for c in commands.ran if c[:2] == ["claude", "--bg"]]
    assert cmd[cmd.index("--plugin-dir") + 1] == str(root / LATEST)
    assert settings(cmd) == {"enabledPlugins": OFF}


def test_s031_12_a_session_turns_every_install_off_and_loads_only_the_folder(root: Path, checkout: Git) -> None:
    """The wiring S-031-12's probe relies on: `--settings` is Claude Code's highest settings
    source after managed policy, so its enabledPlugins turns off shipmill@shipmill enabled at
    user, project, or local scope, and --plugin-dir is the one copy left. The probe against a
    real `claude` is recorded in the pull request that built this"""
    commands = Commands()
    claude = ClaudeCli([], run=commands.run, spawn=commands.spawn, environ={})
    tick(checkout, claude, resolver(root, FakeHost(), FakePyPI(), checkout.root))
    [cmd] = commands.spawned
    assert settings(cmd)["enabledPlugins"] == {"shipmill@shipmill": False}
    assert [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--plugin-dir"] == [str(root / LATEST)]


def test_s031_11_the_refused_flags_are_the_specs() -> None:
    assert set(PLUGIN_REFUSED) == {"--plugin-dir", "--plugin-url"}


@pytest.mark.parametrize("mode", [Mode.HEADLESS, Mode.INTERACTIVE])
@pytest.mark.parametrize("arg", ["--plugin-dir", "--plugin-dir=/x", "--plugin-url", "--plugin-url=https://x"])
def test_s031_11_a_plugin_claude_arg_is_refused(root: Path, checkout: Git, mode: Mode, arg: str) -> None:
    claude = FakeClaude([bg("old", "idle", "done")], args=(arg, "/x"))
    host_ = FakeHost()
    with pytest.raises(ReleaseError, match=f"--claude-arg {arg.split('=')[0]} is refused"):
        tick(checkout, claude, resolver(root, host_, FakePyPI(), checkout.root), mode=mode)
    assert (claude.started, claude.launched, claude.stopped, host_.calls) == ([], [], [], [])


# --- S-031-14: the self-test runs the cache folder's hooks ------------------------------------


def test_s031_14_the_self_test_runs_on_the_folder_the_session_loads(root: Path, checkout: Git) -> None:
    tests, claude = FakeSelfTest(PASSED), FakeClaude()
    tick(checkout, claude, resolver(root, FakeHost(), FakePyPI(), checkout.root), tests=tests)
    assert tests.folders == [root / LATEST] == claude.plugin_dirs


def test_s031_14_a_failing_self_test_of_the_folder_pauses_a_headless_tick(root: Path, checkout: Git) -> None:
    broken = HookTest(f"the PreToolUse hook of shipmill@shipmill {LATEST} (the gate's cache) exited 1", "rm -rf it")
    tests, claude = FakeSelfTest(broken), FakeClaude()
    decision, *_ = tick(checkout, claude, resolver(root, FakeHost(), FakePyPI(), checkout.root), tests=tests)
    assert (decision.action, claude.started, tests.folders) == (Action.HOOKS_FAILED, [], [root / LATEST])


def test_a_dry_run_reads_the_folder_and_starts_nothing(root: Path, checkout: Git) -> None:
    claude, tests = FakeClaude(), FakeSelfTest(PASSED)
    decision, launched, _, _ = tick(
        checkout, claude, resolver(root, FakeHost(), FakePyPI(), checkout.root), tests=tests, dry_run=True
    )
    assert (decision.action, launched, claude.started) == (Action.LAUNCH, None, [])
    assert tests.folders == [root / LATEST]


def test_a_tick_that_launches_nothing_reads_no_plugin(root: Path, checkout: Git) -> None:
    host_ = FakeHost()
    claude = FakeClaude([bg("live", "busy", "working")])
    decision, *_ = tick(checkout, claude, resolver(root, host_, FakePyPI(), checkout.root))
    assert decision.action is Action.RUNNING and host_.calls == [] and not root.exists()


def test_the_cache_folder_loads_instead_of_the_install_check(root: Path, checkout: Git) -> None:
    """D-35's install read can't apply to a session that loads the cache folder"""

    def never(cmd: list[str], cwd: Path) -> str:
        raise AssertionError(f"no install is read: {cmd}")

    agents = AgentsConfig(prompt="/t", prs=False, retry_hours=24, mode=Mode.HEADLESS)
    claude = FakeClaude()
    decision, *_ = gate(
        checkout,
        "romamo/demo",
        lambda: agents,
        claude,
        lambda _: [ISSUES],
        NOW,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        login=host,
        started=lambda pid: None,
        plugins=never,
        cache=resolver(root, FakeHost(), FakePyPI(), checkout.root),
    )
    assert decision.action is Action.LAUNCH and decision.loaded is None and claude.plugin_dirs == [root / LATEST]
