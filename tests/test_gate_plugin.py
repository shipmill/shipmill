"""The gate and the shipmill@shipmill plugin its sessions load.

Spec 031, D-44: the gate reports, never pauses on, an install that lags the latest release, an
install keyed on its linked worktree, its own lagging CLI, and an unmet `requires`; the one hold
is PyPI answering 404 for the version sessions load. It changes no install (S-031-21), and the
config refuses [agents] plugin_update (S-031-22)"""

import json
import subprocess
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig, Mode
from shipmill.autonomy import Hold
from shipmill.errors import ReleaseError
from shipmill.gate import Action, ClaudeCli, Decision, Waiting, gate, state_dir, tick_lines, tick_record
from shipmill.gitrepo import Git
from shipmill.plugin import (
    CLI_RECORD,
    INSTALLED,
    READ_MARKETPLACE,
    GateCli,
    Listed,
    PluginHost,
    effective,
    listed_installs,
    load_cli,
    session_project,
    update_command,
)
from shipmill.requires import Requires
from shipmill.version import Version
from shipmill.worktrees import Judged

from .test_gate import ISSUES, NO_PRUNE, NOW, FakeClaude, FakeNotifier, bg, host

Tick = tuple[Decision, str | None, tuple[Waiting, ...], tuple[Judged, ...]]
READS = {("claude", "plugin", "list"), ("gh", "api", "-H")}  # the only commands the gate runs on the plugin
PYPI_URL = "https://pypi.org/pypi/shipmill/{}/json"


def marketplace(ref: str) -> str:
    """shipmill/shipmill's marketplace.json, as the gh api read gives it raw, naming ref"""
    entry = {"name": "shipmill", "source": {"source": "github", "repo": "shipmill/shipmill", "ref": ref}}
    return json.dumps({"name": "shipmill", "plugins": [entry]}) + "\n"


@dataclass
class FakeRunner:
    """claude plugin list and the marketplace's gh api read, without either tool; any other
    command, such as `claude plugin update`, fails the test. installs maps (scope, folder) to a
    version"""

    checkout: Path
    version: str | None = "0.25.0"  # the checkout's project install; None: none
    latest: str = "v0.32.2"
    user: str | None = "0.32.2"  # the user-scope install's version; None: none
    installs: dict[tuple[str, Path], str] = field(default_factory=dict)
    calls: list[tuple[list[str], Path]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.version is not None and not self.installs:
            self.installs[("project", self.checkout)] = self.version

    def __call__(self, cmd: list[str], cwd: Path) -> str:
        self.calls.append((cmd, cwd))
        if cmd[:3] == ["claude", "plugin", "list"]:
            listed: list[dict[str, str]] = []
            if self.user is not None:
                listed.append({"id": "shipmill@shipmill", "scope": "user", "version": self.user})
            listed += [
                {"id": "shipmill@shipmill", "scope": scope, "version": version, "projectPath": str(folder)}
                for (scope, folder), version in self.installs.items()
            ]
            return json.dumps(listed)
        if cmd == READ_MARKETPLACE:
            return marketplace(self.latest)
        raise AssertionError(f"unexpected command {cmd}")

    @property
    def ran(self) -> set[tuple[str, ...]]:
        """Each command's first three words"""
        return {tuple(cmd[:3]) for cmd, _ in self.calls}


@dataclass
class FakePyPI:
    """PyPI's JSON API: the status it answers, or no answer at all"""

    status: int = 200
    down: str | None = None
    asked: list[str] = field(default_factory=list)

    def __call__(self, url: str) -> int:
        self.asked.append(url)
        if self.down is not None:
            raise ReleaseError(self.down)
        return self.status


def plugin_host(
    runner: FakeRunner,
    markers: Path,
    cli: str = "0.32.2",
    pypi: FakePyPI | None = None,
    bound: Requires | None = None,
    fix: str = "uv tool upgrade shipmill",
) -> PluginHost:
    return PluginHost(runner, GateCli(Version.parse(cli), fix), pypi or FakePyPI(), markers, lambda: bound)


@pytest.fixture
def checkout(tmp_path: Path) -> Git:
    root = tmp_path / "demo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    git = Git(root)
    git.run("remote", "add", "origin", "https://github.com/romamo/demo.git")
    return git


def markers_of(git: Git) -> Path:
    """The notification markers' folder, beside the checkout, never the real home's"""
    return git.root.parent / "cache" / "shipmill" / "plugin"


def agents(notify: bool = True, mode: Mode = Mode.INTERACTIVE) -> AgentsConfig:
    return AgentsConfig(prompt="/t", prs=False, retry_hours=24, notify=notify, mode=mode)


def tick(git: Git, runner: FakeRunner, dry: bool = False) -> Tick:
    return gate(
        git,
        "romamo/demo",
        lambda: agents(),
        FakeClaude([bg("old", "idle", "done")]),
        lambda _: [ISSUES],
        NOW,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        dry_run=dry,
        login=host,
        plugin=plugin_host(runner, markers_of(git)),
    )


@pytest.mark.parametrize(
    ("entry", "fix"),
    [
        (
            {"scope": "user", "version": "0.1.0"},
            "claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope user",
        ),
        (
            {"scope": "project", "version": "0.1.0", "projectPath": "/w/r"},
            "in /w/r: claude plugin marketplace update shipmill"
            " && claude plugin update shipmill@shipmill --scope project",
        ),
        (
            {"scope": "local", "version": "0.1.0", "projectPath": "/w/r"},
            "in /w/r: claude plugin marketplace update shipmill"
            " && claude plugin update shipmill@shipmill --scope local",
        ),
    ],
)
def test_a_stale_installs_fix_refreshes_the_marketplace_first(entry: dict[str, str], fix: str) -> None:
    # #477: the marketplace refresh, then the update, in that order, at each scope
    installs = listing(entry)
    assert update_command(installs[0], installs) == fix


def test_the_nested_install_fix_refreshes_the_marketplace_before_the_reinstall() -> None:
    installs = listing(
        {"scope": "project", "version": "0.1.0", "projectPath": "/w/r"},
        {"scope": "project", "version": "0.1.0", "projectPath": "/w/r/tmp/shipmill-gate"},
    )
    assert update_command(installs[0], installs) == (
        "in /w/r: claude plugin marketplace update shipmill && claude plugin uninstall shipmill@shipmill"
        " --scope project && claude plugin install shipmill@shipmill --scope project"
        " (`update` picks the nested install in /w/r/tmp/shipmill-gate, a Claude Code bug)"
    )


def test_a_tick_that_launches_nothing_checks_nothing(checkout: Git) -> None:
    runner = FakeRunner(checkout.root)
    pypi = FakePyPI()
    decision, _, _, _ = gate(
        checkout,
        "romamo/demo",
        lambda: agents(),
        FakeClaude(),
        lambda _: [],
        NOW,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        login=host,
        plugin=plugin_host(runner, markers_of(checkout), pypi=pypi),
    )
    assert decision.action is Action.QUIET and runner.calls == [] and pypi.asked == []


# -- S-031-21: the gate's update path is gone; S-031-22 refuses [agents] plugin_update ----------


@pytest.mark.parametrize("dry", [False, True])
def test_s031_21_the_gate_changes_no_install_and_runs_no_plugin_update(checkout: Git, dry: bool) -> None:
    # behind installs keyed on the checkout, at both scopes, as D-23's daily update once updated;
    # the key that asked for it is refused since (S-031-22, tests/test_plugin_update_removed.py)
    root = checkout.root.resolve()
    installs = {("project", root): "0.25.0", ("local", root): "0.30.0"}
    runner = FakeRunner(checkout.root, installs=installs, user="0.31.0")
    decision, launched, _, _ = tick(checkout, runner, dry=dry)
    assert decision.action is Action.LAUNCH and (launched is None) is dry
    assert runner.ran == READS  # read only: no `claude plugin update`, no marketplace refresh
    assert runner.installs == {("project", root): "0.25.0", ("local", root): "0.30.0"}
    assert not (state_dir(checkout) / "plugin-check.json").exists()  # no daily check is recorded
    record = tick_record(decision, launched, (), (), dry_run=dry)
    assert "plugin" not in record  # the daily update's record is gone with it
    lines = tick_lines(decision, launched, (), (), dry_run=dry)
    assert not any(line.startswith(("  plugin updated", "  plugin update failed")) for line in lines)
    assert any("0.25.0 (project scope" in line and "lags" in line for line in lines)


# -- spec 031: the gate reports what lags and starts the session ------------------------------


@pytest.fixture
def linked(tmp_path: Path) -> tuple[Git, Path]:
    """shipmill's own layout: the gate's checkout is a linked worktree nested in the main one"""
    main = tmp_path / "r"
    main.mkdir()
    subprocess.run(["git", "init", "-q", str(main)], check=True)
    run = ["git", "-C", str(main), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*run, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    subprocess.run([*run, "worktree", "add", "-q", "--detach", str(main / "tmp" / "shipmill-gate")], check=True)
    git = Git(main / "tmp" / "shipmill-gate")
    git.run("remote", "add", "origin", "https://github.com/romamo/demo.git")
    return git, main.resolve()


def report_tick(
    git: Git,
    plugin: PluginHost,
    config: AgentsConfig,
    claude: FakeClaude | None = None,
    notifier: FakeNotifier | None = None,
    dry: bool = False,
) -> Tick:
    return gate(
        git,
        "romamo/demo",
        lambda: config,
        claude or FakeClaude([bg("old", "idle", "done")]),
        lambda _: [ISSUES],
        NOW,
        Hold,
        notifier or FakeNotifier(),
        NO_PRUNE,
        dry_run=dry,
        login=host,
        started=lambda _: "Sat Oct  4 12:00:00 2026",
        new_session=lambda: uuid.UUID(int=1),
        plugin=plugin,
    )


def plugin_lines(decision: Decision, launched: str | None) -> list[str]:
    return [line for line in tick_lines(decision, launched, (), (), dry_run=False)[1:] if "plugin" in line]


USER_FIX = "claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope user"


@pytest.mark.parametrize("mode", [Mode.INTERACTIVE, Mode.HEADLESS])
@pytest.mark.parametrize("scope", ["user", "project", "local"])
def test_s031_13_a_lagging_install_at_any_scope_starts_the_session_with_one_line(
    checkout: Git, mode: Mode, scope: str
) -> None:
    root = checkout.root.resolve()
    if scope == "user":
        runner = FakeRunner(checkout.root, version=None, user="0.31.0")
        fix, where = USER_FIX, "user scope"
    else:
        runner = FakeRunner(checkout.root, installs={(scope, root): "0.31.0"}, user=None)
        fix = (
            f"in {root}: claude plugin marketplace update shipmill"
            f" && claude plugin update shipmill@shipmill --scope {scope}"
        )
        where = f"{scope} scope, keyed on {root}"
    claude = FakeClaude([bg("old", "idle", "done")])
    decision, launched, _, _ = report_tick(
        checkout, plugin_host(runner, markers_of(checkout)), agents(mode=mode), claude
    )
    assert not hasattr(Action, "PLUGIN_STALE")  # no tick reads it
    assert decision.action is Action.LAUNCH
    assert launched is not None and (claude.launched or claude.started)  # the session starts
    assert plugin_lines(decision, launched) == [
        f"  plugin: shipmill@shipmill 0.31.0 ({where}) lags the latest release 0.32.2; the session starts;"
        f" update it: {fix}"
    ]
    assert runner.ran == READS  # reported, never updated
    record = tick_record(decision, launched, (), (), dry_run=False)["loaded"]
    assert isinstance(record, dict) and record["lags"] == [
        {"scope": scope, "folder": None if scope == "user" else str(root), "version": "0.31.0", "fix": fix}
    ]


def test_s031_13_every_lagging_install_that_applies_gets_its_line(linked: tuple[Git, Path]) -> None:
    git, main = linked
    runner = FakeRunner(git.root, installs={("local", main): "0.31.1", ("project", main): "0.30.0"}, user="0.29.0")
    decision, launched, _, _ = report_tick(git, plugin_host(runner, git.root.parent / "m"), agents())
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    assert [line.split(" lags ")[0] for line in plugin_lines(decision, launched)] == [
        f"  plugin: shipmill@shipmill 0.31.1 (local scope, keyed on {main})",
        f"  plugin: shipmill@shipmill 0.30.0 (project scope, keyed on {main})",
        "  plugin: shipmill@shipmill 0.29.0 (user scope)",
    ]


def test_s031_16_an_install_keyed_on_the_gates_linked_worktree_is_reported_as_unloaded(
    linked: tuple[Git, Path], tmp_path: Path
) -> None:
    # #485: Claude Code loads the main checkout's installs in the linked gate checkout, so the
    # entry keyed on the worktree itself is never loaded and no `claude plugin` command reaches it
    git, main = linked
    gate_dir = git.root.resolve()
    installs = {("local", main): "0.32.2", ("local", gate_dir): "0.25.0"}
    runner = FakeRunner(git.root, installs=installs, user="0.32.2")
    decision, launched, _, _ = report_tick(git, plugin_host(runner, tmp_path / "m"), agents())
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    fix = f'delete the entry with "projectPath": "{gate_dir}" under "shipmill@shipmill" in {INSTALLED}'
    assert INSTALLED == "~/.claude/plugins/installed_plugins.json"
    assert plugin_lines(decision, launched) == [
        f"  plugin: shipmill@shipmill 0.25.0 (local scope, keyed on {gate_dir}) is keyed on the gate's linked"
        f" worktree, which no session loads; {fix}"
    ]
    record = tick_record(decision, launched, (), (), dry_run=False)["loaded"]
    assert isinstance(record, dict)
    assert record["unloaded"] == [{"scope": "local", "folder": str(gate_dir), "version": "0.25.0", "fix": fix}]
    assert record["lags"] == []  # the session's install is current: no session loads the worktree's
    # shipmill only reads the installs: a list and the marketplace, no command that changes one
    assert runner.ran == READS


def test_s031_16_a_main_checkouts_own_install_is_never_unloaded(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, installs={("local", checkout.root.resolve()): "0.32.2"}, user=None)
    decision, launched, _, _ = report_tick(checkout, plugin_host(runner, markers_of(checkout)), agents())
    assert decision.loaded is not None and decision.loaded.unloaded == ()
    assert plugin_lines(decision, launched) == []


def test_s031_17_the_gates_own_lagging_cli_is_reported_with_its_fix_and_the_session_starts(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version=None, user="0.32.2")
    plugin = plugin_host(runner, markers_of(checkout), cli="0.30.0")
    decision, launched, _, _ = report_tick(checkout, plugin, agents())
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    lines = tick_lines(decision, launched, (), (), dry_run=False)
    assert "  the gate's CLI, shipmill 0.30.0, lags the latest release 0.32.2: uv tool upgrade shipmill" in lines
    record = tick_record(decision, launched, (), (), dry_run=False)["loaded"]
    assert isinstance(record, dict) and record["cli"] == {"version": "0.30.0", "fix": "uv tool upgrade shipmill"}
    assert load_cli(state_dir(checkout) / CLI_RECORD) == Version.parse("0.30.0")  # for doctor and status
    current = plugin_host(runner, markers_of(checkout), cli="0.32.2")
    (state_dir(checkout) / "gate.json").unlink()
    decision, launched, _, _ = report_tick(checkout, current, agents())
    assert not any("gate's CLI" in line for line in tick_lines(decision, launched, (), (), dry_run=False))


def test_s031_17_a_dry_run_records_no_cli_version(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version=None)
    report_tick(checkout, plugin_host(runner, markers_of(checkout), cli="0.30.0"), agents(), dry=True)
    assert load_cli(state_dir(checkout) / CLI_RECORD) is None


@pytest.mark.parametrize(
    ("user", "bound", "fix"),
    [
        ("0.31.0", ">=0.32", f"{USER_FIX}; or lower requires in .github/shipmill.toml"),
        ("0.32.2", ">=0.33", "release shipmill 0.33.0 or later, or lower requires in .github/shipmill.toml"),
    ],
)
def test_s031_19_an_unmet_requires_is_reported_and_the_session_starts(
    checkout: Git, user: str, bound: str, fix: str
) -> None:
    runner = FakeRunner(checkout.root, version=None, user=user)
    plugin = plugin_host(runner, markers_of(checkout), bound=Requires.parse(bound))
    decision, launched, _, _ = report_tick(checkout, plugin, agents())
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    line = (
        f"  plugin: .github/shipmill.toml requires shipmill {bound}, but sessions here load shipmill@shipmill"
        f" {user} (user scope), whose shipmill commands refuse the config; the session starts; fix: {fix}"
    )
    assert line in tick_lines(decision, launched, (), (), dry_run=False)
    record = tick_record(decision, launched, (), (), dry_run=False)["loaded"]
    assert isinstance(record, dict) and record["requires"] == {"bound": bound, "fix": fix}


def test_s031_19_a_met_requires_says_nothing(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version=None, user="0.32.2")
    plugin = plugin_host(runner, markers_of(checkout), bound=Requires.parse(">=0.32"))
    decision, launched, _, _ = report_tick(checkout, plugin, agents())
    assert plugin_lines(decision, launched) == []


def lagging(git: Git, markers: Path) -> PluginHost:
    return plugin_host(FakeRunner(git.root, version=None, user="0.31.0"), markers)


def test_s031_20_the_first_tick_on_a_host_notifies_once_per_release(tmp_path: Path) -> None:
    markers = tmp_path / "home" / ".cache" / "shipmill" / "plugin"
    gates = []
    for name in ("a", "b"):  # two gates on one host, two repos
        root = tmp_path / name
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        git = Git(root)
        git.run("remote", "add", "origin", "https://github.com/romamo/demo.git")
        gates.append(git)
    notifier = FakeNotifier()
    decision, _, _, _ = report_tick(gates[0], lagging(gates[0], markers), agents(), notifier=notifier)
    assert notifier.sent == [
        ("shipmill 0.32.2 is out", f"update shipmill@shipmill: 0.31.0 (user scope): {USER_FIX}"),
    ]
    assert (markers / "0.32.2.notified").is_file()
    assert "  notified: shipmill@shipmill lags 0.32.2" in tick_lines(decision, "s1", (), (), dry_run=False)
    decision, launched, _, _ = report_tick(gates[1], lagging(gates[1], markers), agents(), notifier=notifier)
    assert len(notifier.sent) == 1 and decision.plugin_notice is None and launched == "s1"
    (state_dir(gates[0]) / "gate.json").unlink()  # a new launch, not UNCHANGED
    report_tick(gates[0], lagging(gates[0], markers), agents(), notifier=notifier)
    assert len(notifier.sent) == 1  # the marker holds for every later tick of any gate


def test_s031_20_notify_false_sends_none_and_writes_no_marker(checkout: Git) -> None:
    notifier = FakeNotifier()
    markers = markers_of(checkout)
    decision, launched, _, _ = report_tick(
        checkout, lagging(checkout, markers), agents(notify=False), notifier=notifier
    )
    assert notifier.sent == [] and not markers.exists() and decision.plugin_notice is None
    assert launched == "s1"


def test_s031_20_a_dry_run_sends_none_and_writes_no_marker(checkout: Git) -> None:
    notifier = FakeNotifier()
    markers = markers_of(checkout)
    decision, _, _, _ = report_tick(checkout, lagging(checkout, markers), agents(), notifier=notifier, dry=True)
    assert notifier.sent == [] and not markers.exists()
    assert decision.plugin_notice == "would notify: shipmill@shipmill lags 0.32.2"


def test_s031_20_a_failed_send_is_reported_and_the_marker_stays(checkout: Git) -> None:
    notifier = FakeNotifier(fail="osascript exited 1")
    markers = markers_of(checkout)
    decision, launched, _, _ = report_tick(checkout, lagging(checkout, markers), agents(), notifier=notifier)
    assert decision.plugin_notice == "notify failed: osascript exited 1" and launched == "s1"
    assert (markers / "0.32.2.notified").is_file()  # one try per release on the host


def test_s031_20_no_lag_sends_none(checkout: Git) -> None:
    notifier = FakeNotifier()
    markers = markers_of(checkout)
    plugin = plugin_host(FakeRunner(checkout.root, version=None), markers)
    report_tick(checkout, plugin, agents(), notifier=notifier)
    assert notifier.sent == [] and not markers.exists()


@pytest.mark.parametrize("mode", [Mode.INTERACTIVE, Mode.HEADLESS])
def test_s031_24_a_version_pypi_doesnt_serve_yet_holds_the_tick_and_the_next_retries(checkout: Git, mode: Mode) -> None:
    runner = FakeRunner(checkout.root, version=None, user="0.32.2")
    pypi = FakePyPI(status=404)
    claude = FakeClaude([bg("old", "idle", "done")])
    decision, launched, _, _ = report_tick(
        checkout, plugin_host(runner, markers_of(checkout), pypi=pypi), agents(mode=mode), claude
    )
    assert pypi.asked == [PYPI_URL.format("0.32.2")]
    assert (decision.action, launched) == (Action.PYPI_WAIT, None)
    assert claude.launched == [] and claude.started == [] and claude.stopped == []
    assert decision.reason.startswith("plugin 0.32.2 waits for PyPI")
    assert tick_lines(decision, launched, (), (), dry_run=False)[0].startswith(
        "PYPI_WAIT: plugin 0.32.2 waits for PyPI"
    )
    assert not (state_dir(checkout) / "gate.json").exists()  # no launch recorded: the next tick tries again
    pypi.status = 200  # publish uploaded it
    decision, launched, _, _ = report_tick(
        checkout, plugin_host(runner, markers_of(checkout), pypi=pypi), agents(mode=mode), claude
    )
    assert decision.action is Action.LAUNCH and launched is not None and len(pypi.asked) == 2


@pytest.mark.parametrize(
    ("pypi", "line"),
    [
        (
            FakePyPI(status=503),
            f"  plugin 0.32.2: PyPI answered 503 for {PYPI_URL.format('0.32.2')}; the session starts anyway",
        ),
        (FakePyPI(down="timed out"), "  plugin 0.32.2: PyPI didn't answer (timed out); the session starts anyway"),
    ],
)
def test_s031_24_any_other_pypi_answer_is_reported_and_the_session_starts(
    checkout: Git, pypi: FakePyPI, line: str
) -> None:
    runner = FakeRunner(checkout.root, version=None, user="0.32.2")
    decision, launched, _, _ = report_tick(checkout, plugin_host(runner, markers_of(checkout), pypi=pypi), agents())
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    assert line in tick_lines(decision, launched, (), (), dry_run=False)


def test_s031_24_a_served_version_says_nothing_and_no_install_asks_nothing(checkout: Git) -> None:
    pypi = FakePyPI()
    runner = FakeRunner(checkout.root, version=None, user="0.32.2")
    decision, launched, _, _ = report_tick(checkout, plugin_host(runner, markers_of(checkout), pypi=pypi), agents())
    assert plugin_lines(decision, launched) == [] and len(pypi.asked) == 1
    none = FakePyPI(status=404)
    (state_dir(checkout) / "gate.json").unlink()
    bare = FakeRunner(checkout.root, version=None, user=None)
    decision, _, _, _ = report_tick(checkout, plugin_host(bare, markers_of(checkout), pypi=none), agents())
    assert decision.action is Action.LAUNCH and none.asked == []  # no version sessions load: nothing to wait for


def test_s031_24_the_gates_claude_commands_carry_no_plugin_dir(tmp_path: Path) -> None:
    ran: list[list[str]] = []
    spawned: list[list[str]] = []

    def run(cmd: list[str], cwd: Path) -> str:
        ran.append(cmd)
        return "started: claude attach s1\n"

    def spawn(cmd: list[str], cwd: Path, log: Path, env: Mapping[str, str]) -> int:
        spawned.append(cmd)
        return 42

    cli = ClaudeCli(["--model", "opus"], run=run, spawn=spawn, environ={})
    assert cli.launch(tmp_path, "n", "prompt", {"GH_TOKEN_HELPER": "x"}) == "s1"
    assert cli.start(tmp_path, "n", "prompt", uuid.UUID(int=1), tmp_path / "s.log") == 42
    assert ran and ran[0][:2] == ["claude", "--bg"] and spawned and spawned[0][:2] == ["claude", "-p"]
    assert not any(arg.startswith("--plugin-dir") for cmd in ran + spawned for arg in cmd)


# -- the install a session loads -------------------------------------------------------------


def test_a_failed_latest_release_read_is_reported_and_the_session_starts(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, latest="latest")  # not a version tag: the read fails
    decision, launched, _, _ = report_tick(checkout, plugin_host(runner, markers_of(checkout)), agents())
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    assert decision.loaded is not None and decision.loaded.error is not None
    lines = tick_lines(decision, launched, (), (), dry_run=False)
    assert f"  plugin check failed, the session starts anyway: {decision.loaded.error}" in lines


def test_with_no_install_the_session_starts_and_the_tick_says_so(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version=None, user=None)
    decision, launched, _, _ = report_tick(checkout, plugin_host(runner, markers_of(checkout)), agents())
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    lines = tick_lines(decision, launched, (), (), dry_run=False)
    assert (
        f"  plugin: no shipmill@shipmill install applies to {checkout.root.resolve()}; the session loads no"
        " shipmill skills"
    ) in lines


def listing(*entries: dict[str, str]) -> list[Listed]:
    return listed_installs(json.dumps([{"id": "shipmill@shipmill", **e} for e in entries]))


@pytest.mark.parametrize(
    ("entries", "expected"),
    [
        ([{"scope": "user", "version": "1.0.0"}], ("user", "1.0.0")),
        ([{"scope": "managed", "version": "1.0.0"}], ("managed", "1.0.0")),
        ([{"scope": "managed", "version": "2.0.0"}, {"scope": "user", "version": "1.0.0"}], ("user", "1.0.0")),
        (
            [{"scope": "user", "version": "1.0.0"}, {"scope": "project", "version": "0.9.0", "projectPath": "/w/r"}],
            ("project", "0.9.0"),
        ),
        (
            [
                {"scope": "project", "version": "0.9.0", "projectPath": "/w/r"},
                {"scope": "local", "version": "0.8.0", "projectPath": "/w/r"},
            ],
            ("local", "0.8.0"),
        ),
        (
            [  # keyed on other folders, an enclosing one included: neither applies
                {"scope": "local", "version": "0.8.0", "projectPath": "/w"},
                {"scope": "project", "version": "0.8.0", "projectPath": "/w/r/tmp/shipmill-gate"},
                {"scope": "user", "version": "1.0.0"},
            ],
            ("user", "1.0.0"),
        ),
    ],
)
def test_a_session_loads_the_most_specific_scope_for_its_project(
    entries: list[dict[str, str]], expected: tuple[str, str]
) -> None:
    found = effective(listing(*entries), Path("/w/r").resolve())
    assert found is not None and (str(found.scope), str(found.version)) == expected


def test_no_install_that_applies_is_none() -> None:
    assert effective(listing({"scope": "local", "version": "1.0.0", "projectPath": "/x"}), Path("/w/r")) is None


def test_a_linked_worktrees_project_is_its_main_checkout() -> None:
    gate_dir = Path("/w/r/tmp/shipmill-gate")
    assert session_project(gate_dir, "/w/r/.git\n") == Path("/w/r").resolve()
    assert session_project(Path("/w/r"), "/w/r/.git\n") == Path("/w/r").resolve()
    assert session_project(Path("/srv/x"), "/srv/x.git\n") == Path("/srv/x").resolve()


@pytest.mark.parametrize(
    "text",
    [
        '[{"id": "shipmill@shipmill", "scope": "session", "version": "1.0.0"}]',
        '[{"id": "shipmill@shipmill", "scope": "user", "version": "abc123"}]',
        '[{"id": "shipmill@shipmill", "scope": "project", "version": "1.0.0"}]',
    ],
)
def test_a_malformed_install_is_refused(text: str) -> None:
    with pytest.raises(ReleaseError):
        listed_installs(text)


def test_two_installs_at_the_deciding_scope_are_refused() -> None:
    twice = listing({"scope": "user", "version": "1.0.0"}, {"scope": "user", "version": "1.1.0"})
    with pytest.raises(ReleaseError, match="twice at user scope"):
        effective(twice, Path("/w/r"))


@pytest.mark.parametrize("text", ["{", '{"version": 1}', '{"version": "x"}', '{"version": "1.0.0", "more": 1}'])
def test_a_malformed_cli_record_fails(tmp_path: Path, text: str) -> None:
    path = tmp_path / CLI_RECORD
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ReleaseError):
        load_cli(path)
