"""Spec 033: contributors in a shipmill repo. The plugin is per person by default ([agents]
plugin), setup's Plugin rows, the key the gate hands every session (SHIPMILL_APP_KEY), `shipmill
gh` and `app-token` reading it, `app-token --check`, doctor's app-writes line, init's commented
key, the docs, and the skills' "Write as the App" rule. The hook's own criteria (S-033-5 to
S-033-8) are in test_delivery_hooks.py, beside spec 026's"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.agents import AgentsConfig, Plugin
from shipmill.app import APP_KEY, Answer, Helpers, Identity, app_check, session_env
from shipmill.cli import main
from shipmill.config import CONFIG_PATH, Table
from shipmill.doctor import app_writes, doctor
from shipmill.errors import ReleaseError
from shipmill.gate import ClaudeCli
from shipmill.gitrepo import Git
from shipmill.init import init

from .conftest import Repo
from .test_app import APP_ID, BOT_ID, REPO, FakeApi, FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, Runner, checkout
from .test_app_token import FAKE_GH, MintApi, executable
from .test_gate_app import Prepared, gh_path, launch_as_app
from .test_gate_headless import Reads, Spawned, app_check_for, headless, tick

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "skills" / "shipmill-setup" / "scripts" / "setup_state.py"
SKILLS = [
    "github-issue-triage",
    "github-issue-resolve",
    "github-pr-triage",
    "github-ship-watch",
    "product-intake",
    "shipmill-setup",
]


def folded(*parts: str) -> str:
    """A doc with its line wrapping folded, so a statement reads as one line"""
    return " ".join(ROOT.joinpath(*parts).read_text(encoding="utf-8").split())


@pytest.fixture(scope="module")
def ss() -> ModuleType:
    spec = importlib.util.spec_from_file_location("setup_state_033", SETUP)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ws(ss: ModuleType) -> ModuleType:
    found: ModuleType = ss.watch_module()
    return found


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def agents(text: str) -> AgentsConfig:
    return AgentsConfig.parse(Table(tomllib.loads('[agents]\nprompt = "/t"\n' + text), "shipmill.toml").table("agents"))


# --- S-033-1: [agents] plugin ------------------------------------------------------------------

BAD_PLUGINS = ['plugin = "both"', 'plugin = "Host"', 'plugin = ""', "plugin = 1", "plugin = true", 'plugin = ["host"]']


def test_s033_1_plugin_reads_host_by_default_and_repo_when_given() -> None:
    assert agents("").plugin is Plugin.HOST
    assert agents('plugin = "host"\n').plugin is Plugin.HOST
    assert agents('plugin = "repo"\n').plugin is Plugin.REPO


@pytest.mark.parametrize("line", BAD_PLUGINS)
def test_s033_1_any_other_plugin_exits_2_naming_the_key_and_both_values(line: str) -> None:
    with pytest.raises(ReleaseError) as raised:  # cli.run prints it and exits 2
        agents(line + "\n")
    message = str(raised.value)
    assert '[agents] plugin must be "host" (the default) or "repo"' in message


@pytest.mark.parametrize("line", BAD_PLUGINS)
def test_s033_1_setup_state_refuses_the_same_values(
    ss: ModuleType, ws: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], line: str
) -> None:
    write(tmp_path, ".github/shipmill.toml", f'[agents]\nprompt = "/t"\n{line}\n')
    with pytest.raises(SystemExit) as exited:
        ss.plugin_mode(tmp_path, ws)
    assert exited.value.code == 2
    assert '[agents] plugin must be "host" (the default) or "repo"' in capsys.readouterr().err


@pytest.mark.parametrize(
    ("config", "mode"),
    [(None, "host"), ("[release]\n", "host"), ('[agents]\nprompt = "/t"\n', "host")]
    + [('[agents]\nprompt = "/t"\nplugin = "host"\n', "host"), ('[agents]\nprompt = "/t"\nplugin = "repo"\n', "repo")],
)
def test_s033_1_setup_state_reads_the_mode(
    ss: ModuleType, ws: ModuleType, tmp_path: Path, config: str | None, mode: str
) -> None:
    if config is not None:
        write(tmp_path, ".github/shipmill.toml", config)
    assert ss.plugin_mode(tmp_path, ws) == mode


def test_s033_1_setup_state_reads_the_mode_under_python_310(tmp_path: Path) -> None:
    write(tmp_path, "repo/.github/shipmill.toml", '[agents]\nprompt = "/t"\nplugin = "repo"\n')
    write(tmp_path, "bad/.github/shipmill.toml", '[agents]\nprompt = "/t"\nplugin = "x"\n')
    uv = shutil.which("uv")
    assert uv is not None, "uv runs the skill scripts"
    code = (
        "import importlib.util, sys; from pathlib import Path\n"
        "spec = importlib.util.spec_from_file_location('setup_state', sys.argv[1])\n"
        "ss = importlib.util.module_from_spec(spec); sys.modules['setup_state'] = ss; spec.loader.exec_module(ss)\n"
        "ws = ss.watch_module(); assert ws.tomllib is None, 'tomllib on 3.10'\n"
        "root = Path(sys.argv[2])\n"
        "print(ss.plugin_mode(root / 'repo', ws), ss.plugin_mode(root / 'none', ws), flush=True)\n"
        "ss.plugin_mode(root / 'bad', ws)\n"
    )
    command = [uv, "run", "--no-project", "--python", "3.10", "python", "-c", code, str(SETUP), str(tmp_path)]
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    assert (done.returncode, done.stdout.strip()) == (2, "repo host"), done.stderr
    assert '[agents] plugin must be "host" (the default) or "repo", got "x"' in done.stderr


# --- S-033-2, S-033-3, S-033-4: the Plugin rows -------------------------------------------------

PROJECT = Path("/work/demo")


def listing(*installs: tuple[str, str | None]) -> list[dict[str, Any]]:
    """`claude plugin list --json` with shipmill@shipmill at each (scope, projectPath)"""
    found: list[dict[str, Any]] = [{"id": "other@mine", "scope": "user", "version": "1.0.0"}]
    for scope, where in installs:
        entry: dict[str, Any] = {"id": "shipmill@shipmill", "scope": scope, "version": "0.80.1"}
        if where is not None:
            entry["projectPath"] = where
        found.append(entry)
    return found


def host_rows(
    ss: ModuleType, settings: dict[str, Any], plugins: object, outdated: list[Any] | None = None
) -> list[Any]:
    def unread() -> list[Any]:
        if outdated is None:
            raise AssertionError("installs are read only for a PLUGIN_OK")
        return outdated

    rows: list[Any] = ss.host_plugin_rows(settings, lambda: plugins, PROJECT, unread)
    return rows


@pytest.mark.parametrize(
    ("installs", "detail"),
    [
        ([("user", None)], "shipmill@shipmill 0.80.1 is installed at user scope"),
        ([("local", str(PROJECT))], f"shipmill@shipmill 0.80.1 is installed at local scope for {PROJECT}"),
        ([("project", str(PROJECT)), ("user", None)], f"0.80.1 is installed at project scope for {PROJECT}"),
    ],
)
def test_s033_2_host_reads_ok_naming_the_install_that_applies(
    ss: ModuleType, installs: list[tuple[str, str | None]], detail: str
) -> None:
    [row] = host_rows(ss, {}, listing(*installs), [])
    assert row.state == "PLUGIN_OK" and detail in row.detail


@pytest.mark.parametrize(
    "installs",
    [[], [("project", "/work/other")], [("local", f"{PROJECT}/tmp/shipmill-gate")], [("managed", None)]],
)
def test_s033_2_host_reads_missing_with_the_user_scope_install(
    ss: ModuleType, installs: list[tuple[str, str | None]]
) -> None:
    [row] = host_rows(ss, {}, listing(*installs))
    assert row.state == "PLUGIN_MISSING"
    assert row.detail.endswith(
        "claude plugin marketplace add shipmill/shipmill && claude plugin install shipmill@shipmill --scope user"
    )
    assert "PLUGIN_MISSING" not in ss.DONE


def test_s033_2_host_without_claude_reads_ok_and_outdated_installs_replace_it(ss: ModuleType) -> None:
    [row] = host_rows(ss, {}, None, [])
    assert (row.state, row.detail) == ("PLUGIN_OK", "claude isn't on PATH, installs not read")
    behind = [ss.Row("PLUGIN_OUTDATED", "plugin user: 0.70.0, latest v0.80.1; claude plugin marketplace update ...")]
    assert host_rows(ss, {}, listing(("user", None)), behind) == behind


@pytest.mark.parametrize("plugins", [{"not": "a list"}, [{"id": "shipmill@shipmill", "scope": 1, "version": "1"}]])
def test_s033_2_a_malformed_listing_exits_2(ss: ModuleType, plugins: object) -> None:
    with pytest.raises(SystemExit) as exited:
        host_rows(ss, {}, plugins)
    assert exited.value.code == 2


SETTINGS_TEXT = '{\n  "permissions": {"allow": ["Bash(ls)"]},\n  "enabledPlugins": {"other@mine": true}\n}'


@pytest.mark.parametrize("text", [None, SETTINGS_TEXT, '{"enabledPlugins": {"other@shipmill": true}}'])
def test_s033_2_host_fix_leaves_the_settings_byte_for_byte(ss: ModuleType, tmp_path: Path, text: str | None) -> None:
    path = tmp_path / ".claude" / "settings.json"
    if text is not None:
        write(tmp_path, ".claude/settings.json", text)
    settings = ss.load_settings(path)
    assert ss.fix_plugin(path, settings, "host") == settings
    if text is None:
        assert not path.exists() and not path.parent.exists()
    else:
        assert path.read_text(encoding="utf-8") == text


def test_s033_3_a_committed_plugin_in_host_mode_reads_committed_and_is_not_done(ss: ModuleType) -> None:
    [row] = host_rows(ss, {"enabledPlugins": {"shipmill@shipmill": True}}, listing(("user", None)))
    assert row.state == "PLUGIN_COMMITTED"
    assert '--fix removes "shipmill@shipmill" from enabledPlugins' in row.detail
    assert 'or set plugin = "repo" in [agents] to keep it' in row.detail
    assert ss.exit_code([row]) == 1


MARKET = {"source": {"source": "github", "repo": "shipmill/shipmill"}, "autoUpdate": True}


def committed(**extra: Any) -> dict[str, Any]:
    """Settings that commit the plugin and its marketplace, with extra keys first"""
    return {**extra, "extraKnownMarketplaces": {"shipmill": MARKET}, "enabledPlugins": {"shipmill@shipmill": True}}


def test_s033_3_host_fix_removes_the_plugin_and_keeps_every_other_key_and_the_layout(
    ss: ModuleType, tmp_path: Path
) -> None:
    settings = committed(permissions={"allow": ["Bash(ls)"]}, model="opus")
    settings["enabledPlugins"]["other@mine"] = True
    settings["extraKnownMarketplaces"]["mine"] = {"source": {"source": "github", "repo": "me/mine"}}
    path = write(tmp_path, ".claude/settings.json", json.dumps(settings, indent=4))  # no trailing newline
    kept = ss.fix_plugin(path, ss.load_settings(path), "host")
    expected = {
        "permissions": {"allow": ["Bash(ls)"]},
        "model": "opus",
        "extraKnownMarketplaces": {"mine": {"source": {"source": "github", "repo": "me/mine"}}},
        "enabledPlugins": {"other@mine": True},
    }
    assert kept == expected
    assert path.read_text(encoding="utf-8") == json.dumps(expected, indent=4)
    [row] = host_rows(ss, kept, listing(("user", None)), [])
    assert row.state == "PLUGIN_OK"


def test_s033_3_host_fix_keeps_the_marketplace_while_another_shipmill_plugin_is_on(
    ss: ModuleType, tmp_path: Path
) -> None:
    settings = committed()
    settings["enabledPlugins"]["extra@shipmill"] = True
    path = write(tmp_path, ".claude/settings.json", json.dumps(settings, indent="\t") + "\n")
    kept = ss.fix_plugin(path, ss.load_settings(path), "host")
    expected = {"extraKnownMarketplaces": {"shipmill": MARKET}, "enabledPlugins": {"extra@shipmill": True}}
    assert kept == expected
    assert path.read_text(encoding="utf-8") == json.dumps(expected, indent="\t") + "\n"


def test_s033_3_host_fix_drops_the_marketplace_when_only_a_disabled_one_names_it(
    ss: ModuleType, tmp_path: Path
) -> None:
    settings = committed(permissions={"deny": []})
    settings["enabledPlugins"]["extra@shipmill"] = False
    path = write(tmp_path, ".claude/settings.json", json.dumps(settings) + "\n")  # one line
    kept = ss.fix_plugin(path, ss.load_settings(path), "host")
    expected = {"permissions": {"deny": []}, "enabledPlugins": {"extra@shipmill": False}}
    assert kept == expected
    assert path.read_text(encoding="utf-8") == json.dumps(expected) + "\n"


def test_s033_3_host_fix_drops_the_objects_left_empty(ss: ModuleType, tmp_path: Path) -> None:
    path = write(tmp_path, ".claude/settings.json", json.dumps(committed(permissions={}), indent=2) + "\n")
    kept = ss.fix_plugin(path, ss.load_settings(path), "host")
    assert kept == {"permissions": {}}
    assert path.read_text(encoding="utf-8") == '{\n  "permissions": {}\n}\n'


@pytest.mark.parametrize("settings", [committed(), {"enabledPlugins": {"shipmill@shipmill": True}}])
def test_s033_3_host_fix_deletes_the_file_left_with_no_keys(
    ss: ModuleType, tmp_path: Path, settings: dict[str, Any]
) -> None:
    path = write(tmp_path, ".claude/settings.json", json.dumps(settings, indent=2) + "\n")
    assert ss.fix_plugin(path, ss.load_settings(path), "host") == {}
    assert not path.exists()


def test_s033_4_repo_mode_fix_leaves_a_committed_plugin_byte_for_byte(ss: ModuleType, tmp_path: Path) -> None:
    text = json.dumps(committed(permissions={"allow": []}), indent=4)
    path = write(tmp_path, ".claude/settings.json", text)
    settings = ss.load_settings(path)
    assert ss.fix_plugin(path, settings, "repo") == settings
    assert path.read_text(encoding="utf-8") == text


def test_s033_4_repo_mode_reads_the_settings_and_fix_writes_them(ss: ModuleType, tmp_path: Path) -> None:
    path = write(tmp_path, ".claude/settings.json", SETTINGS_TEXT)
    settings = ss.load_settings(path)
    assert [r.state for r in ss.plugin_rows(settings, lambda: [])] == ["PLUGIN_MISSING"]
    merged = ss.fix_plugin(path, settings, "repo")
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written == merged
    assert written["permissions"] == {"allow": ["Bash(ls)"]}
    assert written["enabledPlugins"] == {"other@mine": True, "shipmill@shipmill": True}
    assert written["extraKnownMarketplaces"]["shipmill"]["source"] == {"source": "github", "repo": "shipmill/shipmill"}
    assert [r.state for r in ss.plugin_rows(written, lambda: [])] == ["PLUGIN_OK"]
    (tmp_path / "fresh").mkdir()
    absent = tmp_path / "fresh" / ".claude" / "settings.json"
    ss.fix_plugin(absent, {}, "repo")
    assert json.loads(absent.read_text(encoding="utf-8"))["enabledPlugins"] == {"shipmill@shipmill": True}


@pytest.mark.parametrize("mode", ["host", "repo"])
def test_s033_4_disabled_reads_disabled_in_either_mode_and_fix_leaves_it(
    ss: ModuleType, tmp_path: Path, mode: str
) -> None:
    text = '{"enabledPlugins": {"shipmill@shipmill": false}}'
    path = write(tmp_path, ".claude/settings.json", text)
    settings = ss.load_settings(path)
    rows = ss.plugin_rows(settings, lambda: []) if mode == "repo" else host_rows(ss, settings, listing())
    assert [r.state for r in rows] == ["PLUGIN_DISABLED"]
    ss.fix_plugin(path, settings, mode)
    assert path.read_text(encoding="utf-8") == text


# setup_state.py as the skill runs it: a fake gh, no claude on PATH, a HOME of its own

FAKE_SETUP_GH = """#!{python}
import json, sys
args = sys.argv[1:]
if args[:2] == ["label", "list"]:
    print("[]")
elif any(a.endswith("marketplace.json") for a in args):
    entry = {{"name": "shipmill", "source": {{"source": "github", "repo": "shipmill/shipmill", "ref": "v0.80.1"}}}}
    print(json.dumps({{"plugins": [entry]}}))
elif args[:1] == ["api"] and "repos/romamo/demo" in args:
    print("true")
elif args[:2] == ["label", "create"]:
    pass
else:
    sys.stderr.write("unexpected gh " + " ".join(args) + "\\n")
    sys.exit(1)
"""


def setup_repo(tmp_path: Path, config: str, settings: str | None) -> Path:
    root = tmp_path / "demo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    Git(root).run("remote", "add", "origin", f"https://github.com/{REPO}.git")
    write(root, ".github/shipmill.toml", config)
    write(root, "CONTRIBUTING.md", "# Contributing\n\nOpen an issue first.\n")
    if settings is not None:
        write(root, ".claude/settings.json", settings)
    return root


def run_setup(tmp_path: Path, root: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    fakes = tmp_path / "fakes"
    fakes.mkdir(exist_ok=True)
    executable(fakes / "gh", FAKE_SETUP_GH.format(python=sys.executable))
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]), "HOME": str(home)}
    command = [sys.executable, str(SETUP), REPO, "--repo-dir", str(root), "--json", *flags]
    return subprocess.run(command, capture_output=True, text=True, check=False, env=env)


def states(done: subprocess.CompletedProcess[str]) -> dict[str, str]:
    assert done.returncode in (0, 1), done.stderr
    return {row["state"]: row["detail"] for row in map(json.loads, done.stdout.splitlines())}


GATE = '[agents]\nprompt = "/shipmill:github-issue-triage {repo}"\nmode = "headless"\n'


@pytest.mark.parametrize("settings", [None, SETTINGS_TEXT])
def test_s033_2_fix_in_host_mode_never_touches_settings_without_the_plugin(
    tmp_path: Path, settings: str | None
) -> None:
    root = setup_repo(tmp_path, GATE, settings)
    found = states(run_setup(tmp_path, root, "--fix"))
    path = root / ".claude" / "settings.json"
    if settings is None:
        assert not (root / ".claude").exists()
    else:
        assert path.read_text(encoding="utf-8") == settings
    assert found["PLUGIN_OK"] == "claude isn't on PATH, installs not read"


COMMITTED_TEXT = (
    '{\n  "permissions": {\n    "allow": ["Bash(ls)"]\n  },\n  "extraKnownMarketplaces": {\n'
    '    "shipmill": {"source": {"source": "github", "repo": "shipmill/shipmill"}}\n  },\n'
    '  "enabledPlugins": {\n    "shipmill@shipmill": true\n  }\n}\n'
)
LEFT_TEXT = '{\n  "permissions": {\n    "allow": [\n      "Bash(ls)"\n    ]\n  }\n}\n'


def test_s033_3_fix_in_host_mode_removes_the_committed_plugin_end_to_end(tmp_path: Path) -> None:
    root = setup_repo(tmp_path, GATE, COMMITTED_TEXT)
    before = run_setup(tmp_path, root)
    assert before.returncode == 1
    assert '--fix removes "shipmill@shipmill"' in states(before)["PLUGIN_COMMITTED"]
    path = root / ".claude" / "settings.json"
    assert path.read_text(encoding="utf-8") == COMMITTED_TEXT  # a read changes nothing
    found = states(run_setup(tmp_path, root, "--fix"))
    assert "PLUGIN_COMMITTED" not in found
    assert found["PLUGIN_OK"] == "claude isn't on PATH, installs not read"
    assert path.read_text(encoding="utf-8") == LEFT_TEXT


def test_s033_3_fix_in_host_mode_deletes_a_settings_file_left_empty_end_to_end(tmp_path: Path) -> None:
    root = setup_repo(tmp_path, GATE, '{"enabledPlugins": {"shipmill@shipmill": true}}')
    found = states(run_setup(tmp_path, root, "--fix"))
    assert not (root / ".claude" / "settings.json").exists()
    assert found["PLUGIN_OK"] == "claude isn't on PATH, installs not read"


def test_s033_4_fix_in_repo_mode_writes_the_settings(tmp_path: Path) -> None:
    root = setup_repo(tmp_path, GATE + 'plugin = "repo"\n', SETTINGS_TEXT)
    assert "PLUGIN_MISSING" in states(run_setup(tmp_path, root))
    assert "PLUGIN_OK" in states(run_setup(tmp_path, root, "--fix"))
    written = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert written["enabledPlugins"] == {"other@mine": True, "shipmill@shipmill": True}
    assert written["permissions"] == {"allow": ["Bash(ls)"]}


# --- S-033-9: the gate hands every session the key it used -------------------------------------


def test_s033_9_session_env_names_the_keys_absolute_path(tmp_path: Path) -> None:
    folder = tmp_path / "bin"
    helpers = Helpers(folder, folder / "gh", folder / "git-credential-shipmill", Path("/usr/bin/gh"))
    identity = Identity(APP_ID, "demo-agent", BOT_ID, tmp_path / "keys" / ".." / "app.pem")  # as --app-key gave it
    env = session_env(identity, helpers, "/usr/bin")
    assert env[APP_KEY] == str((tmp_path / "app.pem").resolve())
    assert Path(env[APP_KEY]).is_absolute()
    assert {"GIT_AUTHOR_NAME", "GIT_CONFIG_COUNT", "PATH"} <= set(env)  # beside the env D-14 sets


def test_s033_9_an_interactive_session_gets_it_in_its_settings(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    git = Git(root)
    git.run("remote", "add", "origin", f"https://github.com/{REPO}.git")

    commands: list[list[str]] = []

    def run(cmd: list[str], cwd: Path) -> str:
        commands.append(cmd)
        return "[]" if cmd[:2] == ["claude", "agents"] else "started; claude attach s9\n"

    launch_as_app(git, tmp_path, ClaudeCli([], run=run))
    started = commands[-1]
    env = json.loads(started[started.index("--settings") + 1])["env"]
    assert env[APP_KEY] == str((tmp_path / "app.pem").resolve())  # the gate's --app-key


def test_s033_9_a_headless_session_gets_it_in_its_settings(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    git = Git(root)
    git.run("remote", "add", "origin", f"https://github.com/{REPO}.git")
    spawned = Spawned()
    claude = ClaudeCli([], run=spawned.runner, spawn=spawned)
    tick(git, headless(APP_ID), claude, Reads(), app=app_check_for(tmp_path), app_env=Prepared(git, gh_path(tmp_path)))
    [(cmd, _, _)] = spawned.commands
    env = json.loads(cmd[cmd.index("--settings") + 1])["env"]
    assert env[APP_KEY] == str((tmp_path / "app.pem").resolve())


def test_s033_9_the_default_key_is_named_when_the_gate_has_no_app_key(tmp_path: Path) -> None:
    """app_check reads ~/.config/shipmill/app-<app_id>.pem without --app-key; the session gets it"""
    home = tmp_path / "home"
    key = home / ".config" / "shipmill" / f"app-{APP_ID}.pem"
    key.parent.mkdir(parents=True)
    key.write_text("not a key\n", encoding="utf-8")
    key.chmod(0o600)
    identity = app_check(REPO, None, home, FakeSigner(), FakeApi())(APP_ID)
    folder = tmp_path / "bin"
    helpers = Helpers(folder, folder / "gh", folder / "git-credential-shipmill", Path("/usr/bin/gh"))
    assert session_env(identity, helpers, "/usr/bin")[APP_KEY] == str(key.resolve())


# --- S-033-10: a real claude -p sees the --settings env -----------------------------------------

PROBE = os.environ.get("SHIPMILL_CLAUDE_PROBE")  # set to 1 to run the probe against the real claude


def probe_command(prompt: str, settings: str) -> list[str]:
    """The prompt goes right after -p: --allowedTools takes several values and swallows any
    argument after it"""
    return ["claude", "-p", prompt, "--plugin-dir", str(ROOT), "--settings", settings, "--allowedTools", "Bash(gh *)"]


def test_s033_10_the_probe_passes_its_prompt_before_the_flags() -> None:
    command = probe_command("the prompt", "{}")
    assert command[1:3] == ["-p", "the prompt"]
    assert command[-2:] == ["--allowedTools", "Bash(gh *)"]


@pytest.mark.skipif(PROBE != "1" or shutil.which("claude") is None, reason="a real claude -p probe, run by hand")
def test_s033_10_a_hook_in_a_real_claude_session_sees_the_settings_env(tmp_path: Path) -> None:
    """The spec's probe: a session started with --settings whose env sets SHIPMILL_APP_KEY, in a
    repo with app_id and no key file, has its plain gh write refused by this checkout's hook.
    The write names a repo that doesn't exist, so it changes nothing if it runs"""
    repo = tmp_path / "probe"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    write(repo, ".github/shipmill.toml", '[agents]\nprompt = "/t"\napp_id = 999999999\n')
    settings = json.dumps({"enabledPlugins": {"shipmill@shipmill": False}, "env": {APP_KEY: "/tmp/x"}})
    command = f"gh label create probe --repo shipmill-probe/{tmp_path.name}-does-not-exist"
    prompt = (
        f"Run exactly this one Bash command, unchanged, once: {command}\n"
        "Then reply with SHIPMILL-HOOK-REFUSED if a PreToolUse hook blocked it naming app-writes, else RAN."
    )
    done = subprocess.run(
        probe_command(prompt, settings),
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert "SHIPMILL-HOOK-REFUSED" in done.stdout, done.stdout + done.stderr


# --- S-033-11: shipmill gh and app-token read SHIPMILL_APP_KEY ----------------------------------


@pytest.fixture
def host(tmp_path: Path) -> Host:
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    executable(fakes / "gh", FAKE_GH)
    record = tmp_path / "record"
    record.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return Host(fakes, record, home)


def test_s033_11_gh_takes_the_key_from_shipmill_app_key(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    key = key_file(tmp_path)
    signer = FakeSigner()
    runner = Runner(code=0)
    code = main(
        ["--repo", str(root), "gh", "issue", "comment", "1", "--body", "x"],
        api=MintApi(),
        signer=signer,
        environ=host.env(**{APP_KEY: str(key)}),
        home=host.home,  # no key at the default path
        gh_runner=runner,
    )
    assert code == 0
    assert {path for path, _ in signer.signed} == {key}
    assert runner.calls[0][1]["GH_TOKEN"] == "token-1"


def test_s033_11_a_leading_app_key_wins_over_the_variable(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    key = key_file(tmp_path)
    signer = FakeSigner()
    args = ["--repo", str(root), "gh", "--app-key", str(key), "pr", "list"]
    environ = host.env(**{APP_KEY: str(tmp_path / "elsewhere.pem")})
    assert main(args, api=MintApi(), signer=signer, environ=environ, home=host.home, gh_runner=Runner(code=0)) == 0
    assert {path for path, _ in signer.signed} == {key}


@pytest.mark.parametrize("named", [None, "", "/nowhere/app.pem"])
def test_s033_11_no_key_exits_2_saying_the_app_isnt_available_and_never_runs_gh(
    tmp_path: Path, host: Host, named: str | None
) -> None:
    root = checkout(tmp_path, WITH_APP)
    api, signer, runner = MintApi(), FakeSigner(), Runner()
    environ = host.env() if named is None else host.env(**{APP_KEY: named})
    with pytest.raises(ReleaseError) as raised:  # cli.run prints it and exits 2
        main(["--repo", str(root), "gh", "pr", "create"], api=api, signer=signer, environ=environ, home=host.home)
    path = named or str(host.home / ".config" / "shipmill" / f"app-{APP_ID}.pem")
    first, second = str(raised.value).split("\n")
    assert first == f"no App private key at {path}; download it from the App's settings to that path"
    assert second == (
        "the App isn't available here, so shipmill writes nothing: a skill hands you its text to post, "
        "and what you post yourself with gh is yours (spec 033)"
    )
    assert (runner.calls, api.calls, api.posts, signer.signed) == ([], [], [], [])


def test_s033_11_the_message_through_the_cli_is_two_lines_on_exit_2(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    env = {**host.env(), "HOME": str(host.home)}
    done = subprocess.run(
        [sys.executable, "-m", "shipmill", "--repo", str(root), "gh", "pr", "create"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert done.returncode == 2
    lines = done.stderr.splitlines()
    assert lines[0].startswith("shipmill: no App private key at ") and "the App isn't available here" in lines[1]
    assert not (host.record / "gh-args").exists()


def test_s033_11_app_token_reads_the_variable_the_same_way(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, None)
    key = key_file(tmp_path)
    signer = FakeSigner()
    args = ["--repo", str(root), "app-token", REPO, "--app-id", str(APP_ID)]
    assert main(args, api=MintApi(), signer=signer, environ={APP_KEY: str(key)}, home=host.home) == 0
    assert capsys.readouterr().out == "token-1\n"
    assert {path for path, _ in signer.signed} == {key}


def test_s033_11_app_tokens_app_key_wins_over_the_variable(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, None)
    key = key_file(tmp_path)
    signer = FakeSigner()
    args = ["--repo", str(root), "app-token", REPO, "--app-id", str(APP_ID), "--app-key", str(key)]
    environ = {APP_KEY: str(tmp_path / "elsewhere.pem")}
    assert main(args, api=MintApi(), signer=signer, environ=environ, home=host.home) == 0
    assert {path for path, _ in signer.signed} == {key}


# --- S-033-12: doctor's app-writes line ---------------------------------------------------------


def test_s033_12_doctor_says_which_case_the_host_is_in(tmp_path: Path) -> None:
    home = tmp_path / "home"
    path = home / ".config" / "shipmill" / f"app-{APP_ID}.pem"
    assert app_writes(None, home).startswith("app-writes: off (no [agents] app_id)")
    missing = app_writes(APP_ID, home)
    assert missing.startswith(f"app-writes: on in gate sessions only (no key at {path} on this host;")
    assert "SHIPMILL_APP_KEY" in missing
    path.parent.mkdir(parents=True)
    path.write_text("not a key\n", encoding="utf-8")
    path.chmod(0)  # looked for, never read
    try:
        assert app_writes(APP_ID, home).startswith(f"app-writes: on (the App's key is at {path})")
    finally:
        path.chmod(0o600)


def test_s033_12_doctors_hooks_block_carries_the_line(repo: Repo, tmp_path: Path) -> None:
    config = str(CONFIG_PATH)
    repo.write(config, repo.read(config) + f'\n[agents]\nprompt = "/t"\napp_id = {APP_ID}\n')
    home = tmp_path / "no-key-home"
    found = [c.detail for c in doctor(repo.root, home=home) if c.name == "hooks"]
    assert found[0].startswith("app-writes: on in gate sessions only (no key at ")


# --- S-033-13, S-033-14: init's commented key, and nothing for a client's CONTRIBUTING.md ----------

CHANGELOG = "# Changelog\n\n## [Unreleased]\n"


def test_s033_13_init_writes_a_commented_plugin_line_and_still_parses(tmp_path: Path) -> None:
    write(tmp_path, "CHANGELOG.md", CHANGELOG)
    written = init(tmp_path, "ci.yml", force=False).written
    text = written[0].read_text(encoding="utf-8")
    [line] = [line for line in text.splitlines() if line.startswith('# plugin = "host"')]
    assert '"repo"' in line and ".claude/settings.json" in line
    tomllib.loads(text)
    start = text.index("# [agents]")
    block = text[start:].split("\n\n", 1)[0]
    example = "\n".join(line.removeprefix("#").removeprefix(" ") for line in block.splitlines())
    written[0].write_text(text[:start] + example + "\n", encoding="utf-8")
    assert AgentsConfig.load(tmp_path).plugin is Plugin.HOST  # uncommented, it reads as host


def test_s033_14_init_and_setup_fix_leave_contributing_alone(tmp_path: Path) -> None:
    root = setup_repo(tmp_path, GATE, None)
    write(root, "CHANGELOG.md", CHANGELOG)
    before = (root / "CONTRIBUTING.md").read_bytes()
    init(root, "ci.yml", force=True)
    states(run_setup(tmp_path, root, "--fix"))
    assert (root / "CONTRIBUTING.md").read_bytes() == before


def test_s033_14_no_skill_or_package_file_holds_text_for_a_clients_contributing() -> None:
    """Only two files name CONTRIBUTING.md: setup_state.py, which reads it for a stale rule
    (D-42), and shipmill-setup's SKILL.md, which says never to edit it or draft text for it"""
    naming = sorted(
        str(path.relative_to(ROOT))
        for folder in ("skills", "src/shipmill")
        for path in (ROOT / folder).rglob("*")
        if path.is_file() and path.suffix != ".pyc" and "CONTRIBUTING" in path.read_text(encoding="utf-8")
    )
    assert naming == ["skills/shipmill-setup/SKILL.md", "skills/shipmill-setup/scripts/setup_state.py"]
    assert "never edit CLAUDE.md, AGENTS.md, or CONTRIBUTING.md, nor draft text for them" in folded(
        "skills", "shipmill-setup", "SKILL.md"
    )


# --- S-033-15: the docs ---------------------------------------------------------------------------


def test_s033_15_install_describes_the_per_person_default_and_the_opt_in() -> None:
    text = folded("docs", "install.md")
    for phrase in (
        "The plugin is installed per person by default",
        "claude plugin install shipmill@shipmill --scope user",
        '`[agents] plugin = "repo"`',
        '"enabledPlugins": { "shipmill@shipmill": true }',
        '`--fix` writes the plugin into `.claude/settings.json` only with `plugin = "repo"`',
    ):
        assert phrase in text, phrase


def test_s033_15_install_has_a_contributors_section() -> None:
    text = folded("docs", "install.md")
    assert text.count("## Contributors") == 1
    section = text.split("## Contributors", 1)[1].split(" ## ", 1)[0]
    for phrase in (
        "shipmill writes to GitHub only as the App",
        "hand the person the text to post",
        "`app-writes` rule applies only where the App's key is, or in gate sessions",
        "goes out as them",
        "never landed automatically (D-16)",
        "shipmill writes nothing to the repo's `CONTRIBUTING.md`, `README.md`, or other docs",
        "`SHIPMILL_APP_KEY`",
    ):
        assert phrase in section, phrase


def test_s033_15_release_lanes_lists_the_plugin_key_and_setup_names_the_row() -> None:
    lanes = folded("docs", "release-lanes.md")
    assert "`[agents] plugin`" in lanes and 'plugin = "repo"' in lanes
    setup = folded("skills", "shipmill-setup", "SKILL.md")
    assert "`PLUGIN_COMMITTED`" in setup
    assert "Ask where the plugin loads" in setup


# --- S-033-16: app-token --check ---------------------------------------------------------------


class NoNetwork:
    def get(self, path: str, token: str | None) -> Answer:
        raise AssertionError(f"--check made a network call: GET {path}")

    def post(self, path: str, token: str, body: Mapping[str, object]) -> Answer:
        raise AssertionError(f"--check made a network call: POST {path}")


class NoSigner:
    def sign(self, key: Path, data: bytes) -> bytes:
        raise AssertionError("--check signed a JWT")


def check(root: Path, environ: dict[str, str], home: Path) -> int:
    return main(
        ["--repo", str(root), "app-token", "--check"], api=NoNetwork(), signer=NoSigner(), environ=environ, home=home
    )


def test_s033_16_check_exits_0_naming_the_app_and_the_test_that_held(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, WITH_APP)
    home = tmp_path / "home"
    assert check(root, {APP_KEY: "/nowhere/app.pem"}, home) == 0
    assert capsys.readouterr() == (f"the App {APP_ID} is available here: SHIPMILL_APP_KEY is set\n", "")
    key = home / ".config" / "shipmill" / f"app-{APP_ID}.pem"
    key.parent.mkdir(parents=True)
    key.write_text("not a key\n", encoding="utf-8")
    key.chmod(0)  # stat, never read
    try:
        assert check(root / ".github", {}, home) == 0
    finally:
        key.chmod(0o600)
    assert capsys.readouterr() == (f"the App {APP_ID} is available here: its key is at {key}\n", "")
    assert not (root / ".git" / "shipmill").exists()  # no token cache: nothing minted


@pytest.mark.parametrize("environ", [{}, {APP_KEY: ""}])
def test_s033_16_check_exits_2_naming_the_path_and_the_variable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], environ: dict[str, str]
) -> None:
    root = checkout(tmp_path, WITH_APP)
    home = tmp_path / "home"
    with pytest.raises(ReleaseError) as raised:
        check(root, environ, home)
    path = home / ".config" / "shipmill" / f"app-{APP_ID}.pem"
    assert str(raised.value) == f"the App {APP_ID} isn't available here: no key at {path} and no SHIPMILL_APP_KEY"
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("config", [None, '[agents]\nprompt = "/t"\n', "[release]\n"])
def test_s033_16_check_without_app_id_exits_2_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str | None
) -> None:
    root = checkout(tmp_path, config)
    with pytest.raises(ReleaseError, match=r"no \[agents\] app_id in .*\.github/shipmill\.toml"):
        check(root, {APP_KEY: "/k.pem"}, tmp_path)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "extra",
    [[REPO], ["--app-id", "1"], ["--app-key", "k.pem"], ["--git-credential", "get"], ["--product"]],
)
def test_s033_16_check_takes_nothing_else(tmp_path: Path, extra: list[str]) -> None:
    root = checkout(tmp_path, WITH_APP)
    with pytest.raises(ReleaseError, match="app-token --check takes no"):
        main(["--repo", str(root), "app-token", "--check", *extra], api=NoNetwork(), signer=NoSigner(), environ={})


def test_s033_16_without_check_a_token_still_needs_the_repo_and_the_app_id(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="app-token needs owner/name and --app-id, or --check alone"):
        main(["--repo", str(tmp_path), "app-token", REPO], api=NoNetwork(), signer=NoSigner(), environ={})


# --- S-033-17: the skills' "Write as the App" rule ---------------------------------------------


def write_rule(skill: str) -> str:
    """The skill's "Write as the App" rule, folded: its paragraph or list item"""
    text = folded("skills", skill, "SKILL.md")
    at = text.index("Write as the App")
    end = text.find(" **", at + len("Write as the App") + 3)
    ends = [i for i in (end, text.find(" ## ", at)) if i != -1]
    return text[at : min(ends)] if ends else text[at:]


@pytest.mark.parametrize("skill", SKILLS)
def test_s033_17_each_skills_write_rule_checks_stops_hands_over_and_never_writes_as_the_person(skill: str) -> None:
    rule = write_rule(skill)
    for phrase in (
        "`shipmill app-token --check` before its first write to GitHub, a push included",
        "the App isn't available here",
        "hands over the text of each write it would have made",
        "its target and the exact text",
        "never writes with plain `gh`, `GH_TOKEN`, or a push as the person",
        "never asks for or fetches the key",
        "a `shipmill gh` exit 2 naming the missing key",
    ):
        assert phrase in rule, (skill, phrase)


# --- S-033-18: the eval case ---------------------------------------------------------------------


CASE = ROOT / "evals" / "github-issue-resolve" / "no-app-drafts"
SHIM = ROOT / "evals" / "bin" / "shipmill"


def test_s033_18_an_eval_case_runs_resolve_without_the_app() -> None:
    cases = tomllib.loads((ROOT / "evals" / "cases.toml").read_text(encoding="utf-8"))["case"]
    [entry] = [c for c in cases if c["path"] == "github-issue-resolve/no-app-drafts"]
    assert (entry["skill"], entry["kind"]) == ("github-issue-resolve", "fix")
    commit = entry["commit"]
    config = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{commit}:.github/shipmill.toml"], capture_output=True, text=True, check=True
    ).stdout
    assert tomllib.loads(config)["agents"]["app_id"]  # the workspace sets app_id
    assert (CASE / "fixture" / "no-app").is_file()  # and runs without the App
    graders = (CASE / "case.yaml").read_text(encoding="utf-8")
    for phrase in ('"kind": "check"', '"kind": "(write|refused)"', "match: not_contains"):
        assert phrase in graders, phrase
    for phrase in ("the App isn't available here", "nothing was written to GitHub", "no `git push`"):
        assert phrase in graders, phrase
    assert "pull request title" in graders and "pull request body" in graders and "local branch" in graders


def shim(tmp_path: Path, link: str, *args: str, no_app: bool) -> tuple[subprocess.CompletedProcess[str], list[Any]]:
    """The eval's shipmill or uvx shim run in a workspace with .eval/, with or without the App"""
    eval_dir = tmp_path / "work" / ".eval"
    (eval_dir / "gh").mkdir(parents=True, exist_ok=True)
    (eval_dir / "gh.jsonl").write_text("", encoding="utf-8")
    marker = eval_dir / "no-app"
    if no_app:
        marker.write_text("no App\n", encoding="utf-8")
    elif marker.exists():
        marker.unlink()
    program = tmp_path / "bin" / link
    if not program.exists():
        program.parent.mkdir(exist_ok=True)
        program.symlink_to(SHIM)
    done = subprocess.run(
        [sys.executable, str(program), *args],
        cwd=eval_dir.parent,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "HOME": str(tmp_path)},
    )
    return done, [json.loads(line) for line in (eval_dir / "gh.jsonl").read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize(("link", "head"), [("shipmill", []), ("uvx", ["shipmill==0.80.1"])])
def test_s033_18_the_eval_shim_answers_the_check_with_and_without_the_app(
    tmp_path: Path, link: str, head: list[str]
) -> None:
    done, logged = shim(tmp_path, link, *head, "--repo", ".", "app-token", "--check", no_app=False)
    assert (done.returncode, logged) == (0, [{"kind": "check", "args": ["--repo", ".", "app-token", "--check"]}])
    done, logged = shim(tmp_path, link, *head, "app-token", "--check", no_app=True)
    assert done.returncode == 2 and "the App isn't available here" in done.stderr
    assert logged == [{"kind": "check", "args": ["app-token", "--check"]}]
    done, logged = shim(tmp_path, link, *head, "gh", "pr", "create", "--title", "t", no_app=True)
    assert done.returncode == 2
    assert done.stderr.splitlines()[0].startswith("shipmill: no App private key at ")
    assert "the App isn't available here" in done.stderr.splitlines()[1]
    assert logged == [{"kind": "refused", "via": "shipmill", "args": ["pr", "create", "--title", "t"]}]
