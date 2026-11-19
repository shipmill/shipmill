"""Spec 082: whom agents write to GitHub as is chosen once per repo, at setup. [agents]
identity reads "app", "host", or "none" in shipmill and in setup_state.py, setup_state.py
prints one Identity row, and `shipmill gh`, `spec open`, and `app-token --check` refuse a write
with the owner's choice or the three choices. No test reaches the network: gh is a fake"""

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

from .test_app import APP_ID, REPO, FakeSigner
from .test_app_gh import WITH_APP, Host, checkout, outside
from .test_app_token import FAKE_GH, MintApi, executable
from .test_contributors import check, run_setup, setup_repo, states
from .test_gh_refuses_without_app import COMMENT, PR_CREATE, choices, one_call, refusal, run
from .test_spec_open import FakeCheckout, FakeGh, repo_files, spec_text
from .test_spec_open import cli as spec_open

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


# -- S-082-2 to S-082-6: the two refusals and app-token --check -----------------------------

NONE = AGENTS + 'identity = "none"\n'
HOST = AGENTS + 'identity = "host"\n'
# not chosen: no config, no [agents], [agents] setting neither key, identity = "app" without app_id
UNCHOSEN = [None, "[release]\n", AGENTS, AGENTS + 'identity = "app"\n']
NOT_IN_OWNERS_CHOICE = ("app-create", "app_id", '"host"', "--as-host")


def owners_choice(repo: str) -> list[str]:
    """The owner's-choice message, the spec's two lines without cli.run's `shipmill: `"""
    return [
        f'refusing a write to {repo}: .github/shipmill.toml sets [agents] identity = "none", so this repo\'s owner '
        "chose that agents don't write to GitHub here",
        "shipmill wrote nothing: hand the text to a person, who posts it as themselves",
    ]


@pytest.mark.parametrize("args", [PR_CREATE, COMMENT])
def test_s082_2_identity_none_refuses_a_write_with_the_owners_choice(
    tmp_path: Path, host: Host, args: list[str]
) -> None:
    lines = refusal(checkout(tmp_path, NONE), args, host)  # gh never ran, no token minted
    assert lines == owners_choice("owner/name" if args is PR_CREATE else REPO)
    for word in NOT_IN_OWNERS_CHOICE:
        assert word not in "\n".join(lines)


def test_s082_2_the_refusal_exits_2_on_stderr_and_never_starts_gh(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, NONE)
    done = subprocess.run(
        [sys.executable, "-m", "shipmill", "--repo", str(root), "gh", *PR_CREATE],
        capture_output=True,
        text=True,
        check=False,
        env={**host.env(), "HOME": str(host.home)},
    )
    assert (done.returncode, done.stdout) == (2, "")
    first, second = owners_choice("owner/name")
    assert done.stderr.splitlines() == [f"shipmill: {first}", second]
    assert not (host.record / "gh-args").exists()


def test_s082_2_identity_none_runs_a_read_as_the_host_with_ghs_exit(tmp_path: Path, host: Host) -> None:
    api, signer = MintApi(), FakeSigner()
    code, runner = run(checkout(tmp_path, NONE), ["pr", "view", "1"], host, api, signer, GH_TOKEN="")
    assert code == 7  # gh's
    [(argv, env)] = runner.calls
    assert argv == [host.gh, "pr", "view", "1"]
    assert "GH_TOKEN" not in env
    assert (api.calls, api.posts, signer.signed) == ([], [], [])


@pytest.mark.parametrize("args", [PR_CREATE, COMMENT])
def test_s082_3_as_host_doesnt_lift_identity_none(tmp_path: Path, host: Host, args: list[str]) -> None:
    lines = refusal(checkout(tmp_path, NONE), ["--as-host", *args], host)
    assert lines == owners_choice("owner/name" if args is PR_CREATE else REPO)


@pytest.mark.parametrize("text", UNCHOSEN)
@pytest.mark.parametrize("args", [PR_CREATE, COMMENT])
def test_s082_4_not_chosen_names_the_three_choices_the_setup_line_and_one_call(
    tmp_path: Path, host: Host, text: str | None, args: list[str]
) -> None:
    first, *middle, last = refusal(checkout(tmp_path, text), args, host)
    repo = "owner/name" if args is PR_CREATE else REPO
    assert first.startswith(f"refusing a write to {repo} as the host's gh login: ")
    assert middle == choices(repo)
    for choice in ("app_id = <id>", "app-create`", 'identity = "host"', 'identity = "none"'):
        assert choice in middle[0]
    assert middle[1] == f"or let setup ask once and record it: /shipmill:shipmill-setup {repo}"
    assert last == one_call(args)


def test_s082_4_outside_a_checkout_the_setup_line_names_a_placeholder(tmp_path: Path, host: Host) -> None:
    _, _, setup, _ = refusal(outside(tmp_path), COMMENT, host)
    assert setup == "or let setup ask once and record it: /shipmill:shipmill-setup <owner/name>"


def test_s082_4_identity_host_still_writes_as_the_host(tmp_path: Path, host: Host) -> None:
    api, signer = MintApi(), FakeSigner()
    code, runner = run(checkout(tmp_path, HOST), COMMENT, host, api, signer, GH_TOKEN="")
    assert code == 7
    [(argv, env)] = runner.calls
    assert argv[:3] == [host.gh, "issue", "comment"] and "GH_TOKEN" not in env
    assert (api.calls, api.posts, signer.signed) == ([], [], [])


def test_s082_5_spec_open_refuses_identity_none_before_its_first_write(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, NONE)
    repo_files(root, spec_text())
    gh, fake, api = FakeGh(), FakeCheckout(), MintApi()
    with pytest.raises(ReleaseError) as raised:
        spec_open(root, host, gh, fake, api)
    assert str(raised.value).split("\n") == owners_choice(REPO)
    assert (gh.calls, fake.published, api.posts) == ([], [], [])


@pytest.mark.parametrize("text", [AGENTS, AGENTS + 'identity = "app"\n'])
def test_s082_5_spec_open_not_chosen_names_the_choices_and_no_one_call(tmp_path: Path, host: Host, text: str) -> None:
    root = checkout(tmp_path, text)
    repo_files(root, spec_text())
    gh, fake, api = FakeGh(), FakeCheckout(), MintApi()
    with pytest.raises(ReleaseError) as raised:
        spec_open(root, host, gh, fake, api)
    first, *rest = str(raised.value).split("\n")
    assert first == f"refusing a write to {REPO} as the host's gh login: .github/shipmill.toml sets no [agents] app_id"
    assert rest == choices(REPO)  # no --as-host line: no one call allows a command of shipmill's own
    assert (gh.calls, fake.published, api.posts) == ([], [], [])


def test_s082_6_check_with_identity_host_exits_0_naming_the_hosts_login(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, HOST)
    assert check(root, {}, tmp_path / "home") == 0
    path = root / ".github" / "shipmill.toml"
    assert capsys.readouterr() == (
        f'writes here go as the host\'s gh login: {path} sets [agents] identity = "host"\n',
        "",
    )
    assert not (root / ".git" / "shipmill").exists()  # no token cache: nothing minted


def test_s082_6_check_with_identity_none_exits_2_with_the_owners_choice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, NONE)
    with pytest.raises(ReleaseError) as raised:  # NoNetwork and NoSigner fail on any call
        check(root, {"SHIPMILL_APP_KEY": "/k.pem"}, tmp_path / "home")
    assert str(raised.value).split("\n") == owners_choice(REPO)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("text", UNCHOSEN)
def test_s082_6_check_not_chosen_exits_2_naming_the_choices_and_setup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str | None
) -> None:
    root = checkout(tmp_path, text)
    with pytest.raises(ReleaseError) as raised:
        check(root, {"SHIPMILL_APP_KEY": "/k.pem"}, tmp_path / "home")
    first, *rest = str(raised.value).split("\n")
    assert first == f"the App isn't available here: no [agents] app_id in {root / '.github' / 'shipmill.toml'}"
    assert rest == choices(REPO)
    assert capsys.readouterr() == ("", "")


def test_s082_6_check_with_app_id_answers_as_s033_16(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = checkout(tmp_path, WITH_APP)
    assert check(root, {"SHIPMILL_APP_KEY": "/nowhere/app.pem"}, tmp_path / "home") == 0
    assert capsys.readouterr() == (f"the App {APP_ID} is available here: SHIPMILL_APP_KEY is set\n", "")
    with pytest.raises(ReleaseError, match=f"the App {APP_ID} isn't available here: no key at"):
        check(root, {}, tmp_path / "home")
    assert not (root / ".git" / "shipmill").exists()
