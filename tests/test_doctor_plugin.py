"""doctor reports the shipmill plugin's installs as `status` does (D-22, #233): the rows and fix
text come from github-ship-watch's watch_state.py, fed here without claude, gh, or the network"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from shipmill.cli import _doctor_repo
from shipmill.doctor import Check, PluginRow, PluginRows, doctor, plugin_checks
from shipmill.errors import ReleaseError
from shipmill.plugin import Fetch, GateCli
from shipmill.requires import Requires
from shipmill.version import Version
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


UNLOADED = (
    f'delete the entry with "projectPath": "{GATE}" under "shipmill@shipmill"'
    " in ~/.claude/plugins/installed_plugins.json"
)


def test_s031_16_the_repos_install_and_one_keyed_on_the_gates_worktree_warn_with_statuss_fix(ws: ModuleType) -> None:
    """D-22: separate rows for the repo's folder and the gate's checkout, each with its fix;
    the gate's linked worktree is no session's project, so its install is deleted by hand"""
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
        f"plugin project 0.25.0, keyed on the gate's linked worktree {GATE}, which no session loads; {UNLOADED}"
    )


def test_s031_16_a_current_install_keyed_on_the_gates_worktree_still_warns(ws: ModuleType) -> None:
    found = checked(ws, [install("user", "0.32.1"), install("local", "0.32.1", GATE)])
    assert [c.status for c in found] == ["PASS", "WARN"] and found[1].detail.endswith(UNLOADED)


def test_a_current_install_passes(ws: ModuleType) -> None:
    found = checked(ws, [install("user", "0.32.1"), install("project", "0.32.1", REPO)])
    assert found == [Check("PASS", "plugin", f"latest v0.32.1; plugin: user 0.32.1, project 0.32.1 ({REPO})")]


@pytest.mark.parametrize(
    ("scope", "where", "fix"),
    [
        (
            "user",
            None,
            "claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope user",
        ),
        (
            "project",
            REPO,
            "in /work/r: claude plugin marketplace update shipmill"
            " && claude plugin update shipmill@shipmill --scope project",
        ),
        (
            "local",
            REPO,
            "in /work/r: claude plugin marketplace update shipmill"
            " && claude plugin update shipmill@shipmill --scope local",
        ),
    ],
)
def test_s031_15_each_lagging_install_warns_with_its_fix_and_none_says_the_gate_pauses(
    ws: ModuleType, scope: str, where: Path | None, fix: str
) -> None:
    rows = ws.plugin_rows([install(scope, "0.31.0", where)], None, "v0.32.1", [REPO], [GATE], REPO)
    found = plugin_checks(lambda: [PluginRow(r.state, r.subject, r.detail) for r in rows])
    assert found[1] == Check("WARN", "plugin", f"plugin {scope} 0.31.0, latest v0.32.1; {fix}")
    assert not any("starts no session" in c.detail or "D-35" in c.detail for c in found)


def test_nothing_installed_is_an_info_row(ws: ModuleType) -> None:
    found = checked(ws, [])
    assert found == [Check("PASS", "plugin", "latest v0.32.1; plugin: not installed for this repo on this host")]


def test_without_claude_the_installs_are_skipped_not_failed(ws: ModuleType) -> None:
    found = checked(ws, None)
    assert found == [Check("PASS", "plugin", "latest v0.32.1; plugin: claude isn't on PATH, not read")]


def test_s031_15_the_install_a_session_loads_is_named_and_its_lag_is_reported_not_a_pause(ws: ModuleType) -> None:
    # #417: the gate's linked checkout loads the main checkout's local install, not the leftover
    # keyed on the worktree; spec 031: when it is behind, its own row warns and the gate still runs
    plugins = [install("user", "0.32.1"), install("local", "0.31.0", REPO), install("local", "0.25.0", GATE)]
    rows = ws.plugin_rows(plugins, None, "v0.32.1", [REPO], [GATE], REPO)
    found = plugin_checks(lambda: [PluginRow(r.state, r.subject, r.detail) for r in rows])
    assert found[0] == Check(
        "PASS",
        "plugin",
        f"latest v0.32.1; plugin: user 0.32.1, local 0.31.0 ({REPO}), local 0.25.0 ({GATE}); a session loads"
        f" local 0.31.0 ({REPO}), older than v0.32.1",
    )
    assert [c.status for c in found] == ["PASS", "WARN", "WARN"]  # the lagging install, the unloaded one
    current = [install("user", "0.31.0"), install("local", "0.32.1", REPO)]
    rows = ws.plugin_rows(current, None, "v0.32.1", [REPO], [GATE], REPO)
    assert rows[0].detail.endswith(f"; a session loads local 0.32.1 ({REPO})")
    assert plugin_checks(lambda: [PluginRow(r.state, r.subject, r.detail) for r in rows])[0].status == "PASS"


def session_rows(ws: ModuleType, version: str) -> PluginRows:
    rows = ws.plugin_rows([install("user", version)], None, "v0.32.1", [REPO], [GATE], REPO)
    return lambda: [PluginRow(r.state, r.subject, r.detail) for r in rows]


@pytest.mark.parametrize(
    ("cli", "warned"),
    [
        (GateCli(Version.parse("0.30.0"), "uv tool upgrade shipmill"), True),
        (GateCli(Version.parse("0.30.0"), "uvx shipmill@latest --repo /g launchd o/r"), True),
        (GateCli(Version.parse("0.32.1"), "uv tool upgrade shipmill"), False),
        (None, False),
    ],
)
def test_s031_17_the_gates_lagging_cli_warns_with_its_fix(ws: ModuleType, cli: GateCli | None, warned: bool) -> None:
    found = [c for c in plugin_checks(session_rows(ws, "0.32.1"), cli) if c.name == "gate cli"]
    if not warned:
        assert found == []
        return
    assert cli is not None
    assert found == [
        Check("WARN", "gate cli", f"the gate's CLI, shipmill 0.30.0, lags the latest release 0.32.1: {cli.fix}")
    ]


@pytest.mark.parametrize(
    ("version", "bound", "fix"),
    [
        (
            "0.31.0",
            ">=0.32",
            "claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope user;"
            " or lower requires in .github/shipmill.toml",
        ),
        ("0.32.1", ">=0.33", "release shipmill 0.33.0 or later, or lower requires in .github/shipmill.toml"),
    ],
)
def test_s031_19_doctor_warns_when_the_version_sessions_load_misses_requires(
    ws: ModuleType, version: str, bound: str, fix: str
) -> None:
    found = [c for c in plugin_checks(session_rows(ws, version), None, Requires.parse(bound)) if c.name == "requires"]
    assert found == [
        Check(
            "WARN",
            "requires",
            f".github/shipmill.toml requires shipmill {bound}, but sessions in the gate's folder load"
            f" shipmill@shipmill {version} (user scope), whose shipmill commands refuse the config; fix: {fix}",
        )
    ]
    met = plugin_checks(session_rows(ws, "0.32.1"), None, Requires.parse(">=0.32"))
    assert "requires" not in {c.name for c in met}


PUBLISH = (
    "check the publish.yml run for v0.32.1: gh run list --repo shipmill/shipmill --workflow publish.yml;"
    " if none passed, publish it: gh workflow run publish.yml --repo shipmill/shipmill -f tag=v0.32.1"
)


def answers(status: int | None) -> Fetch:
    def fetch(url: str) -> int:
        assert url == "https://pypi.org/pypi/shipmill/0.32.1/json"
        if status is None:
            raise ReleaseError("timed out")
        return status

    return fetch


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (
            404,
            Check(
                "FAIL",
                "pypi",
                "plugin 0.32.1 waits for PyPI: https://pypi.org/pypi/shipmill/0.32.1/json answers 404, so the gate"
                f" starts no session until it serves it; fix: {PUBLISH}",
            ),
        ),
        (200, Check("PASS", "pypi", "PyPI serves shipmill 0.32.1, the version sessions load")),
        (
            503,
            Check(
                "WARN",
                "pypi",
                "plugin 0.32.1: PyPI answered 503 for https://pypi.org/pypi/shipmill/0.32.1/json;"
                " the session starts anyway",
            ),
        ),
        (None, Check("WARN", "pypi", "plugin 0.32.1: PyPI didn't answer (timed out); the session starts anyway")),
    ],
)
def test_doctor_asks_pypi_for_the_version_sessions_load(ws: ModuleType, answer: int | None, expected: Check) -> None:
    # #569: the one plugin check that holds the gate is a FAIL with the publish fix; a failed read warns
    found = [c for c in plugin_checks(session_rows(ws, "0.32.1"), pypi=answers(answer)) if c.name == "pypi"]
    assert found == [expected]


def test_doctor_asks_pypi_nothing_when_no_install_is_loaded(ws: ModuleType) -> None:
    def never(url: str) -> int:
        raise AssertionError(url)

    rows = ws.plugin_rows([], None, "v0.32.1", [REPO], [GATE], REPO)
    found = plugin_checks(lambda: [PluginRow(r.state, r.subject, r.detail) for r in rows], pypi=never)
    assert "pypi" not in {c.name for c in found}
    assert "pypi" not in {c.name for c in plugin_checks(session_rows(ws, "0.32.1"))}


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
