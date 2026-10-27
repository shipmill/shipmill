"""Spec 031: the marketplace names the release tag, and the plugin pins its CLI to its own
version, `uvx shipmill==<plugin.json's version>`, in the repo's layout and in the wheel"""

import datetime as dt
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

from shipmill import UVX, requires
from shipmill.errors import ReleaseError
from shipmill.plugin import READ_MARKETPLACE, latest_release, loaded, marketplace_release
from shipmill.policy import Policy
from shipmill.stamp import write_version
from shipmill.version import Version

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
WATCH = ROOT / "skills" / "github-ship-watch" / "scripts"
OLD = "git+https://github.com/shipmill/shipmill@v0"
PINNED = re.compile(r"uvx shipmill==(\S+?)(?=[\s`\"'),]|$)")
APP = '[agents]\nprompt = "/t"\napp_id = 7\n'


def version() -> str:
    found = json.loads(PLUGIN.read_text(encoding="utf-8"))["version"]
    assert isinstance(found, str)
    return found


def load(name: str, path: Path, *search: Path) -> ModuleType:
    sys.path[:0] = [str(p) for p in search]
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # dataclasses look their module up by name
        spec.loader.exec_module(module)
    finally:
        del sys.path[: len(search)]
    return module


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("watch_state", WATCH / "watch_state.py")


def marketplace(source: object, name: str = "shipmill") -> str:
    return json.dumps({"name": "shipmill", "plugins": [{"name": name, "source": source}]})


def files(folder: Path) -> list[Path]:
    """The files under folder, but Python's bytecode caches"""
    return [p for p in sorted(folder.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]


def pins(root: Path) -> dict[str, list[str]]:
    """Every written-out `uvx shipmill==<version>` under root/skills, by file (placeholders such
    as `<version>` in a script's docstring left out)"""
    found: dict[str, list[str]] = {}
    for path in files(root / "skills"):
        hits = [v for v in PINNED.findall(path.read_text(encoding="utf-8")) if not v.startswith("<")]
        if hits:
            found[path.relative_to(root).as_posix()] = hits
    return found


# -- S-031-1: the marketplace names the release tag, and the stamp moves it ------------------


def test_s031_1_the_marketplace_entry_names_a_release_tag_no_newer_than_plugin_json() -> None:
    data = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    (entry,) = [p for p in data["plugins"] if p["name"] == "shipmill"]
    assert {k: v for k, v in entry["source"].items() if k != "ref"} == {"source": "github", "repo": "shipmill/shipmill"}
    # D-50 (#617): the ref moves after publish, so the release commit, which CI checks before it
    # lands, still names the previous release; it never names one newer than plugin.json's
    assert marketplace_release(MARKETPLACE.read_text(encoding="utf-8")) <= Version.parse(version())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == version()  # the package and the plugin move together


def stamped_copy(tmp_path: Path, new: str) -> Path:
    """A copy of the repo's release files and skills, stamped as new by the release's
    version step (shipmill stamp's write_version) under the repo's own config"""
    copy = tmp_path / "repo"
    for name in (".github", ".claude-plugin", "skills"):
        shutil.copytree(ROOT / name, copy / name)
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copy(ROOT / name, copy / name)
    policy = Policy.load(copy / ".github" / "shipmill.toml")
    changed = write_version(copy, policy, Version.parse(new), dt.date(2026, 10, 20))
    assert ".claude-plugin/plugin.json" in changed
    return copy


def test_s031_1_a_release_stamp_moves_plugin_json_and_leaves_the_marketplace_ref(tmp_path: Path) -> None:
    before = MARKETPLACE.read_text(encoding="utf-8")
    copy = stamped_copy(tmp_path, "0.99.0")
    assert json.loads((copy / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"] == "0.99.0"
    # D-50 (#617): move-major-tag.yml moves the ref, after publish, never the release commit
    assert (copy / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8") == before


def test_shipmills_own_config_requires_a_release_that_knows_after_publish() -> None:
    raw = tomllib.loads((ROOT / ".github" / "shipmill.toml").read_text(encoding="utf-8"))
    # #617: 0.70.0 brought after_publish; an upgrade may raise the bound past it (#684)
    assert requires.check(raw, Version.parse(version())) is not None
    with pytest.raises(ReleaseError, match=re.escape("this is 0.69.0")):
        requires.check(raw, Version.parse("0.69.0"))


# -- S-031-2: the latest release is the marketplace entry's ref -------------------------------


BAD_ENTRIES = [
    marketplace("./"),
    marketplace({"source": "github", "repo": "shipmill/shipmill"}),
    marketplace({"source": "url", "url": "https://x/y.git", "ref": "v1.2.3"}),
    marketplace({"source": "github", "repo": "shipmill/shipmill", "ref": "main"}),
    marketplace({"source": "github", "repo": "shipmill/shipmill", "ref": "v1.2"}),
    marketplace({"source": "github", "repo": "shipmill/shipmill", "ref": "1.2.3"}),
    marketplace({"source": "github", "repo": "shipmill/shipmill", "ref": "v1.2.3rc1"}),
]
UNREADABLE = ["{", "[]", '{"plugins": {}}', marketplace({"source": "./"}, name="other")]


def test_s031_2_the_repo_marketplace_reads_the_same_in_the_cli_and_watch_state(ws: ModuleType) -> None:
    text = MARKETPLACE.read_text(encoding="utf-8")
    # D-50 (#617): on a release commit the ref still names the previous release, never a newer one
    assert marketplace_release(text) <= Version.parse(version())
    assert ws.marketplace_release(text) == f"v{marketplace_release(text)}"


def test_s031_2_the_cli_reads_the_marketplace_from_the_default_branch_not_gh_release() -> None:
    assert READ_MARKETPLACE == [
        "gh",
        "api",
        "-H",
        "Accept: application/vnd.github.raw+json",
        "repos/shipmill/shipmill/contents/.claude-plugin/marketplace.json",
    ]
    seen: list[list[str]] = []

    def run(cmd: list[str], cwd: Path) -> str:
        seen.append(cmd)
        if cmd == READ_MARKETPLACE:
            return marketplace({"source": "github", "repo": "shipmill/shipmill", "ref": "v0.60.1"})
        if cmd[:3] == ["claude", "plugin", "list"]:
            return json.dumps([{"id": "shipmill@shipmill", "scope": "user", "version": "0.59.0"}])
        raise AssertionError(f"unexpected command {cmd}")

    assert latest_release(run, ROOT) == Version.parse("0.60.1")
    found = loaded(ROOT, ROOT, run, None, None)  # the gate's read of the install a session loads
    assert (found.latest, len(found.lags), found.error) == (Version.parse("0.60.1"), 1, None)
    assert not any(cmd[:2] == ["gh", "release"] for cmd in seen)


@pytest.mark.parametrize("text", BAD_ENTRIES)
def test_s031_2_an_entry_without_a_github_source_and_a_vxyz_ref_is_refused(text: str, ws: ModuleType) -> None:
    with pytest.raises(ReleaseError) as raised:
        marketplace_release(text)
    said = str(raised.value)
    assert "shipmill/shipmill:.claude-plugin/marketplace.json" in said and "plugins entry 'shipmill'" in said
    with pytest.raises(SystemExit) as refused:  # watch_state.py's refusal: exit 2, its message on stderr
        ws.latest_release(lambda cmd: text)
    assert refused.value.code == 2
    assert "shipmill/shipmill:.claude-plugin/marketplace.json" in str(refused.value)
    assert "plugins entry 'shipmill'" in str(refused.value)


@pytest.mark.parametrize("text", UNREADABLE)
def test_s031_2_a_marketplace_without_one_shipmill_entry_is_refused_naming_the_file(text: str, ws: ModuleType) -> None:
    with pytest.raises(ReleaseError, match=r"shipmill/shipmill:\.claude-plugin/marketplace\.json"):
        marketplace_release(text)
    with pytest.raises(SystemExit) as refused:
        ws.marketplace_release(text)
    assert refused.value.code == 2 and ".claude-plugin/marketplace.json" in str(refused.value)


def test_s031_2_watch_state_reads_the_latest_release_from_the_marketplace(ws: ModuleType) -> None:
    seen: list[list[str]] = []

    def run(cmd: list[str]) -> str:
        seen.append(cmd)
        return marketplace({"source": "github", "repo": "shipmill/shipmill", "ref": "v0.60.1"})

    assert ws.latest_release(run) == "v0.60.1"
    assert seen == [READ_MARKETPLACE]


# -- S-031-3: the skills and hooks name the pinned CLI, and the stamp moves every pin ---------


def test_s031_3_no_file_under_skills_or_hooks_names_the_v0_source() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for folder in ("skills", "hooks")
        for path in files(ROOT / folder)
        if OLD.encode() in path.read_bytes()
    ]
    assert offenders == []


def test_s031_3_every_pin_under_skills_names_the_plugin_version() -> None:
    found = pins(ROOT)
    assert found, "the skills write the pinned CLI out"
    assert {v for hits in found.values() for v in hits} == {version()}
    assert f"uvx shipmill=={version()}" == UVX  # the CLI's own hints name the same release


def test_s031_3_a_release_stamp_moves_every_pin(tmp_path: Path) -> None:
    before = pins(ROOT)
    copy = stamped_copy(tmp_path, "0.99.0")
    after = pins(copy)
    assert {k: len(v) for k, v in after.items()} == {k: len(v) for k, v in before.items()}
    assert {v for hits in after.values() for v in hits} == {"0.99.0"}


# -- S-031-4: the scripts run the CLI their own plugin pins ----------------------------------

WRITERS = """
import importlib.util, json, sys
from pathlib import Path

root, checkout, only = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, root / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def watch_state():
    ws = load("watch_state", "skills/github-ship-watch/scripts/watch_state.py")
    try:
        return ws.gh_writer(checkout)
    except ws.Refused as refused:  # as the script's __main__ reports it
        sys.stderr.write(f"{refused}\\n")
        raise


def setup_state():
    ss = load("setup_state", "skills/shipmill-setup/scripts/setup_state.py")
    return ss.gh_writer(checkout, ss.watch_module())


def shipped():
    sp = load("shipped", "skills/github-pr-triage/scripts/shipped.py")
    return sp.writer(checkout, sp.watch_module())


def chains():
    sys.path.insert(0, str(root / "skills/github-issue-triage/scripts"))
    return load("chains", "skills/github-issue-triage/scripts/chains.py").writer(checkout)


names = ["watch_state", "setup_state", "shipped", "chains"] if only == "all" else [only]
print(json.dumps({"python": list(sys.version_info[:2]), **{n: globals()[n]() for n in names}}))
"""
SCRIPTS = ["watch_state", "setup_state", "shipped", "chains"]


def uv() -> str:
    found = shutil.which("uv")
    assert found is not None, "uv runs the skill scripts"
    return found


def writers(root: Path, checkout: Path, only: str = "all") -> subprocess.CompletedProcess[str]:
    """The scripts' writing gh, under Python 3.10 as a skill runs them, from the plugin at root"""
    command = [uv(), "run", "--no-project", "--python", "3.10", "python", "-c", WRITERS, str(root), str(checkout), only]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def app_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    (root / ".git").mkdir(parents=True)
    (root / ".github").mkdir()
    (root / ".github" / "shipmill.toml").write_text(APP, encoding="utf-8")
    return root.resolve()


def test_s031_4_the_scripts_run_the_pinned_cli_in_the_repo_layout(tmp_path: Path) -> None:
    checkout = app_checkout(tmp_path)
    done = writers(ROOT, checkout)
    assert done.returncode == 0, done.stderr
    found = json.loads(done.stdout)
    assert found.pop("python") == [3, 10]
    want = ["uvx", f"shipmill=={version()}", "--repo", str(checkout), "gh"]
    assert found == dict.fromkeys(SCRIPTS, want)


def test_s031_4_watch_state_runs_every_command_pinned_and_keeps_tool(ws: ModuleType) -> None:
    assert ws.PLUGIN_JSON == PLUGIN  # three folders above scripts/
    assert ws.shipmill_cli() == ["uvx", f"shipmill=={version()}"]
    assert ws.shipmill_cli("git+https://example.com/fork@main") == [
        "uvx",
        "--from",
        "git+https://example.com/fork@main",
        "shipmill",
    ]
    row = ws.plan_failed_row(ws.PlanFailed("shipmill: bad"), "release.yml", Path("/r"), "main", None)
    assert row.fix == f"on an up-to-date main: uvx shipmill=={version()} --repo /r plan --event schedule --dry-run"


def test_s031_4_retro_and_intake_run_the_pinned_cli_too(tmp_path: Path) -> None:
    retro = load("retro", WATCH / "retro.py", WATCH)
    intake = load("intake_state", ROOT / "skills" / "product-intake" / "scripts" / "intake_state.py")
    assert retro.pinned_shipmill() == ("uvx", f"shipmill=={version()}")
    assert intake.shipmill_command(None) == ["uvx", f"shipmill=={version()}"]
    assert intake.shipmill_command("x") == ["uvx", "--from", "x", "shipmill"]
    broken = tmp_path / "plugin.json"
    broken.write_text('{"version": "next"}', encoding="utf-8")
    with pytest.raises(SystemExit) as refused:
        retro.pinned_shipmill(broken)
    assert refused.value.code == 2
    with pytest.raises(SystemExit) as refused:
        intake.shipmill_command(None, broken)
    assert refused.value.code == 2


BROKEN = [
    (None, "is missing"),
    ("{not json", "is not JSON"),
    ('{"name": "shipmill"}', "version must be X.Y.Z, got None"),
    ('{"version": "0.57"}', "version must be X.Y.Z, got '0.57'"),
    ('{"version": 57}', "version must be X.Y.Z, got 57"),
]


@pytest.mark.parametrize(("text", "said"), BROKEN)
def test_s031_4_a_broken_plugin_json_exits_2_naming_the_path(tmp_path: Path, text: str | None, said: str) -> None:
    plugin = tmp_path / "plugin"
    shutil.copytree(ROOT / "skills", plugin / "skills")
    path = plugin / ".claude-plugin" / "plugin.json"
    if text is not None:
        path.parent.mkdir()
        path.write_text(text, encoding="utf-8")
    checkout = app_checkout(tmp_path)
    for script in SCRIPTS:
        done = writers(plugin, checkout, script)
        assert done.returncode == 2, (script, done.stdout, done.stderr)
        assert str(path.resolve()) in done.stderr and said in done.stderr, (script, done.stderr)


# -- S-031-5: the wheel holds plugin.json, so the scripts find it there too -------------------


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("wheel")
    built = subprocess.run(
        [uv(), "build", "--wheel", "--out-dir", str(out), str(ROOT)], capture_output=True, text=True, check=False
    )
    assert built.returncode == 0, built.stderr
    (found,) = out.glob("shipmill-*.whl")
    return found


def test_s031_5_the_wheel_holds_plugin_json_at_the_package_version(wheel: Path) -> None:
    package = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    with zipfile.ZipFile(wheel) as archive:
        held = json.loads(archive.read("shipmill/.claude-plugin/plugin.json"))
        names = archive.namelist()
    assert held["version"] == package == version()
    assert "shipmill/skills/github-ship-watch/scripts/watch_state.py" in names


def test_s031_4_the_scripts_run_the_pinned_cli_from_the_wheel(wheel: Path, tmp_path: Path) -> None:
    site = tmp_path / "site"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(site)
    checkout = app_checkout(tmp_path)
    done = writers(site / "shipmill", checkout)
    assert done.returncode == 0, done.stderr
    found = json.loads(done.stdout)
    assert found.pop("python") == [3, 10]
    assert found == dict.fromkeys(SCRIPTS, ["uvx", f"shipmill=={version()}", "--repo", str(checkout), "gh"])
