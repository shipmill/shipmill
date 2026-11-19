"""Spec 082: whom agents write to GitHub as is chosen once per repo, at setup. [agents]
identity reads "app", "host", or "none" in shipmill and in setup_state.py, and setup_state.py
prints one Identity row. No test reaches the network: gh is a fake"""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.agents import AgentsConfig, WriteAs, gh_identity_of
from shipmill.errors import ReleaseError

from .test_app import APP_ID
from .test_app_gh import WITH_APP, checkout
from .test_contributors import run_setup, setup_repo, states

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "shipmill-setup" / "scripts" / "setup_state.py"
AGENTS = '[agents]\nprompt = "/t"\n'
BAD = ['"App"', '"nobody"', '""', "1", "true", '["none"]']
VALUES = '"app" (the default), "host", or "none"'


@pytest.fixture(scope="module")
def ss() -> ModuleType:
    spec = importlib.util.spec_from_file_location("setup_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


def config(root: Path, text: str) -> Path:
    path = root / ".github" / "shipmill.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return root


# -- S-082-1: three values, in shipmill and in setup_state.py -------------------------------


@pytest.mark.parametrize(("extra", "want"), [("", WriteAs.APP), *((f'identity = "{w}"\n', w) for w in WriteAs)])
def test_s082_1_agents_config_reads_the_three_values(tmp_path: Path, extra: str, want: WriteAs) -> None:
    root = checkout(tmp_path, AGENTS + extra)
    assert AgentsConfig.load(root).identity is want
    assert gh_identity_of(root).identity is want


@pytest.mark.parametrize("value", BAD)
def test_s082_1_any_other_identity_exits_2_naming_the_key_and_the_three_values(tmp_path: Path, value: str) -> None:
    root = checkout(tmp_path, f"{AGENTS}identity = {value}\n")
    for load in (lambda: AgentsConfig.load(root), lambda: gh_identity_of(root)):
        with pytest.raises(ReleaseError) as raised:
            load()
        assert f"[agents] identity must be {VALUES}" in str(raised.value)


@pytest.mark.parametrize("value", ["none", "host"])
def test_s082_1_none_or_host_with_app_id_exits_2_naming_both_keys(tmp_path: Path, value: str) -> None:
    root = checkout(tmp_path, f'{WITH_APP}identity = "{value}"\n')
    for load in (lambda: AgentsConfig.load(root), lambda: gh_identity_of(root)):
        with pytest.raises(ReleaseError, match=rf'\[agents\] identity = "{value}" and \[agents\] app_id'):
            load()


@pytest.mark.parametrize(
    ("text", "want"),
    [
        (None, (False, None, "app")),
        ('mode = "release"\n', (False, None, "app")),
        (AGENTS, (True, None, "app")),
        (AGENTS + 'identity = "app"\n', (True, None, "app")),
        (AGENTS + 'identity = "host"\n', (True, None, "host")),
        (AGENTS + "identity = 'none'\n", (True, None, "none")),
        (WITH_APP, (True, str(APP_ID), "app")),
        (WITH_APP + 'identity = "app"\n', (True, str(APP_ID), "app")),
    ],
)
def test_s082_1_setup_state_reads_the_same_three_values(
    ss: ModuleType, tmp_path: Path, text: str | None, want: tuple[bool, str | None, str]
) -> None:
    if text is not None:
        config(tmp_path, text)
    found = ss.identity_of(tmp_path, ss.watch_module())
    assert (found.section, found.app_id, found.identity) == want


@pytest.mark.parametrize(
    "text",
    [
        *(f"{AGENTS}identity = {value}\n" for value in BAD),
        f'{WITH_APP}identity = "none"\n',
        f'{WITH_APP}identity = "host"\n',
    ],
)
def test_s082_1_setup_state_refuses_the_same_input_with_exit_2(
    ss: ModuleType, tmp_path: Path, text: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        ss.identity_of(config(tmp_path, text), ss.watch_module())
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert f"[agents] identity must be {VALUES}" in err or "and [agents] app_id can't both be set" in err


def test_s082_1_setup_state_reads_and_refuses_on_python_310(tmp_path: Path) -> None:
    cases = {
        "absent": AGENTS,
        "host": AGENTS + 'identity = "host"\n',
        "none": AGENTS + 'identity = "none"\n',
        "app": WITH_APP,
        "other": AGENTS + 'identity = "nobody"\n',
        "number": AGENTS + "identity = 1\n",
        "both": WITH_APP + 'identity = "none"\n',
    }
    for name, text in cases.items():
        config(tmp_path / name, text)
    uv = shutil.which("uv")
    assert uv is not None, "uv runs the skill scripts"
    code = (
        "import importlib.util, sys; from pathlib import Path\n"
        "spec = importlib.util.spec_from_file_location('setup_state', sys.argv[1])\n"
        "ss = importlib.util.module_from_spec(spec); sys.modules['setup_state'] = ss; spec.loader.exec_module(ss)\n"
        "ws = ss.watch_module(); assert ws.tomllib is None, 'tomllib on 3.10'\n"
        "for name in sys.argv[3:]:\n"
        "    try:\n"
        "        found = ss.identity_of(Path(sys.argv[2]) / name, ws)\n"
        "        print(name, found.identity, found.app_id)\n"
        "    except SystemExit as exc:\n"
        "        print(name, 'exit', exc.code)\n"
    )
    command = [uv, "run", "--no-project", "--python", "3.10", "python", "-c", code, str(SCRIPT), str(tmp_path)]
    done = subprocess.run([*command, *cases], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == [
        "absent app None",
        "host host None",
        "none none None",
        f"app app {APP_ID}",
        "other exit 2",
        "number exit 2",
        "both exit 2",
    ]


# -- S-082-7: one Identity row --------------------------------------------------------------


class FakeOwner:
    """gh for the owner's listing and its configs; anything else fails the test"""

    def __init__(self, configs: dict[str, str | None]) -> None:
        self.configs = configs
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> str | None:
        self.calls.append(cmd)
        if cmd[:3] == ["gh", "api", "users/me"]:
            return "User\n"
        if cmd[:3] == ["gh", "api", "user"]:
            return "me\n"
        if "--paginate" in cmd:
            return "".join(f"false {name}\n" for name in ["me/demo", *self.configs])
        name = cmd[-1].removeprefix("repos/").removesuffix("/contents/.github/shipmill.toml")
        return self.configs[name]


def keys(home: Path, *names: str) -> None:
    folder = home / ".config" / "shipmill"
    folder.mkdir(parents=True)
    for name in names:
        (folder / name).write_text("not a key\n", encoding="utf-8")
        (folder / name).chmod(0)  # opening it would fail: the row lists names alone


def row(ss: ModuleType, root: Path, home: Path, gh: FakeOwner) -> Any:
    """setup_state.py's Row, untyped: the script is loaded from its path"""
    ws = ss.watch_module()
    return ss.identity_row("me/demo", ss.identity_of(root, ws), home, ws, gh)


@pytest.mark.parametrize(
    ("text", "state", "named"),
    [
        (WITH_APP, "IDENTITY_APP", str(APP_ID)),
        (AGENTS + 'identity = "host"\n', "IDENTITY_HOST", 'identity = "host"'),
        (AGENTS + 'identity = "none"\n', "IDENTITY_NONE", 'identity = "none"'),
    ],
)
def test_s082_7_a_recorded_choice_is_done_and_reads_no_sibling(
    ss: ModuleType, tmp_path: Path, text: str, state: str, named: str
) -> None:
    gh = FakeOwner({"me/api": WITH_APP})
    found = row(ss, config(tmp_path / "demo", text), tmp_path / "home", gh)
    assert found.state == state and named in found.detail
    assert state in ss.DONE and gh.calls == []
    assert ss.exit_code([ss.Row("RELEASE_READY", ""), found]) == 0


def test_s082_7_unchosen_names_each_app_with_a_key_file_and_each_siblings_app_id(
    ss: ModuleType, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    keys(home, "app-77.pem", f"app-{APP_ID}.pem", "app-x.pem", "other.pem")
    gh = FakeOwner(
        {
            "me/api": WITH_APP,
            "me/web": '[agents]\nprompt = "/t"\napp_id = 9\n',
            "me/bare": None,
            "me/plain": 'mode = "release"\n',
            "me/broken": "[agents\napp_id = 5\n",
        }
    )
    found = row(ss, config(tmp_path / "demo", AGENTS), home, gh)
    assert found.state == "IDENTITY_UNCHOSEN"
    assert found.detail.endswith(
        f"the host's Apps: 9 (me/web), 77 (key at ~/.config/shipmill/app-77.pem),"
        f" {APP_ID} (key at ~/.config/shipmill/app-{APP_ID}.pem, me/api)"
    )
    for choice in ("app_id = <id>", "shipmill app-create", 'identity = "host"', 'identity = "none"'):
        assert choice in found.detail
    for skipped in ("me/broken", "me/bare", "me/plain", "5 ("):  # no App there, or a config it can't read
        assert skipped not in found.detail


def test_s082_7_unchosen_with_no_app_says_so(ss: ModuleType, tmp_path: Path) -> None:
    found = row(ss, config(tmp_path / "demo", AGENTS), tmp_path / "home", FakeOwner({"me/bare": None}))
    assert found.state == "IDENTITY_UNCHOSEN" and found.detail.endswith("the host has no App yet")


@pytest.mark.parametrize(("text", "code"), [(AGENTS, 1), ('mode = "release"\n', 0), (None, 0)])
def test_s082_7_unchosen_is_an_action_only_with_an_agents_section(
    ss: ModuleType, tmp_path: Path, text: str | None, code: int
) -> None:
    root = tmp_path / "demo"
    root.mkdir()
    if text is not None:
        config(root, text)
    found = row(ss, root, tmp_path / "home", FakeOwner({}))
    assert found.state == "IDENTITY_UNCHOSEN"
    done = [ss.Row(state, "") for state in sorted(ss.DONE)]
    assert ss.exit_code([*done, found]) == code


def test_s082_7_the_script_prints_one_identity_row_after_the_agents_rows(tmp_path: Path) -> None:
    root = setup_repo(tmp_path, AGENTS + 'mode = "headless"\n', None)
    keys(tmp_path / "home", "app-77.pem")
    done = run_setup(tmp_path, root)
    rows = [json.loads(line)["state"] for line in done.stdout.splitlines()]
    assert [state for state in rows if state.startswith("IDENTITY_")] == ["IDENTITY_UNCHOSEN"]
    assert rows.index("IDENTITY_UNCHOSEN") == rows.index("AUTONOMY_IMPLICIT") + 1
    assert "77 (key at ~/.config/shipmill/app-77.pem)" in states(done)["IDENTITY_UNCHOSEN"]
    assert done.returncode == 1


def test_s082_7_a_bad_identity_stops_the_script_before_fix_changes_anything(tmp_path: Path) -> None:
    root = setup_repo(tmp_path, AGENTS + 'identity = "nobody"\n', None)
    done = run_setup(tmp_path, root, "--fix")
    assert done.returncode == 2 and f"[agents] identity must be {VALUES}" in done.stderr
    assert done.stdout == ""


def test_s082_7_the_docstring_names_the_rows(ss: ModuleType) -> None:
    for state in ("IDENTITY_APP", "IDENTITY_HOST", "IDENTITY_NONE", "IDENTITY_UNCHOSEN"):
        assert state in (ss.__doc__ or "")
