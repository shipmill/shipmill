"""Spec 031: the config's top-level requires, in the CLI and in the skills' scripts"""

import importlib.util
import json
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

from shipmill import requires
from shipmill.agents import AgentsConfig
from shipmill.cli import main
from shipmill.config import CONFIG_PATH, loads
from shipmill.errors import ReleaseError
from shipmill.init import init
from shipmill.policy import Policy
from shipmill.requires import Requires
from shipmill.version import Version

from .conftest import POLICY, Repo

SKILLS = Path(__file__).resolve().parents[1] / "skills"
WATCH = SKILLS / "github-ship-watch" / "scripts" / "watch_state.py"
SETUP = SKILLS / "shipmill-setup" / "scripts" / "setup_state.py"
TOO_NEW = ">=999.0"
# what an old CLI meets in a newer config: a key it doesn't know, at the top and in a table
NEWER = POLICY + "future_key = 1\n\n[agents]\nprompt = 'triage {repo}'\nfuture_agents_key = true\n"


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("shipmill_watch_state", WATCH)


def write_config(root: Path, text: str) -> Path:
    path = root / CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def with_requires(text: str, bound: str) -> str:
    return f'requires = "{bound}"  # the oldest shipmill\n{text}'


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "shipmill", "--repo", str(root), *args]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def run_script(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(path), *args]
    return subprocess.run(command, capture_output=True, text=True, check=False)


# -- the CLI (S-031-6) -----------------------------------------------------------------------


@pytest.mark.parametrize("bound", [">=0.1", ">=0.1.0", str(Requires.series(requires.running()))])
def test_s031_6_a_requires_the_cli_meets_reads_as_before(bound: str) -> None:
    raw = loads(with_requires(POLICY, bound), str(CONFIG_PATH))
    assert Policy.parse(raw, CONFIG_PATH.name) == Policy.parse(tomllib.loads(POLICY), CONFIG_PATH.name)


def test_s031_6_an_unmet_requires_exits_2_with_the_bound_the_version_and_both_updates(tmp_path: Path) -> None:
    write_config(tmp_path, with_requires(NEWER, TOO_NEW))
    done = run_cli(tmp_path, "upgrade")
    assert done.returncode == 2
    assert done.stderr == f"shipmill: {requires.unmet(TOO_NEW, str(requires.running()))}\n"
    assert done.stderr.startswith(f"shipmill: .github/shipmill.toml requires shipmill {TOO_NEW}; this is ")
    assert "claude plugin update shipmill@shipmill" in done.stderr and "uv tool upgrade shipmill" in done.stderr


def test_s031_6_the_bound_is_checked_before_any_unknown_key(tmp_path: Path) -> None:
    write_config(tmp_path, NEWER)  # without requires, the same config fails on its keys
    with pytest.raises(ReleaseError, match="unknown keys"):
        Policy.load(tmp_path / CONFIG_PATH)
    write_config(tmp_path, with_requires(NEWER, TOO_NEW))
    for read in (lambda: Policy.load(tmp_path / CONFIG_PATH), lambda: AgentsConfig.load(tmp_path)):
        with pytest.raises(ReleaseError, match="requires shipmill >=999.0; this is"):
            read()
    with pytest.raises(ReleaseError, match="requires shipmill >=999.0; this is"):
        Policy.parse(tomllib.loads(with_requires(NEWER, TOO_NEW)), CONFIG_PATH.name)


@pytest.mark.parametrize("value", ['"0.56"', '">0.56"', '">= 0.56"', '">=1"', '">=1.2.3.4"', '"<=1.0"', "56", "true"])
def test_s031_6_any_other_requires_exits_2_naming_the_key(tmp_path: Path, value: str) -> None:
    write_config(tmp_path, f"requires = {value}\n{POLICY}")
    with pytest.raises(ReleaseError, match=r'requires must be ">=X.Y" or ">=X.Y.Z"'):
        Policy.load(tmp_path / CONFIG_PATH)
    done = run_cli(tmp_path, "upgrade")
    assert done.returncode == 2 and "requires must be" in done.stderr


def test_s031_6_a_pre_release_meets_the_bound_of_its_release() -> None:
    bound = Requires.parse(">=0.58")
    assert bound.met(Version.parse("0.58.0.dev3")) and bound.met(Version.parse("0.58.0rc1"))
    assert not bound.met(Version.parse("0.57.9"))
    assert not Requires.parse(">=0.58.1").met(Version.parse("0.58.0"))
    assert str(Requires.parse(">=0.058")) == ">=0.58"


# -- the scripts (S-031-6) -------------------------------------------------------------------


@pytest.mark.parametrize(("bound", "version"), [(">=0.56", "0.55.0"), (">=1.2.3", "1.2.2"), (">=0.058", "0.57.9")])
def test_s031_6_the_scripts_refuse_with_the_clis_text(ws: ModuleType, bound: str, version: str) -> None:
    with pytest.raises(ws.Refused) as refused:
        ws.check_requires(with_requires(POLICY, bound), ws.POLICY, lambda: version)
    want = requires.unmet(str(Requires.parse(bound)), version)
    assert str(refused.value) == want
    assert ws.requires_unmet(str(Requires.parse(bound)), version) == want


@pytest.mark.parametrize("value", ["0.56", ">= 0.56", ">=1", 56, True])
def test_s031_6_the_scripts_refuse_any_other_value_as_the_cli_does(ws: ModuleType, value: object) -> None:
    text = f"requires = {value!r}\n".replace("'", '"').replace("True", "true") + POLICY
    with pytest.raises(ws.Refused) as refused:
        ws.check_requires(text, ws.POLICY, lambda: "0.57.0")
    assert str(refused.value) == f"error: {requires.invalid(value)}"


def test_s031_6_the_scripts_read_on_as_before_when_met_or_absent(ws: ModuleType) -> None:
    def unread() -> str:
        raise AssertionError("the version is read only when the config sets requires")

    ws.check_requires(POLICY, ws.POLICY, unread)
    ws.check_requires(with_requires(POLICY, ">=0.57"), ws.POLICY, lambda: "0.57.0")
    ws.check_requires(with_requires(POLICY, ">=0.57.0"), ws.POLICY, lambda: "1.0.0")


def test_s031_6_the_scripts_read_requires_on_python_3_10(ws: ModuleType) -> None:
    assert ws.requires_value_310(POLICY, ws.POLICY) is None
    assert ws.requires_value_310(with_requires(POLICY, ">=0.56"), ws.POLICY) == ">=0.56"
    assert ws.requires_value_310("requires = '>=0.56'\n[agents]\nrequires = 1\n", ws.POLICY) == ">=0.56"
    with pytest.raises(ws.Refused, match="can't read requires on Python 3.10"):
        ws.requires_value_310('"requires" = ">=0.56"\n', ws.POLICY)


def test_s031_6_the_scripts_compare_the_plugins_version(ws: ModuleType, tmp_path: Path) -> None:
    assert SKILLS.parent / ".claude-plugin" / "plugin.json" == ws.PLUGIN_JSON
    assert ws.plugin_version() == json.loads(ws.PLUGIN_JSON.read_text(encoding="utf-8"))["version"]
    path = tmp_path / "plugin.json"
    for text, error in (("{", "not JSON"), ('{"version": "0.57"}', "version must be X.Y.Z")):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ws.Refused, match=error):
            ws.plugin_version(path)
    with pytest.raises(ws.Refused, match="missing"):
        ws.plugin_version(tmp_path / "none.json")


@pytest.mark.parametrize("script", [WATCH, SETUP])
def test_s031_6_watch_state_and_setup_state_exit_2_on_an_unmet_requires(
    ws: ModuleType, script: Path, tmp_path: Path
) -> None:
    write_config(tmp_path, with_requires(NEWER, TOO_NEW))
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", "https://github.com/o/r.git"], check=True)
    done = run_script(script, "o/r", "--repo-dir", str(tmp_path))
    assert done.returncode == 2
    assert done.stderr == requires.unmet(TOO_NEW, ws.plugin_version()) + "\n"


# -- init and upgrades (S-031-7) -------------------------------------------------------------


def test_s031_7_init_writes_requires_at_its_own_major_minor(repo: Repo) -> None:
    (repo.root / CONFIG_PATH).unlink()
    repo.write(".github/workflows/ci.yml", "name: CI\non:\n  workflow_call:\njobs: {}\n")
    written = init(repo.root, "ci.yml", force=False).written[0]
    have = requires.running()
    assert tomllib.loads(written.read_text(encoding="utf-8"))["requires"] == f">={have.major}.{have.minor}"
    Policy.load(written)


@pytest.mark.parametrize(
    ("bound", "after"),
    [
        (">=0.30", ">=0.37.0"),
        (">=0.37", ">=0.37"),
        (">=0.37.0", ">=0.37.0"),
        (">=0.40", ">=0.40"),
        (">=0.5", ">=0.37.0"),
    ],
)
def test_s031_7_apply_raises_a_lower_requires_and_leaves_a_higher_one(tmp_path: Path, bound: str, after: str) -> None:
    before = f'# the policy\nrequires = \'{bound}\'   # kept comment\nname = "demo"\n\n[changelog]\npath = "C.md"\n'
    path = write_config(tmp_path, before)
    assert main(["--repo", str(tmp_path), "upgrade", "--apply", "changelog-fragments"]) == 0  # its version: 0.37.0
    edited = before + 'fragments = "changelog.d"\n'
    if after != bound:
        edited = edited.replace(f"'{bound}'", f'"{after}"')
    assert path.read_bytes().decode("utf-8") == edited


def test_s031_7_apply_leaves_a_config_without_requires_without_it(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[changelog]\npath = "C.md"\n')
    assert main(["--repo", str(tmp_path), "upgrade", "--apply", "changelog-fragments"]) == 0
    assert "requires" not in tomllib.loads(path.read_text(encoding="utf-8"))


def test_s031_7_apply_refuses_a_config_its_cli_does_not_meet(tmp_path: Path) -> None:
    path = write_config(tmp_path, with_requires('[changelog]\npath = "C.md"\n', TOO_NEW))
    before = path.read_bytes()
    with pytest.raises(ReleaseError, match="requires shipmill >=999.0"):
        main(["--repo", str(tmp_path), "upgrade", "--apply", "changelog-fragments"])
    assert path.read_bytes() == before
