"""Spec 031, "The person's CLI on PATH" (#583): `shipmill --version`, and watch_state.py's
`shipmill on PATH` row against the install a session loads, as doctor and status show it.
Every PATH here is a folder the test makes, holding fake `shipmill` scripts, never the real one"""

import importlib.metadata
import importlib.util
import subprocess
import sys
import sysconfig
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.doctor import PluginRow, plugin_checks
from shipmill.status import Row, Verdict, report
from tests.test_status_picture import facts, lines

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
REPO = Path("/work/r")
GATE = REPO / "tmp" / "shipmill-gate"
UPGRADE = "uv tool upgrade shipmill"
USER_UPDATE = "claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope user"


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    spec = importlib.util.spec_from_file_location("watch_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


def fake(folder: Path, body: str) -> Path:
    """A `shipmill` in folder that runs body under /bin/sh"""
    folder.mkdir(parents=True, exist_ok=True)
    program = folder / "shipmill"
    program.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    program.chmod(0o755)
    return program


def install(scope: str, version: str, where: Path | None = None) -> dict[str, object]:
    found: dict[str, object] = {"id": "shipmill@shipmill", "scope": scope, "version": version}
    if where is not None:
        found["projectPath"] = str(where)
    return found


def reader(ws: ModuleType, path: Path, env: Path) -> Callable[[], object]:
    """path_cli on a PATH of one folder, with env as the environment running the check"""
    return lambda: ws.path_cli(str(path), (env,))


def person(rows: list[Any]) -> list[Any]:
    """watch_state.py's rows about the person's CLI"""
    return [r for r in rows if r.subject == "shipmill on PATH"]


def doctor_rows(rows: list[Any]) -> list[PluginRow]:
    return [PluginRow(r.state, r.subject, r.detail) for r in rows]


def test_s031_25_version_prints_the_package_version_without_a_repo_command_or_config(tmp_path: Path) -> None:
    scripts = Path(sysconfig.get_path("scripts"))
    assert not (tmp_path / ".github" / "shipmill.toml").exists()
    out = subprocess.run(
        [str(scripts / "shipmill"), "--version"], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert (out.returncode, out.stdout) == (0, f"shipmill {importlib.metadata.version('shipmill')}\n")


def test_s031_26_an_older_shipmill_on_path_is_a_row_with_uvs_upgrade(ws: ModuleType, tmp_path: Path) -> None:
    program = fake(tmp_path / "bin", 'echo "shipmill 0.40.0"')
    plugins = [install("user", "0.67.0")]
    rows = ws.plugin_rows(plugins, None, "v0.67.0", [REPO], [GATE], REPO, reader(ws, tmp_path / "bin", tmp_path / "e"))
    (row,) = person(rows)
    assert (row.state, row.detail, row.fix) == (
        "SHIPMILL_OUTDATED",
        f"{program} is 0.40.0, the plugin is 0.67.0; {UPGRADE}",
        UPGRADE,
    )
    assert row.text().splitlines() == [f"SHIPMILL_OUTDATED shipmill on PATH {row.detail}"]


@pytest.mark.parametrize(
    ("loaded", "fix"),
    [
        (install("user", "0.67.0"), USER_UPDATE),
        (
            install("local", "0.67.0", REPO),
            f"in {REPO}: claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill"
            " --scope local",
        ),
    ],
)
def test_s031_26_a_newer_shipmill_on_path_names_the_loaded_installs_update(
    ws: ModuleType, tmp_path: Path, loaded: dict[str, object], fix: str
) -> None:
    program = fake(tmp_path / "bin", 'echo "shipmill 0.70.0"')
    rows = ws.plugin_rows([loaded], None, "v0.70.0", [REPO], [GATE], REPO, reader(ws, tmp_path / "bin", tmp_path / "e"))
    (row,) = person(rows)
    assert (row.detail, row.fix) == (f"{program} is 0.70.0, the plugin is 0.67.0; {fix}", fix)


def test_s031_26_the_same_version_gives_no_row_and_versions_compare_as_numbers(ws: ModuleType, tmp_path: Path) -> None:
    fake(tmp_path / "bin", 'echo "shipmill 0.67.0"')
    plugins = [install("user", "0.67.0")]
    rows = ws.plugin_rows(plugins, None, "v0.67.0", [REPO], [GATE], REPO, reader(ws, tmp_path / "bin", tmp_path / "e"))
    assert person(rows) == []
    # 0.9.0 is older than 0.10.0, though it sorts after it as a string
    older = ws.path_cli_row(ws.PathCli(Path("/b/shipmill"), "0.9.0"), "0.10.0", USER_UPDATE)
    assert older.fix == UPGRADE


def test_s031_26_a_folder_whose_shipmill_resolves_into_the_running_environment_is_skipped(
    ws: ModuleType, tmp_path: Path
) -> None:
    env = tmp_path / "env"
    own = fake(env / "bin", 'echo "shipmill 0.10.0"')
    (tmp_path / "linked").mkdir()
    (tmp_path / "linked" / "shipmill").symlink_to(own)
    outside = fake(tmp_path / "tool", 'echo "shipmill 0.40.0"')
    path = ":".join(str(tmp_path / d) for d in ("linked", "env/bin", "tool"))
    assert ws.path_shipmill(path, (env,)) == outside
    assert ws.path_shipmill(path, (tmp_path / "other",)) == tmp_path / "linked" / "shipmill"  # as PATH names it
    assert ws.path_cli(":".join(str(tmp_path / d) for d in ("linked", "env/bin")), (env,)) is None


def test_s031_26_a_relative_path_entry_never_runs_a_shipmill_from_the_working_folder(tmp_path: Path) -> None:
    """A relative PATH entry (`.`, `bin`) names a folder under the working folder, a checkout
    that may be a pull request's: its `shipmill` is never the person's CLI, so it is never run"""
    fake(tmp_path, 'echo "shipmill 0.40.0"')
    fake(tmp_path / "bin", 'echo "shipmill 0.40.0"')
    tool = fake(tmp_path / "tool", 'echo "shipmill 0.41.0"')
    load = (
        "import importlib.util, sys; from pathlib import Path;"
        f"s = importlib.util.spec_from_file_location('ws', {str(SCRIPT)!r}); m = importlib.util.module_from_spec(s);"
        "sys.modules['ws'] = m; s.loader.exec_module(m);"
        f"print(m.path_shipmill(sys.argv[1], (Path({str(tmp_path / 'e')!r}),)))"
    )
    for path in (".", "bin", f".:bin:{tmp_path / 'tool'}"):
        out = subprocess.run(
            [sys.executable, "-c", load, path], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert out == (str(tool) if "tool" in path else "None"), path


def test_s031_26_another_uvx_runs_environment_is_skipped_and_a_tool_install_is_not(
    ws: ModuleType, tmp_path: Path
) -> None:
    # the gate's `uvx shipmill@latest` puts its cache environment's bin first on its sessions' PATH
    archive = tmp_path / "cache" / "uv" / "archive-v0" / "dg069"
    fake(archive / "bin", 'echo "shipmill 0.10.0"')
    (archive / "pyvenv.cfg").touch()
    tools = tmp_path / "share" / "uv" / "tools" / "shipmill"
    tool = fake(tools / "bin", 'echo "shipmill 0.40.0"')
    (tools / "pyvenv.cfg").touch()
    (tmp_path / "local-bin").mkdir()
    (tmp_path / "local-bin" / "shipmill").symlink_to(tool)
    path = f"{archive / 'bin'}:{tmp_path / 'local-bin'}"
    found = ws.path_cli(path, (tmp_path / "running",))
    assert found == ws.PathCli(tmp_path / "local-bin" / "shipmill", "0.40.0")


def test_s031_26_the_environment_is_the_interpreters_and_the_one_holding_the_script(
    ws: ModuleType, tmp_path: Path
) -> None:
    venv = tmp_path / "archive-v0" / "abc"
    script = venv / "lib" / "python3.14" / "site-packages" / "shipmill" / "skills" / "watch_state.py"
    script.parent.mkdir(parents=True)
    script.touch()
    (venv / "pyvenv.cfg").touch()
    assert ws.own_environments(str(tmp_path / "py"), script) == ((tmp_path / "py").resolve(), venv.resolve())
    assert ws.own_environments(str(venv), script) == (venv.resolve(),)
    assert ws.own_environments(str(tmp_path / "py"), tmp_path / "skills" / "watch_state.py") == (
        (tmp_path / "py").resolve(),
    )


def test_s031_26_version_runs_with_path_and_home_only(ws: ModuleType, tmp_path: Path) -> None:
    program = fake(
        tmp_path / "bin", 'echo "${GH_TOKEN-unset}|${GITHUB_TOKEN-unset}|${USER-unset}|${HOME:+home}|${PATH:+path}"'
    )
    assert ws.answer_version(program).stdout.strip() == "unset|unset|unset|home|path"


def test_s031_29_a_shipmill_that_never_answers_is_a_row_never_a_stop(ws: ModuleType, tmp_path: Path) -> None:
    """D-50, S-031-29: the gate reads watch_state.py every tick and stops on its exit 2, so a hung
    or unstartable shipmill on PATH is the row with its reason and uv's upgrade, never exit 2"""
    slow = fake(tmp_path / "slow", "exec sleep 5")

    def hurried() -> object:
        return ws.path_cli(str(tmp_path / "slow"), (tmp_path / "e",), lambda p: ws.answer_version(p, timeout=0.2))

    rows = ws.plugin_rows([install("user", "0.67.0")], None, "v0.67.0", [REPO], [GATE], REPO, hurried)
    (row,) = person(rows)
    assert (row.detail, row.fix) == (
        f"{slow} doesn't answer shipmill --version: timed out after 0.2 s, the plugin is 0.67.0; {UPGRADE}",
        UPGRADE,
    )
    assert row.json()["agent"] is False
    broken = tmp_path / "broken" / "shipmill"
    broken.parent.mkdir()
    broken.write_text("#!/nonexistent/interpreter\n", encoding="utf-8")
    broken.chmod(0o755)
    found = ws.path_cli(str(broken.parent), (tmp_path / "e",))
    assert found.path == broken and found.silent is not None and found.silent.startswith("can't start: ")
    assert ws.path_cli_row(found, "0.67.0", USER_UPDATE).fix == UPGRADE


def test_s031_27_a_shipmill_from_before_version_is_a_row_naming_it(ws: ModuleType, tmp_path: Path) -> None:
    usage = "shipmill: error: the following arguments are required: command"
    program = fake(tmp_path / "bin", f'echo "{usage}" >&2; exit 2')
    plugins = [install("user", "0.67.0")]
    rows = ws.plugin_rows(plugins, None, "v0.67.0", [REPO], [GATE], REPO, reader(ws, tmp_path / "bin", tmp_path / "e"))
    (row,) = person(rows)
    assert (row.detail, row.fix) == (
        f"{program} predates shipmill --version, the plugin is 0.67.0; {UPGRADE}",
        UPGRADE,
    )


@pytest.mark.parametrize("printed", ["0.40.0", "shipmill 0.40", "shipmill v0.40.0", "shipmill 0.40.0rc1", ""])
def test_s031_27_an_exit_0_that_isnt_a_version_stops_the_watch_naming_the_path(
    ws: ModuleType, tmp_path: Path, printed: str
) -> None:
    program = fake(tmp_path / "bin", f'printf "%s\\n" "{printed}"')
    with pytest.raises(ws.Refused) as refused:
        ws.path_cli(str(tmp_path / "bin"), (tmp_path / "e",))
    assert refused.value.code == 2
    assert str(program) in str(refused.value) and repr(printed) in str(refused.value)


def test_s031_28_no_shipmill_on_path_or_no_loaded_install_gives_no_row(ws: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    plugins = [install("user", "0.67.0")]
    rows = ws.plugin_rows(plugins, None, "v0.67.0", [REPO], [GATE], REPO, reader(ws, tmp_path / "empty", tmp_path))
    assert person(rows) == []

    def unasked() -> None:
        raise AssertionError("the shipmill on PATH is read only when a session loads an install")

    for found in (
        ws.plugin_rows(None, None, "v0.67.0", [REPO], [GATE], REPO, unasked),  # claude isn't on PATH
        ws.plugin_rows([], None, "v0.67.0", [REPO], [GATE], REPO, unasked),  # no install applies
        ws.plugin_rows([install("project", "0.60.0", Path("/else"))], None, "v0.67.0", [REPO], [GATE], REPO, unasked),
    ):
        assert person(found) == []
        shown = doctor_rows(found)
        checks = plugin_checks(lambda: shown)  # noqa: B023 (called before the loop moves on)
        assert not any("shipmill on PATH" in c.detail for c in checks)
        assert not any("shipmill on PATH" in line for line in lines(facts(*[status_row(r) for r in found])))


def status_row(r: Any) -> Row:
    """A watch_state.py row as status reads it from the JSON line"""
    raw = r.json()
    return Row(raw["state"], raw["subject"], raw["detail"], raw["agent"], raw["fix"])


def path_row(ws: ModuleType, tmp_path: Path, version: str, plugin: str = "0.26.0") -> Any:
    fake(tmp_path / "bin", f'echo "shipmill {version}"')
    rows = ws.plugin_rows(
        [install("user", plugin)], None, "v0.26.0", [REPO], [GATE], REPO, reader(ws, tmp_path / "bin", tmp_path / "e")
    )
    (row,) = person(rows)
    return row


def test_s031_29_doctor_warns_naming_the_path_both_versions_and_the_fix_and_exits_0(
    ws: ModuleType, tmp_path: Path
) -> None:
    row = path_row(ws, tmp_path, "0.20.0")
    checks = plugin_checks(lambda: doctor_rows([row]))
    (warn,) = [c for c in checks if "on PATH" in c.detail]
    assert warn.status == "WARN"
    assert warn.detail == f"shipmill on PATH {tmp_path / 'bin' / 'shipmill'} is 0.20.0, the plugin is 0.26.0; {UPGRADE}"
    assert not any(c.status == "FAIL" for c in checks)  # doctor exits 1 only on a FAIL


def test_s031_29_status_waits_on_you_and_names_uvs_upgrade_once(ws: ModuleType, tmp_path: Path) -> None:
    row = status_row(path_row(ws, tmp_path, "0.20.0"))
    assert row.agent is False  # no gate starts or holds a session on it
    current = facts(row)
    found = report(current)
    assert found.verdict is Verdict.WAITS and [r.fix for r in found.reasons] == [UPGRADE]
    assert "\n".join(lines(current)).count(UPGRADE) == 1
    # the shipmill running status lags the latest release too: S-011-15's line says the same once
    lagging = facts(row, cli="0.20.0")
    assert UPGRADE in [r.fix for r in report(lagging).reasons]
    assert "\n".join(lines(lagging)).count(UPGRADE) == 1
    assert lines(lagging)[-1].endswith(f", update available: {UPGRADE}")


def test_s031_29_no_gate_holds_a_session_on_the_row(ws: ModuleType, tmp_path: Path) -> None:
    row = path_row(ws, tmp_path, "0.30.0")
    assert row.state not in ws.AGENT and row.json()["agent"] is False
    assert row.fix == USER_UPDATE
