"""doctor reports the shipmill plugin's installs as `status` does (D-22, #233): the rows and fix
text come from github-ship-watch's watch_state.py, fed here without claude, gh, or the network"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from shipmill.cli import _doctor_repo
from shipmill.doctor import Check, PluginRow, doctor, plugin_checks
from shipmill.errors import ReleaseError
from tests.conftest import Repo

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
REPO = Path("/work/r")
GATE = REPO / "tmp" / "shipmill-gate"


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    spec = importlib.util.spec_from_file_location("watch_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


def install(scope: str, version: str, where: Path | None = None) -> dict[str, object]:
    found: dict[str, object] = {"id": "shipmill@shipmill", "scope": scope, "version": version}
    if where is not None:
        found["projectPath"] = str(where)
    return found


def checked(ws: ModuleType, plugins: object) -> list[Check]:
    """doctor's plugin checks for watch_state's rows of these installs, latest v0.32.1"""
    rows = ws.plugin_rows(plugins, None, "v0.32.1", [REPO], [GATE])
    return plugin_checks(lambda: [PluginRow(r.state, r.subject, r.detail) for r in rows])


def test_a_behind_install_in_the_repo_and_the_gate_checkout_warns_with_statuss_fix(ws: ModuleType) -> None:
    """D-22: separate rows for the repo's folder and the gate's checkout, each with its fix"""
    found = checked(ws, [install("project", "0.31.1", REPO), install("project", "0.25.0", GATE)])
    assert [c.status for c in found] == ["PASS", "WARN", "WARN"]
    assert found[1] == Check(
        "WARN",
        "plugin",
        "plugin project 0.31.1, latest v0.32.1; in /work/r: claude plugin marketplace update shipmill"
        " && claude plugin uninstall shipmill@shipmill --scope project && claude plugin install shipmill@shipmill"
        " --scope project (`update` picks the nested install in /work/r/tmp/shipmill-gate, a Claude Code bug)",
    )
    assert found[2].detail == (
        "plugin project 0.25.0, latest v0.32.1; in /work/r/tmp/shipmill-gate:"
        " claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope project"
    )


def test_a_current_install_passes(ws: ModuleType) -> None:
    found = checked(ws, [install("user", "0.32.1"), install("project", "0.32.1", GATE)])
    assert found == [Check("PASS", "plugin", f"latest v0.32.1; plugin: user 0.32.1, project 0.32.1 ({GATE})")]


def test_nothing_installed_is_an_info_row(ws: ModuleType) -> None:
    found = checked(ws, [])
    assert found == [Check("PASS", "plugin", "latest v0.32.1; plugin: not installed for this repo on this host")]


def test_without_claude_the_installs_are_skipped_not_failed(ws: ModuleType) -> None:
    found = checked(ws, None)
    assert found == [Check("PASS", "plugin", "latest v0.32.1; plugin: claude isn't on PATH, not read")]


def test_the_install_a_session_loads_is_named_and_warns_when_behind(ws: ModuleType) -> None:
    # #417, D-35: the gate's linked checkout loads the main checkout's local install, not the
    # leftover keyed on the worktree; when it is behind, the gate starts no session
    plugins = [install("user", "0.32.1"), install("local", "0.31.0", REPO), install("local", "0.25.0", GATE)]
    rows = ws.plugin_rows(plugins, None, "v0.32.1", [REPO], [GATE], REPO)
    found = plugin_checks(lambda: [PluginRow(r.state, r.subject, r.detail) for r in rows])
    assert found[0] == Check(
        "WARN",
        "plugin",
        f"latest v0.32.1; plugin: user 0.32.1, local 0.31.0 ({REPO}), local 0.25.0 ({GATE}); a session loads"
        f" local 0.31.0 ({REPO}), older than v0.32.1: the gate starts no session (D-35)",
    )
    current = [install("user", "0.31.0"), install("local", "0.32.1", REPO)]
    rows = ws.plugin_rows(current, None, "v0.32.1", [REPO], [GATE], REPO)
    assert rows[0].detail.endswith(f"; a session loads local 0.32.1 ({REPO})")
    assert plugin_checks(lambda: [PluginRow(r.state, r.subject, r.detail) for r in rows])[0].status == "PASS"


def test_a_failed_read_warns_and_doctor_goes_on(repo: Repo) -> None:
    def fails() -> list[PluginRow]:
        raise ReleaseError("gh release view failed: offline")

    checks = doctor(repo.root, plugins=fails)
    warned = "can't read the shipmill plugin's installs: gh release view failed: offline"
    assert Check("WARN", "plugin", warned) in checks
    assert checks[0].name == "policy"


def test_doctor_without_a_reader_checks_no_plugin(repo: Repo) -> None:
    assert "plugin" not in {c.name for c in doctor(repo.root)}


def test_a_checkout_without_a_github_origin_reads_no_plugin_rows(repo: Repo) -> None:
    assert _doctor_repo(repo.root) is None  # a local bare origin
    repo.git.run("remote", "set-url", "origin", "git@github.com:acme/api.git")
    assert _doctor_repo(repo.root) == "acme/api"
    repo.git.run("remote", "remove", "origin")
    assert _doctor_repo(repo.root) is None  # never a crash: doctor's remote check reports it
