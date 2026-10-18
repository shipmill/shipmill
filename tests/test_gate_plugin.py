"""#233, #240, D-23: with [agents] plugin_update = true the gate updates every plugin install
keyed on its checkout, at project or local scope, at most once a day, before it starts a session"""

import datetime as dt
import json
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig, Mode
from shipmill.autonomy import Hold
from shipmill.errors import ReleaseError
from shipmill.gate import Action, Decision, Waiting, gate, state_dir, tick_lines, tick_record
from shipmill.gitrepo import Git
from shipmill.plugin import (
    CHECKED,
    Install,
    Listed,
    PluginUpdate,
    checkout_installs,
    daily_update,
    effective,
    keyed_installs,
    listed_installs,
    load_checked,
    session_project,
)
from shipmill.worktrees import Judged

from .test_gate import ISSUES, NO_PRUNE, NOW, FakeClaude, FakeNotifier, bg, host, write_config

Tick = tuple[Decision, str | None, tuple[Waiting, ...], tuple[Judged, ...]]
UPDATE = ["claude", "plugin", "update", "shipmill@shipmill", "--scope"]


@dataclass
class FakeRunner:
    """claude plugin list, gh release view, and claude plugin update, without either tool.
    installs maps (scope, folder) to a version; an update at a scope run in cwd sets the
    install keyed on `acts_on(cwd)` (the cwd itself by default) to the latest release"""

    checkout: Path
    version: str | None = "0.25.0"  # the checkout's project install; None: none
    latest: str = "v0.32.2"
    fail_update: bool = False
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
        if cmd[:3] == ["gh", "release", "view"]:
            return self.latest + "\n"
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


@pytest.fixture
def checkout(tmp_path: Path) -> Git:
    root = tmp_path / "demo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    git = Git(root)
    git.run("remote", "add", "origin", "https://github.com/romamo/demo.git")
    return git


def agents(plugin_update: bool) -> AgentsConfig:
    return AgentsConfig(prompt="/t", prs=False, retry_hours=24, plugin_update=plugin_update)


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
        plugins=runner,
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


def test_an_update_that_reaches_another_folder_is_reported_and_no_session_starts(checkout: Git) -> None:
    # Claude Code documents no way to name the project an update acts on; were a linked
    # worktree's update to key on its main checkout (#198), the tick says so, not "updated".
    # #417, D-35: the install the session would load is still behind, so none starts
    main = checkout.root.parent
    installs = {("local", checkout.root): "0.25.0", ("local", main): "0.31.1"}
    runner = FakeRunner(checkout.root, installs=installs, acts_on={checkout.root: main})
    decision, launched, _, _ = tick(checkout, runner)
    assert (decision.action, launched) == (Action.PLUGIN_STALE, None)
    assert decision.plugin is not None and decision.plugin.updated == ()
    assert decision.plugin.error == (
        f"`claude plugin update --scope local` in {checkout.root} left its install at 0.25.0;"
        f" the update changed the local install in {main.resolve()}"
    )
    lines = tick_lines(decision, launched, (), (), dry_run=False)
    assert not any("plugin updated" in line for line in lines)
    assert load_checked(state_dir(checkout) / CHECKED) == NOW  # retried the next day, not every tick


def test_a_user_install_is_never_updated(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version=None, user="0.20.0")  # a behind user install only
    decision, _, _, _ = tick(checkout, runner)
    assert runner.updates == [] and decision.plugin == PluginUpdate((), None, ())
    assert decision.action is Action.PLUGIN_STALE  # D-35: the session would load it, so none starts


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


def test_a_failed_update_is_reported_and_no_session_starts_on_the_stale_install(checkout: Git) -> None:
    # #417, D-35: D-23's "the session starts anyway" no longer holds for the install it loads
    runner = FakeRunner(checkout.root, fail_update=True)
    decision, launched, _, _ = tick(checkout, runner)
    assert (decision.action, launched) == (Action.PLUGIN_STALE, None)
    own = (Install("project", checkout.root.resolve(), "0.25.0"),)
    assert decision.plugin == PluginUpdate(own, "0.32.2", (), "claude plugin update failed: network down")
    lines = tick_lines(decision, launched, (), (), dry_run=False)
    assert "  plugin update failed: claude plugin update failed: network down" in lines
    assert load_checked(state_dir(checkout) / CHECKED) == NOW  # retried the next day, not every tick


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
        plugins=runner,
    )
    assert decision.action is Action.QUIET and runner.calls == []


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


# #417, D-35: the gate starts no session on a shipmill plugin older than the latest release,
# reading the install a session in its checkout would load, at any scope


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


def stale_tick(git: Git, runner: FakeRunner, config: AgentsConfig, claude: FakeClaude | None = None) -> Tick:
    return gate(
        git,
        "romamo/demo",
        lambda: config,
        claude or FakeClaude([bg("old", "idle", "done")]),
        lambda _: [ISSUES],
        NOW,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        login=host,
        started=lambda _: "Sat Oct  4 12:00:00 2026",
        new_session=lambda: uuid.UUID(int=1),
        plugins=runner,
    )


def test_the_gate_checkouts_stale_install_on_its_main_checkout_starts_no_session(linked: tuple[Git, Path]) -> None:
    # #417: the main checkout's local install is the one a session in the linked gate checkout
    # loads; the leftover keyed on the worktree itself is never loaded
    git, main = linked
    gate_dir = git.root.resolve()
    installs = {("local", main): "0.31.1", ("local", gate_dir): "0.25.0"}
    runner = FakeRunner(gate_dir, installs=installs, user="0.32.2")
    claude = FakeClaude([bg("old", "idle", "done")])
    decision, launched, _, _ = stale_tick(git, runner, agents(False), claude)
    assert (decision.action, launched) == (Action.PLUGIN_STALE, None)
    assert claude.launched == [] and claude.stopped == []  # no session stops or starts
    fix = (
        f"in {main}: claude plugin uninstall shipmill@shipmill --scope local && claude plugin install"
        f" shipmill@shipmill --scope local (`update` picks the nested install in {gate_dir}, a Claude Code bug)"
    )
    assert decision.reason == (
        f"a session here would load shipmill@shipmill 0.31.1 (local scope, keyed on {main}), older than the"
        f" latest release 0.32.2: no session starts until it is updated: {fix}"
    )
    lines = tick_lines(decision, launched, (), (), dry_run=False)
    assert lines[0] == f"PLUGIN_STALE: {decision.reason}"
    record = tick_record(decision, launched, (), (), dry_run=False)
    assert record["action"] == "PLUGIN_STALE" and record["stopped"] == [] and record["launched"] is None
    assert record["loaded"] == {
        "project": str(main),
        "scope": "local",
        "folder": str(main),
        "version": "0.31.1",
        "latest": "0.32.2",
        "stale": True,
        "fix": fix,
        "error": None,
    }
    assert not (state_dir(git) / "gate.json").exists()  # no launch recorded: the next tick tries again


def test_a_current_main_checkout_install_launches_beside_a_stale_leftover(linked: tuple[Git, Path]) -> None:
    git, main = linked
    installs = {("local", main): "0.32.2", ("local", git.root.resolve()): "0.25.0"}
    runner = FakeRunner(git.root, installs=installs, user="0.20.0")
    decision, launched, _, _ = stale_tick(git, runner, agents(False))
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    assert decision.loaded is not None and decision.loaded.install is not None
    assert (decision.loaded.install.scope, str(decision.loaded.install.version)) == ("local", "0.32.2")
    assert not any("plugin" in line for line in tick_lines(decision, launched, (), (), dry_run=False))


@pytest.mark.parametrize("mode", [Mode.INTERACTIVE, Mode.HEADLESS])
def test_a_stale_user_install_starts_no_session_in_either_mode(checkout: Git, mode: Mode) -> None:
    runner = FakeRunner(checkout.root, version=None, user="0.31.0")
    claude = FakeClaude([bg("old", "idle", "done")])
    config = AgentsConfig(prompt="/t", prs=False, retry_hours=24, mode=mode)
    decision, launched, _, _ = stale_tick(checkout, runner, config, claude)
    assert (decision.action, launched) == (Action.PLUGIN_STALE, None)
    assert claude.launched == [] and claude.started == [] and claude.stopped == []
    assert decision.reason.endswith(
        "(user scope), older than the latest release 0.32.2: no session starts until it is updated:"
        " claude plugin update shipmill@shipmill --scope user"
    )
    assert runner.updates == []  # the gate never updates a user-scope install


def test_the_next_tick_with_a_current_install_launches(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version=None, user="0.31.0")
    decision, _, _, _ = stale_tick(checkout, runner, agents(False))
    assert decision.action is Action.PLUGIN_STALE
    runner.user = "0.32.2"  # a person ran the fix
    decision, launched, _, _ = stale_tick(checkout, runner, agents(False))
    assert (decision.action, launched) == (Action.LAUNCH, "s1")


def test_the_daily_update_runs_first_so_an_updated_install_launches(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, installs={("local", checkout.root): "0.25.0"}, user="0.20.0")
    decision, launched, _, _ = stale_tick(checkout, runner, agents(True))
    assert (decision.action, launched) == (Action.LAUNCH, "s1") and runner.scopes == ["local"]


def test_a_failed_latest_release_read_is_reported_and_the_session_starts(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, latest="latest")  # not a version tag: the read fails
    decision, launched, _, _ = stale_tick(checkout, runner, agents(False))
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    assert decision.loaded is not None and decision.loaded.error is not None
    lines = tick_lines(decision, launched, (), (), dry_run=False)
    assert f"  plugin check failed, the session starts anyway: {decision.loaded.error}" in lines


def test_with_no_install_the_session_starts_and_the_tick_says_so(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version=None, user=None)
    decision, launched, _, _ = stale_tick(checkout, runner, agents(False))
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    lines = tick_lines(decision, launched, (), (), dry_run=False)
    assert (
        f"  plugin: no shipmill@shipmill install applies to {checkout.root.resolve()}; the session loads no"
        " shipmill skills"
    ) in lines


def test_a_dry_run_reports_a_stale_install_too(checkout: Git) -> None:
    runner = FakeRunner(checkout.root, version=None, user="0.31.0")
    decision, _, _, _ = tick(checkout, runner, plugin_update=False, dry=True)
    assert decision.action is Action.PLUGIN_STALE and runner.updates == []


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
