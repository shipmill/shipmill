"""The gate and the shipmill@shipmill plugin its sessions load.

#233, #240, D-23: with [agents] plugin_update = true the gate updates every plugin install keyed
on its checkout, at project or local scope, at most once a day, before it starts a session.

Spec 031, D-44: the gate reports, never pauses on, an install that lags the latest release, an
install keyed on its linked worktree, its own lagging CLI, and an unmet `requires`; the one hold
is PyPI answering 404 for the version sessions load"""

import datetime as dt
import json
import os
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
    CHECKED,
    CLI_RECORD,
    INSTALLED,
    READ_MARKETPLACE,
    GateCli,
    Install,
    Listed,
    PluginHost,
    PluginUpdate,
    checkout_installs,
    daily_update,
    effective,
    keyed_installs,
    listed_installs,
    load_checked,
    load_cli,
    session_project,
    update_command,
)
from shipmill.requires import Requires
from shipmill.version import Version
from shipmill.worktrees import Judged

from .test_gate import ISSUES, NO_PRUNE, NOW, FakeClaude, FakeNotifier, bg, host, write_config

Tick = tuple[Decision, str | None, tuple[Waiting, ...], tuple[Judged, ...]]
UPDATE = ["claude", "plugin", "update", "shipmill@shipmill", "--scope"]
REFRESH = ["claude", "plugin", "marketplace", "update", "shipmill"]
PYPI_URL = "https://pypi.org/pypi/shipmill/{}/json"


def marketplace(ref: str) -> str:
    """shipmill/shipmill's marketplace.json, as the gh api read gives it raw, naming ref"""
    entry = {"name": "shipmill", "source": {"source": "github", "repo": "shipmill/shipmill", "ref": ref}}
    return json.dumps({"name": "shipmill", "plugins": [entry]}) + "\n"


@dataclass
class FakeRunner:
    """claude plugin list, the marketplace's gh api read, claude plugin marketplace update, and claude plugin
    update, without either tool.
    installs maps (scope, folder) to a version; an update at a scope run in cwd sets the
    install keyed on `acts_on(cwd)` (the cwd itself by default) to the latest release"""

    checkout: Path
    version: str | None = "0.25.0"  # the checkout's project install; None: none
    latest: str = "v0.32.2"
    fail_update: bool = False
    fail_refresh: bool = False
    user: str | None = "0.32.2"  # the user-scope install's version; None: none
    installs: dict[tuple[str, Path], str] = field(default_factory=dict)
    acts_on: dict[Path, Path] = field(default_factory=dict)  # cwd -> the folder an update keys on
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
        if cmd == REFRESH:
            if self.fail_refresh:
                raise ReleaseError("claude plugin marketplace update failed: offline")
            return "refreshed\n"
        if cmd[:5] == UPDATE and len(cmd) == 6:
            if self.fail_update:
                raise ReleaseError("claude plugin update failed: network down")
            key = (cmd[5], self.acts_on.get(cwd, cwd))
            if key in self.installs:
                self.installs[key] = self.latest.removeprefix("v")
            return "updated\n"
        raise AssertionError(f"unexpected command {cmd}")

    @property
    def updates(self) -> list[Path]:
        return [cwd for cmd, cwd in self.calls if cmd[:5] == UPDATE]

    @property
    def scopes(self) -> list[str]:
        return [cmd[5] for cmd, _ in self.calls if cmd[:5] == UPDATE]


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


def agents(plugin_update: bool, notify: bool = True, mode: Mode = Mode.INTERACTIVE) -> AgentsConfig:
    return AgentsConfig(prompt="/t", prs=False, retry_hours=24, notify=notify, mode=mode, plugin_update=plugin_update)


def tick(git: Git, runner: FakeRunner, plugin_update: bool = True, now: dt.datetime = NOW, dry: bool = False) -> Tick:
    return gate(
        git,
        "romamo/demo",
        lambda: agents(plugin_update),
        FakeClaude([bg("old", "idle", "done")]),
        lambda _: [ISSUES],
        now,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        dry_run=dry,
        login=host,
        plugin=plugin_host(runner, markers_of(git)),
    )


def test_a_behind_install_is_updated_in_the_checkout_before_the_launch(checkout: Git) -> None:
    runner = FakeRunner(checkout.root)
    decision, launched, _, _ = tick(checkout, runner)
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    assert runner.updates == [checkout.root] and runner.scopes == ["project"]
    own = (Install("project", checkout.root.resolve(), "0.25.0"),)
    assert decision.plugin == PluginUpdate(own, "0.32.2", ("project",))
    lines = tick_lines(decision, launched, (), (), dry_run=False)
    assert "  plugin updated: shipmill@shipmill 0.25.0 -> 0.32.2 in this checkout (project scope)" in lines
    assert tick_record(decision, launched, (), (), dry_run=False)["plugin"] == {
        "latest": "0.32.2",
        "installs": [{"scope": "project", "installed": "0.25.0", "updated": True}],
        "error": None,
    }
    assert load_checked(state_dir(checkout) / CHECKED) == NOW


def test_a_behind_local_install_in_the_checkout_is_updated_at_local_scope(checkout: Git) -> None:
    # #240: shipmill's own gate checkout has a local-scope install, which D-22 left at 0.25.0
    main = checkout.root.parent
    installs = {("local", checkout.root): "0.25.0", ("local", main): "0.31.1"}
    runner = FakeRunner(checkout.root, installs=installs)
    decision, launched, _, _ = tick(checkout, runner)
    assert launched == "s1" and runner.scopes == ["local"] and runner.updates == [checkout.root]
    assert decision.plugin == PluginUpdate((Install("local", checkout.root.resolve(), "0.25.0"),), "0.32.2", ("local",))
    assert runner.installs == {("local", checkout.root): "0.32.2", ("local", main): "0.31.1"}
    lines = tick_lines(decision, launched, (), (), dry_run=False)
    assert "  plugin updated: shipmill@shipmill 0.25.0 -> 0.32.2 in this checkout (local scope)" in lines


def test_both_scopes_in_the_checkout_are_updated_project_first(checkout: Git) -> None:
    installs = {("local", checkout.root): "0.25.0", ("project", checkout.root): "0.30.0"}
    runner = FakeRunner(checkout.root, installs=installs)
    decision, _, _, _ = tick(checkout, runner)
    assert runner.scopes == ["project", "local"]
    assert decision.plugin is not None and decision.plugin.updated == ("project", "local")
    assert decision.plugin.error is None
    assert tick_record(decision, "s1", (), (), dry_run=False)["plugin"] == {
        "latest": "0.32.2",
        "installs": [
            {"scope": "project", "installed": "0.30.0", "updated": True},
            {"scope": "local", "installed": "0.25.0", "updated": True},
        ],
        "error": None,
    }


def test_an_update_that_reaches_another_folder_is_reported_and_the_session_starts(checkout: Git) -> None:
    # Claude Code documents no way to name the project an update acts on; were a linked
    # worktree's update to key on its main checkout (#198), the tick says so, not "updated".
    # Spec 031: the install the session loads is still behind, which is reported, not a pause
    main = checkout.root.parent
    installs = {("local", checkout.root): "0.25.0", ("local", main): "0.31.1"}
    runner = FakeRunner(checkout.root, installs=installs, acts_on={checkout.root: main})
    decision, launched, _, _ = tick(checkout, runner)
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    assert decision.plugin is not None and decision.plugin.updated == ()
    assert decision.plugin.error == (
        f"`claude plugin update --scope local` in {checkout.root} left its install at 0.25.0;"
        f" the update changed the local install in {main.resolve()}"
    )
    lines = tick_lines(decision, launched, (), (), dry_run=False)
    assert not any("plugin updated" in line for line in lines)
    assert any("shipmill@shipmill 0.25.0 (local scope" in line and "lags" in line for line in lines)
    assert load_checked(state_dir(checkout) / CHECKED) == NOW  # retried the next day, not every tick


def test_a_user_install_is_never_updated(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version=None, user="0.20.0")  # a behind user install only
    decision, launched, _, _ = tick(checkout, runner)
    assert runner.updates == [] and decision.plugin == PluginUpdate((), None, ())
    assert (decision.action, launched) == (Action.LAUNCH, "s1")  # spec 031: reported, the session starts


def test_the_check_runs_at_most_once_a_day(checkout: Git) -> None:
    runner = FakeRunner(checkout.root)
    tick(checkout, runner)
    runner.calls.clear()
    (state_dir(checkout) / "gate.json").unlink()  # a new launch, not UNCHANGED
    decision, _, _, _ = tick(checkout, runner, now=NOW + dt.timedelta(hours=23))
    assert decision.action is Action.LAUNCH and decision.plugin is None and runner.updates == []
    (state_dir(checkout) / "gate.json").unlink()
    runner.calls.clear()
    decision, _, _, _ = tick(checkout, runner, now=NOW + dt.timedelta(hours=24))
    assert decision.plugin is not None and len(runner.calls) > 2  # checked again; the install is current now


def test_a_failed_update_is_reported_and_the_session_starts_on_the_lagging_install(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, fail_update=True)
    decision, launched, _, _ = tick(checkout, runner)
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    own = (Install("project", checkout.root.resolve(), "0.25.0"),)
    assert decision.plugin == PluginUpdate(own, "0.32.2", (), "claude plugin update failed: network down")
    lines = tick_lines(decision, launched, (), (), dry_run=False)
    assert "  plugin update failed: claude plugin update failed: network down" in lines
    assert load_checked(state_dir(checkout) / CHECKED) == NOW  # retried the next day, not every tick


def test_the_daily_update_refreshes_the_marketplace_once_before_updating(checkout: Git) -> None:
    # #477: `claude plugin update` alone left an install behind; Claude Code updates from its
    # local copy of the marketplace, so it is refreshed first, once for every behind install
    installs = {("local", checkout.root): "0.25.0", ("project", checkout.root): "0.30.0"}
    runner = FakeRunner(checkout.root, installs=installs)
    decision, _, _, _ = tick(checkout, runner)
    claude = [cmd for cmd, _ in runner.calls if cmd[:3] != ["claude", "plugin", "list"] and cmd[0] == "claude"]
    assert claude == [REFRESH, [*UPDATE, "project"], [*UPDATE, "local"]]
    assert decision.plugin is not None and decision.plugin.error is None


def test_a_failed_marketplace_refresh_is_reported_and_the_update_still_runs(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, fail_refresh=True)
    decision, launched, _, _ = tick(checkout, runner)
    assert runner.scopes == ["project"] and launched == "s1"  # the update ran and reached the install
    own = (Install("project", checkout.root.resolve(), "0.25.0"),)
    error = "claude plugin marketplace update failed: offline"
    assert decision.plugin == PluginUpdate(own, "0.32.2", ("project",), error)
    assert f"  plugin update failed: {error}" in tick_lines(decision, launched, (), (), dry_run=False)


def test_no_install_behind_refreshes_no_marketplace(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version="0.32.2")
    tick(checkout, runner)
    assert REFRESH not in [cmd for cmd, _ in runner.calls]


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


def test_a_failed_read_is_reported_and_retried_on_the_next_launch(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, latest="latest")
    decision, launched, _, _ = tick(checkout, runner)
    assert launched == "s1" and decision.plugin is not None and decision.plugin.error is not None
    assert not (state_dir(checkout) / CHECKED).exists()


def test_a_current_install_is_left_alone_and_says_nothing(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version="0.32.2")
    decision, launched, _, _ = tick(checkout, runner)
    own = (Install("project", checkout.root.resolve(), "0.32.2"),)
    assert runner.updates == [] and decision.plugin == PluginUpdate(own, "0.32.2", ())
    assert not any("plugin" in line for line in tick_lines(decision, launched, (), (), dry_run=False))


def test_without_an_install_in_the_checkout_nothing_is_updated(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, installs={("local", checkout.root.parent): "0.20.0"})
    decision, _, _, _ = tick(checkout, runner)
    assert runner.updates == [] and decision.plugin == PluginUpdate((), None, ())


def test_by_default_the_gate_changes_no_install(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version="0.32.2")
    decision, launched, _, _ = tick(checkout, runner, plugin_update=False)
    assert launched == "s1" and runner.updates == [] and decision.plugin is None
    assert tick_record(decision, launched, (), (), dry_run=False)["plugin"] is None


def test_a_dry_run_updates_nothing(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version="0.32.2")
    decision, _, _, _ = tick(checkout, runner, dry=True)
    assert decision.action is Action.LAUNCH and runner.updates == []


def test_a_tick_that_launches_nothing_checks_nothing(checkout: Git) -> None:
    runner = FakeRunner(checkout.root)
    pypi = FakePyPI()
    decision, _, _, _ = gate(
        checkout,
        "romamo/demo",
        lambda: agents(True),
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


def own(text: str, checkout: Path) -> tuple[Install, ...]:
    return checkout_installs(keyed_installs(text), checkout)


def test_only_the_checkouts_own_project_and_local_installs_count() -> None:
    root = Path("/work/r/tmp/shipmill-gate")
    installs = [
        {"id": "shipmill@shipmill", "scope": "project", "version": "0.31.1", "projectPath": "/work/r"},
        {"id": "shipmill@shipmill", "scope": "local", "version": "0.30.0", "projectPath": "/work/r"},
        {"id": "shipmill@shipmill", "scope": "user", "version": "0.20.0"},
        {"id": "other@x", "scope": "project", "version": "1.0.0", "projectPath": str(root)},
    ]
    assert own(json.dumps(installs), root) == ()
    installs.append({"id": "shipmill@shipmill", "scope": "local", "version": "0.20.0", "projectPath": str(root)})
    installs.append({"id": "shipmill@shipmill", "scope": "project", "version": "0.25.0", "projectPath": str(root)})
    assert own(json.dumps(installs), root) == (
        Install("project", root.resolve(), "0.25.0"),
        Install("local", root.resolve(), "0.20.0"),
    )


def test_a_relative_checkout_matches_its_absolute_install(tmp_path: Path) -> None:
    # launchd runs `shipmill --repo tmp/shipmill-gate gate ...`; Claude Code records the full path
    gate = tmp_path / "r" / "tmp" / "shipmill-gate"
    gate.mkdir(parents=True)
    install = {"id": "shipmill@shipmill", "scope": "local", "version": "0.25.0", "projectPath": str(gate.resolve())}
    relative = Path(os.path.relpath(gate))
    assert not relative.is_absolute()
    assert own(json.dumps([install]), relative) == (Install("local", gate.resolve(), "0.25.0"),)


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "{}",
        '["x"]',
        '[{"id": "shipmill@shipmill", "scope": "project"}]',
        '[{"id": "shipmill@shipmill", "scope": "local", "version": "0.25.0"}]',
        '[{"id": "shipmill@shipmill", "scope": "local", "version": "0.25.0", "projectPath": "/w"},'
        ' {"id": "shipmill@shipmill", "scope": "local", "version": "0.26.0", "projectPath": "/w"}]',
    ],
)
def test_a_malformed_plugin_list_is_refused(text: str) -> None:
    with pytest.raises(ReleaseError):
        own(text, Path("/w"))


@pytest.mark.parametrize("text", ["{", '{"checked": 1}', '{"checked": "2026-10-04T12:00:00"}', '{"checked": "x"}'])
def test_a_malformed_check_record_fails(tmp_path: Path, text: str) -> None:
    path = tmp_path / CHECKED
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ReleaseError, match="malformed"):
        daily_update(path, tmp_path, NOW, FakeRunner(tmp_path))


@pytest.mark.parametrize(("value", "expected"), [("true", True), ("false", False)])
def test_the_key_is_read_from_the_config(tmp_path: Path, value: str, expected: bool) -> None:
    write_config(tmp_path, f'[agents]\nprompt = "/t"\nplugin_update = {value}\n')
    assert AgentsConfig.load(tmp_path).plugin_update is expected


def test_the_key_defaults_to_false_and_must_be_a_boolean(tmp_path: Path) -> None:
    write_config(tmp_path, '[agents]\nprompt = "/t"\n')
    assert AgentsConfig.load(tmp_path).plugin_update is False
    write_config(tmp_path, '[agents]\nprompt = "/t"\nplugin_update = "yes"\n')
    with pytest.raises(ReleaseError, match="plugin_update"):
        AgentsConfig.load(tmp_path)


def test_shipmills_own_gate_updates_its_plugin() -> None:
    assert AgentsConfig.load(Path(__file__).resolve().parents[1]).plugin_update is True


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
        checkout, plugin_host(runner, markers_of(checkout)), agents(False, mode=mode), claude
    )
    assert not hasattr(Action, "PLUGIN_STALE")  # no tick reads it
    assert decision.action is Action.LAUNCH
    assert launched is not None and (claude.launched or claude.started)  # the session starts
    assert plugin_lines(decision, launched) == [
        f"  plugin: shipmill@shipmill 0.31.0 ({where}) lags the latest release 0.32.2; the session starts;"
        f" update it: {fix}"
    ]
    assert runner.updates == []  # reported, never updated
    record = tick_record(decision, launched, (), (), dry_run=False)["loaded"]
    assert isinstance(record, dict) and record["lags"] == [
        {"scope": scope, "folder": None if scope == "user" else str(root), "version": "0.31.0", "fix": fix}
    ]


def test_s031_13_every_lagging_install_that_applies_gets_its_line(linked: tuple[Git, Path]) -> None:
    git, main = linked
    runner = FakeRunner(git.root, installs={("local", main): "0.31.1", ("project", main): "0.30.0"}, user="0.29.0")
    decision, launched, _, _ = report_tick(git, plugin_host(runner, git.root.parent / "m"), agents(False))
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
    decision, launched, _, _ = report_tick(git, plugin_host(runner, tmp_path / "m"), agents(False))
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
    assert {tuple(cmd[:3]) for cmd, _ in runner.calls} == {("claude", "plugin", "list"), ("gh", "api", "-H")}


def test_s031_16_a_main_checkouts_own_install_is_never_unloaded(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, installs={("local", checkout.root.resolve()): "0.32.2"}, user=None)
    decision, launched, _, _ = report_tick(checkout, plugin_host(runner, markers_of(checkout)), agents(False))
    assert decision.loaded is not None and decision.loaded.unloaded == ()
    assert plugin_lines(decision, launched) == []


def test_s031_17_the_gates_own_lagging_cli_is_reported_with_its_fix_and_the_session_starts(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version=None, user="0.32.2")
    plugin = plugin_host(runner, markers_of(checkout), cli="0.30.0")
    decision, launched, _, _ = report_tick(checkout, plugin, agents(False))
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    lines = tick_lines(decision, launched, (), (), dry_run=False)
    assert "  the gate's CLI, shipmill 0.30.0, lags the latest release 0.32.2: uv tool upgrade shipmill" in lines
    record = tick_record(decision, launched, (), (), dry_run=False)["loaded"]
    assert isinstance(record, dict) and record["cli"] == {"version": "0.30.0", "fix": "uv tool upgrade shipmill"}
    assert load_cli(state_dir(checkout) / CLI_RECORD) == Version.parse("0.30.0")  # for doctor and status
    current = plugin_host(runner, markers_of(checkout), cli="0.32.2")
    (state_dir(checkout) / "gate.json").unlink()
    decision, launched, _, _ = report_tick(checkout, current, agents(False))
    assert not any("gate's CLI" in line for line in tick_lines(decision, launched, (), (), dry_run=False))


def test_s031_17_a_dry_run_records_no_cli_version(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version=None)
    report_tick(checkout, plugin_host(runner, markers_of(checkout), cli="0.30.0"), agents(False), dry=True)
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
    decision, launched, _, _ = report_tick(checkout, plugin, agents(False))
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
    decision, launched, _, _ = report_tick(checkout, plugin, agents(False))
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
    decision, _, _, _ = report_tick(gates[0], lagging(gates[0], markers), agents(False), notifier=notifier)
    assert notifier.sent == [
        ("shipmill 0.32.2 is out", f"update shipmill@shipmill: 0.31.0 (user scope): {USER_FIX}"),
    ]
    assert (markers / "0.32.2.notified").is_file()
    assert "  notified: shipmill@shipmill lags 0.32.2" in tick_lines(decision, "s1", (), (), dry_run=False)
    decision, launched, _, _ = report_tick(gates[1], lagging(gates[1], markers), agents(False), notifier=notifier)
    assert len(notifier.sent) == 1 and decision.plugin_notice is None and launched == "s1"
    (state_dir(gates[0]) / "gate.json").unlink()  # a new launch, not UNCHANGED
    report_tick(gates[0], lagging(gates[0], markers), agents(False), notifier=notifier)
    assert len(notifier.sent) == 1  # the marker holds for every later tick of any gate


def test_s031_20_notify_false_sends_none_and_writes_no_marker(checkout: Git) -> None:
    notifier = FakeNotifier()
    markers = markers_of(checkout)
    decision, launched, _, _ = report_tick(
        checkout, lagging(checkout, markers), agents(False, notify=False), notifier=notifier
    )
    assert notifier.sent == [] and not markers.exists() and decision.plugin_notice is None
    assert launched == "s1"


def test_s031_20_a_dry_run_sends_none_and_writes_no_marker(checkout: Git) -> None:
    notifier = FakeNotifier()
    markers = markers_of(checkout)
    decision, _, _, _ = report_tick(checkout, lagging(checkout, markers), agents(False), notifier=notifier, dry=True)
    assert notifier.sent == [] and not markers.exists()
    assert decision.plugin_notice == "would notify: shipmill@shipmill lags 0.32.2"


def test_s031_20_a_failed_send_is_reported_and_the_marker_stays(checkout: Git) -> None:
    notifier = FakeNotifier(fail="osascript exited 1")
    markers = markers_of(checkout)
    decision, launched, _, _ = report_tick(checkout, lagging(checkout, markers), agents(False), notifier=notifier)
    assert decision.plugin_notice == "notify failed: osascript exited 1" and launched == "s1"
    assert (markers / "0.32.2.notified").is_file()  # one try per release on the host


def test_s031_20_no_lag_sends_none(checkout: Git) -> None:
    notifier = FakeNotifier()
    markers = markers_of(checkout)
    plugin = plugin_host(FakeRunner(checkout.root, version=None), markers)
    report_tick(checkout, plugin, agents(False), notifier=notifier)
    assert notifier.sent == [] and not markers.exists()


@pytest.mark.parametrize("mode", [Mode.INTERACTIVE, Mode.HEADLESS])
def test_s031_24_a_version_pypi_doesnt_serve_yet_holds_the_tick_and_the_next_retries(checkout: Git, mode: Mode) -> None:
    runner = FakeRunner(checkout.root, version=None, user="0.32.2")
    pypi = FakePyPI(status=404)
    claude = FakeClaude([bg("old", "idle", "done")])
    decision, launched, _, _ = report_tick(
        checkout, plugin_host(runner, markers_of(checkout), pypi=pypi), agents(False, mode=mode), claude
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
        checkout, plugin_host(runner, markers_of(checkout), pypi=pypi), agents(False, mode=mode), claude
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
    decision, launched, _, _ = report_tick(
        checkout, plugin_host(runner, markers_of(checkout), pypi=pypi), agents(False)
    )
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    assert line in tick_lines(decision, launched, (), (), dry_run=False)


def test_s031_24_a_served_version_says_nothing_and_no_install_asks_nothing(checkout: Git) -> None:
    pypi = FakePyPI()
    runner = FakeRunner(checkout.root, version=None, user="0.32.2")
    decision, launched, _, _ = report_tick(
        checkout, plugin_host(runner, markers_of(checkout), pypi=pypi), agents(False)
    )
    assert plugin_lines(decision, launched) == [] and len(pypi.asked) == 1
    none = FakePyPI(status=404)
    (state_dir(checkout) / "gate.json").unlink()
    bare = FakeRunner(checkout.root, version=None, user=None)
    decision, _, _, _ = report_tick(checkout, plugin_host(bare, markers_of(checkout), pypi=none), agents(False))
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
    decision, launched, _, _ = report_tick(checkout, plugin_host(runner, markers_of(checkout)), agents(False))
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    assert decision.loaded is not None and decision.loaded.error is not None
    lines = tick_lines(decision, launched, (), (), dry_run=False)
    assert f"  plugin check failed, the session starts anyway: {decision.loaded.error}" in lines


def test_with_no_install_the_session_starts_and_the_tick_says_so(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version=None, user=None)
    decision, launched, _, _ = report_tick(checkout, plugin_host(runner, markers_of(checkout)), agents(False))
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
