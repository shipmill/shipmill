"""Spec 039: one install of shipmill@shipmill, at user scope. Every fix names `--scope user`,
and the project- and local-scope installs on the host are one PLUGIN_SHADOWING row, whose fix
is plugin-clean, in watch_state.py, doctor, status, setup_state.py, and the tick"""

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from shipmill import requires, status
from shipmill.doctor import Check, PluginRow, doctor, plugin_checks
from shipmill.gate import Action, tick_record
from shipmill.gitrepo import Git
from shipmill.plugin import USER_INSTALL, USER_UPDATE, Listed, Loaded, Scope, Shadow, notify_lags
from shipmill.requires import Requires
from shipmill.version import Version
from tests.conftest import Repo
from tests.test_gate import FakeNotifier
from tests.test_gate_plugin import READS, FakeRunner, agents, plugin_host, plugin_lines, report_tick
from tests.test_status_picture import facts, lines

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
USER_FIX = "claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope user"
REPO = Path("/work/r")
GATE = REPO / "tmp" / "shipmill-gate"


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("watch_state", SKILLS / "github-ship-watch" / "scripts" / "watch_state.py")


@pytest.fixture(scope="module")
def ss() -> ModuleType:
    return load("setup_state", SKILLS / "shipmill-setup" / "scripts" / "setup_state.py")


def install(scope: str, version: str, where: Path | None = None) -> dict[str, object]:
    found: dict[str, object] = {"id": "shipmill@shipmill", "scope": scope, "version": version}
    if where is not None:
        found["projectPath"] = str(where)
    return found


def clean(ws: ModuleType) -> str:
    return f"uvx shipmill=={ws.plugin_version()} plugin-clean"


# -- S-039-1: no command that creates or updates a keyed install ---------------------------------

KEYED = re.compile(r"claude plugin (?:install|update)\b[^`;&|]{0,120}?--scope (?:project|local)\b")
SEARCHED = ("src", "skills", "hooks")


def searched_files() -> list[Path]:
    found = [p for folder in SEARCHED for p in (ROOT / folder).rglob("*") if p.is_file() and p.suffix != ".pyc"]
    return [*found, ROOT / "README.md", ROOT / "docs" / "install.md"]


def test_s039_1_no_file_names_a_project_or_local_install_or_update() -> None:
    hits = []
    for path in searched_files():
        text = " ".join(path.read_text(encoding="utf-8", errors="replace").split())  # one line, as a reader sees it
        hits += [f"{path.relative_to(ROOT)}: {m.group(0)}" for m in KEYED.finditer(text)]
    assert hits == []
    assert KEYED.search("in /w/r: claude plugin update shipmill@shipmill --scope project")  # the pattern bites


def test_s039_1_the_gate_runs_no_plugin_install_update_or_uninstall(tmp_path: Path) -> None:
    source = (ROOT / "src" / "shipmill" / "gate.py").read_text(encoding="utf-8")
    assert not re.search(r"plugin\W+(?:install|update|uninstall)\b", source)
    root = tmp_path / "demo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    git = Git(root)
    git.run("remote", "add", "origin", "https://github.com/romamo/demo.git")
    keyed = {("project", root.resolve()): "0.25.0", ("local", root.resolve()): "0.30.0"}
    runner = FakeRunner(root, installs=keyed, user="0.31.0")
    decision, _, _, _ = report_tick(git, plugin_host(runner, tmp_path / "m"), agents())
    assert decision.action is Action.LAUNCH and runner.ran == READS  # only the list and the marketplace


# -- S-039-2: the user install's single update; requires names --scope user ----------------------


def test_s039_2_a_lagging_user_installs_fix_is_the_single_command_everywhere(
    ws: ModuleType, ss: ModuleType, tmp_path: Path
) -> None:
    assert USER_UPDATE == USER_FIX == ws.USER_UPDATE
    rows = ws.plugin_rows([install("user", "0.31.0")], None, "v0.32.1", [REPO], [GATE], REPO)
    (outdated,) = [r for r in rows if r.state == "SHIPMILL_OUTDATED"]
    assert outdated.fix == USER_FIX and outdated.detail == f"0.31.0, latest v0.32.1; {USER_FIX}"
    # doctor
    found = plugin_checks(lambda: [PluginRow(r.state, r.subject, r.detail) for r in rows])
    assert found[1] == Check("WARN", "plugin", f"plugin user 0.31.0, latest v0.32.1; {USER_FIX}")
    # status
    row = status.Row(outdated.state, outdated.subject, outdated.detail, False, outdated.fix)
    assert status.row_fix("o/r", row) == USER_FIX
    assert f"                 fix: {USER_FIX}" in lines(facts(row)) or any(USER_FIX in x for x in lines(facts(row)))
    # setup_state.py
    fake = type("Ws", (), {"Refused": ws.Refused, "shipmill_rows": staticmethod(lambda repo, root: rows)})
    (shown, *_) = ss.outdated_installs("o/r", REPO, fake)
    assert shown.state == "PLUGIN_OUTDATED" and shown.detail.endswith(f"; {USER_FIX}")
    assert " in /" not in shown.detail.partition("; ")[2]  # no folder named
    # the tick
    root = tmp_path / "demo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    git = Git(root)
    git.run("remote", "add", "origin", "https://github.com/romamo/demo.git")
    runner = FakeRunner(root, version=None, user="0.31.0")
    decision, launched, _, _ = report_tick(git, plugin_host(runner, tmp_path / "m"), agents())
    record = tick_record(decision, launched, (), (), dry_run=False)["loaded"]
    assert isinstance(record, dict) and [lag["fix"] for lag in record["lags"]] == [USER_FIX]


def test_s039_2_requires_names_the_user_scope(ws: ModuleType) -> None:
    said = requires.unmet(">=0.90", "0.82.0")
    assert f"update the plugin: {USER_FIX}\n" in said and "<scope>" not in said
    assert ws.requires_unmet(">=0.90", "0.82.0") == said
    rows = ws.plugin_rows([install("project", "0.31.0", REPO)], None, "v0.32.1", [REPO], [GATE], REPO)
    checks = plugin_checks(lambda: [PluginRow(r.state, r.subject, r.detail) for r in rows], bound=Requires(0, 32))
    (warn,) = [c for c in checks if c.name == "requires"]
    assert warn.status == "WARN" and warn.detail.endswith(
        f"fix: {USER_FIX}; or lower requires in .github/shipmill.toml"
    )


# -- S-039-4, S-039-5: one PLUGIN_SHADOWING row --------------------------------------------------


def test_s039_4_every_keyed_install_on_the_host_is_one_row_at_any_version(ws: ModuleType, tmp_path: Path) -> None:
    here, there = tmp_path / "a", tmp_path / "b" / "tmp" / "shipmill-gate"
    here.mkdir()
    there.mkdir(parents=True)
    keyed = [
        install("project", "0.25.0", here),
        install("local", "0.73.1", here),  # the same folder at another scope
        install("local", "0.82.0", there),  # the latest release shadows too
        install("project", "0.9.0", tmp_path / "gone"),
    ]
    rows = ws.plugin_rows([install("user", "0.82.0"), *keyed], None, "v0.82.0", [REPO], [GATE], REPO)
    assert [r.state for r in rows] == ["SHIPMILL_VERSION", "PLUGIN_SHADOWING"]  # no SHIPMILL_OUTDATED, no S-031-16
    (row,) = [r for r in rows if r.state == "PLUGIN_SHADOWING"]
    assert row.subject == "plugin keyed" and row.fix == clean(ws)
    assert row.detail == (
        "4 project- or local-scope installs of shipmill@shipmill (0.9.0 to 0.82.0, 3 folders, 1 missing)"
        f" shadow the user install; {clean(ws)}"
    )
    assert "PLUGIN_SHADOWING" in ws.ACTION and "PLUGIN_SHADOWING" not in ws.AGENT
    assert row.json()["agent"] is False


def test_s039_4_keyed_installs_get_no_outdated_or_unloaded_row(ws: ModuleType) -> None:
    plugins = [install("user", "0.82.0"), install("project", "0.31.1", REPO), install("local", "0.25.0", GATE)]
    rows = ws.plugin_rows(plugins, None, "v0.82.0", [REPO], [GATE], REPO)
    assert [r.state for r in rows] == ["SHIPMILL_VERSION", "PLUGIN_SHADOWING"]
    assert not any("installed_plugins.json" in r.detail for r in rows)


def test_s039_4_no_keyed_install_no_row(ws: ModuleType) -> None:
    rows = ws.plugin_rows([install("user", "0.80.0"), install("managed", "0.1.0")], None, "v0.82.0", [REPO], [GATE])
    assert "PLUGIN_SHADOWING" not in [r.state for r in rows]
    assert ws.plugin_rows(None, None, "v0.82.0", [REPO], [GATE])[0].state == "SHIPMILL_VERSION"


def test_s039_5_without_a_user_install_the_fix_installs_it_first(ws: ModuleType) -> None:
    rows = ws.plugin_rows([install("local", "0.25.0", REPO)], None, "v0.82.0", [REPO], [GATE], REPO)
    (row,) = [r for r in rows if r.state == "PLUGIN_SHADOWING"]
    assert row.fix == f"{USER_INSTALL} && {clean(ws)}"
    assert row.fix.index("claude plugin install shipmill@shipmill --scope user") < row.fix.index("plugin-clean")
    assert row.detail.endswith(f"with no user install to load in their place; {row.fix}")


# -- S-039-6: doctor, status, setup_state.py -----------------------------------------------------


def shadowing_rows(ws: ModuleType) -> list[PluginRow]:
    plugins = [install("user", "0.82.0"), install("project", "0.25.0", REPO)]
    return [PluginRow(r.state, r.subject, r.detail) for r in ws.plugin_rows(plugins, None, "v0.82.0", [REPO], [GATE])]


def test_s039_6_doctor_warns_under_plugin_and_keeps_its_exit_code(ws: ModuleType, repo: Repo) -> None:
    found = plugin_checks(lambda: shadowing_rows(ws))
    assert found[1].status == "WARN" and found[1].name == "plugin"
    assert found[1].detail.startswith("plugin keyed 1 project- or local-scope install") and clean(ws) in found[1].detail
    with_row = doctor(repo.root, plugins=lambda: shadowing_rows(ws))
    without = doctor(repo.root, plugins=lambda: shadowing_rows(ws)[:1])
    assert [c for c in with_row if c.status == "FAIL"] == [c for c in without if c.status == "FAIL"]


def test_s039_6_status_lists_it_as_waiting_on_you_with_its_fix(ws: ModuleType) -> None:
    plugins = [install("user", "0.82.0"), install("project", "0.25.0", REPO)]
    (row,) = [r for r in ws.plugin_rows(plugins, None, "v0.82.0", [REPO], [GATE]) if r.state == "PLUGIN_SHADOWING"]
    found = facts(status.Row(row.state, row.subject, row.detail, False, row.fix))
    done = status.report(found)
    assert done.verdict is status.Verdict.WAITS
    assert any(r.fix == clean(ws) for r in done.reasons)
    assert "PLUGIN_SHADOWING" in status.YOURS_ROWS
    assert any(clean(ws) in line for line in lines(found))
    assert "PLUGIN_SHADOWING" in load("fleet", SKILLS / "github-ship-watch" / "scripts" / "fleet.py").ACTION


def test_s039_6_setup_state_shows_it_not_done_and_fix_runs_no_plugin_command(ws: ModuleType, ss: ModuleType) -> None:
    plugins = [install("user", "0.82.0"), install("project", "0.25.0", REPO)]
    rows = ws.plugin_rows(plugins, None, "v0.82.0", [REPO], [GATE])
    fake = type("Ws", (), {"Refused": ws.Refused, "shipmill_rows": staticmethod(lambda repo, root: rows)})
    found = ss.outdated_installs("o/r", REPO, fake)
    assert [r.state for r in found] == ["PLUGIN_SHADOWING"]
    assert found[0].text().startswith("PLUGIN_SHADOWING")
    enabled = {"enabledPlugins": {"shipmill@shipmill": True}}
    assert ss.plugin_rows(enabled, lambda: found) == found
    assert ss.exit_code([ss.Row("RELEASE_READY", ""), *found]) == 1
    source = (SKILLS / "shipmill-setup" / "scripts" / "setup_state.py").read_text(encoding="utf-8")
    # the only claude command it runs is the list: --fix leaves the installs as they were
    assert not re.search(r"\"plugin\",\s*\"(?:install|update|uninstall)\"", source)


# -- S-039-7: the tick -----------------------------------------------------------------------------


@pytest.mark.parametrize("scope", ["project", "local"])
@pytest.mark.parametrize("version", ["0.31.0", "0.32.2"])
def test_s039_7_a_tick_whose_session_loads_a_keyed_install_reports_plugin_clean_and_starts(
    tmp_path: Path, scope: str, version: str
) -> None:
    root = tmp_path / "demo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    git = Git(root)
    git.run("remote", "add", "origin", "https://github.com/romamo/demo.git")
    runner = FakeRunner(root, installs={(scope, root.resolve()): version}, user="0.32.2")
    decision, launched, _, _ = report_tick(git, plugin_host(runner, tmp_path / "m"), agents())
    assert decision.action is Action.LAUNCH and launched is not None
    assert decision.loaded is not None and decision.loaded.install is not None
    assert decision.loaded.install.scope == scope  # the session loads the keyed install
    fix = f"uvx shipmill=={requires.running()} plugin-clean"
    assert plugin_lines(decision, launched) == [
        f"  plugin: shipmill@shipmill {version} ({scope} scope, keyed on {root.resolve()}) is a {scope}-scope"
        f" install, which shadows the user install in its folder; the session starts; fix: {fix}"
    ]
    record = tick_record(decision, launched, (), (), dry_run=False)["loaded"]
    assert isinstance(record, dict) and [s["fix"] for s in record["shadowing"]] == [fix]
    assert runner.ran == READS


def test_s039_7_the_release_notification_names_plugin_clean_for_a_lagging_keyed_install(tmp_path: Path) -> None:
    keyed = Listed(Scope.PROJECT, tmp_path, Version.parse("0.31.0"))
    fix = f"uvx shipmill=={requires.running()} plugin-clean"
    found = Loaded(tmp_path, keyed, Version.parse("0.32.2"), shadowing=(Shadow(keyed, fix),))
    notifier = FakeNotifier()
    assert notify_lags(found, tmp_path / "m", notifier, dry_run=False) == "notified: shipmill@shipmill lags 0.32.2"
    assert notifier.sent == [
        ("shipmill 0.32.2 is out", f"update shipmill@shipmill: 0.31.0 (project scope, keyed on {tmp_path}): {fix}")
    ]
    current = Loaded(tmp_path, keyed, Version.parse("0.31.0"), shadowing=(Shadow(keyed, fix),))
    assert notify_lags(current, tmp_path / "n", FakeNotifier(), dry_run=False) is None  # nothing lags


# -- S-039-15: the docs ----------------------------------------------------------------------------

DOCS = (ROOT / "docs" / "install.md", SKILLS / "shipmill-setup" / "SKILL.md", SKILLS / "github-ship-watch" / "SKILL.md")


@pytest.mark.parametrize("path", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_s039_15_the_docs_describe_one_user_install_the_row_and_plugin_clean(path: Path) -> None:
    text = " ".join(path.read_text(encoding="utf-8").split())
    assert "user scope" in text or "user-scope" in text
    assert "PLUGIN_SHADOWING" in text and "plugin-clean" in text
    assert USER_FIX in text
    assert not KEYED.search(text)
    assert not re.search(r"run in (?:the|its) folder|reinstall|in the folder it names", text)
