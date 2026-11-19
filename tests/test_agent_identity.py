"""Spec 082: whom agents write to GitHub as is chosen once per repo, at setup. [agents]
identity reads "app", "host", or "none" in shipmill and in setup_state.py, setup_state.py
prints one Identity row, `shipmill gh`, `spec open`, and `app-token --check` refuse a write
with the owner's choice or the three choices, doctor prints one identity row, and setup asks
the question, the six skills' write rule and docs/install.md say it. No test reaches the
network: gh, GitHub's API, and the signer are fakes"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill import cli_command
from shipmill.agents import AgentsConfig, WriteAs, gh_identity_of
from shipmill.app import Answer
from shipmill.doctor import Check, doctor, identity_on_host
from shipmill.errors import ReleaseError

from .conftest import POLICY
from .test_app import APP_ID, REPO, FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, checkout, outside
from .test_app_install import CHECK_APP, CHECK_PAGE
from .test_app_install import Clock as CheckClock
from .test_app_token import FAKE_GH, MintApi, executable
from .test_contributors import FAKE_SETUP_GH, check, run_setup, setup_repo, states
from .test_gate_github_auth import ACCESS, REPO_PATH, SECRET, ReachApi
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


BAD_GATEWAY = "gh: Bad Gateway (HTTP 502)"
FAILING_GH = """#!{python}
import os, sys
args = sys.argv[1:]
if "repos/romamo/api/contents/.github/shipmill.toml" in args:  # one sibling read fails: not a 404
    sys.stderr.write({error!r} + "\\n")
    sys.exit(1)
if args[:2] == ["api", "--paginate"]:  # the owner's repos: this one and a sibling
    print("false romamo/demo")
    print("false romamo/api")
    sys.exit(0)
os.execv({python!r}, [{python!r}, {standard!r}, *args])
"""


def run_failing_sibling(tmp_path: Path, text: str) -> subprocess.CompletedProcess[str]:
    """setup_state.py on a repo whose owner has one sibling, romamo/api, whose config read
    answers 502"""
    root = setup_repo(tmp_path, text, None)
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    executable(fakes / "gh-standard", FAKE_SETUP_GH.format(python=sys.executable))
    failing = FAILING_GH.format(python=sys.executable, standard=str(fakes / "gh-standard"), error=BAD_GATEWAY)
    executable(fakes / "gh", failing)
    executable(fakes / "uvx", failing)
    home = tmp_path / "home"
    home.mkdir()
    env = {"PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]), "HOME": str(home)}
    command = [sys.executable, str(SCRIPT), REPO, "--repo-dir", str(root), "--json"]
    return subprocess.run(command, capture_output=True, text=True, check=False, env=env)


def test_s082_7_a_sibling_read_failing_other_than_404_is_named_unread_and_setup_goes_on(tmp_path: Path) -> None:
    """#1375: without [agents] the Identity row is informational, so a 502 on one sibling's
    config names that sibling as unread instead of stopping setup with exit 2: every row is
    printed, and the exit code is the rows' (states() refuses a 2)"""
    done = run_failing_sibling(tmp_path, 'mode = "release"\n')
    found = states(done)
    assert list(found)[-1] == "BRANCH_DELETE_ON"  # the run went on past the Identity row
    detail = found["IDENTITY_UNCHOSEN"]
    assert f"romamo/api (unread: {BAD_GATEWAY})" in detail
    assert done.stderr == ""


def test_s082_7_an_unread_sibling_leaves_the_exit_code_to_the_rows(ss: ModuleType, tmp_path: Path) -> None:
    def failing(cmd: list[str]) -> str | None:
        if cmd[-1] == "repos/me/api/contents/.github/shipmill.toml":
            script = f"import sys; sys.stderr.write({BAD_GATEWAY!r}); sys.exit(1)"
            read: str | None = ss.gh_try([sys.executable, "-c", script])  # raises GhFailed
            return read
        return FakeOwner({"me/api": None, "me/web": '[agents]\nprompt = "/t"\napp_id = 9\n'})(cmd)

    ws = ss.watch_module()
    found = ss.identity_row("me/demo", ss.identity_of(config(tmp_path / "demo", AGENTS), ws), tmp_path, ws, failing)
    assert found.state == "IDENTITY_UNCHOSEN"
    assert "the host's Apps: 9 (me/web)" in found.detail and f"me/api (unread: {BAD_GATEWAY})" in found.detail
    done = [ss.Row(state, "") for state in sorted(ss.DONE)]
    assert ss.exit_code([*done, found]) == 1  # an [agents] section: still an action, as before


def test_s043_6_a_sibling_read_failing_with_502_still_exits_2_with_app_id(tmp_path: Path) -> None:
    """#1375: the Identity row's tolerance doesn't reach the Product row, which reads the
    siblings with [agents] app_id and stops on a read that fails with anything but 404"""
    done = run_failing_sibling(tmp_path, WITH_APP)
    assert done.returncode == 2
    assert "repos/romamo/api/contents/.github/shipmill.toml" in done.stderr and BAD_GATEWAY in done.stderr


def test_s082_7_the_docstring_names_the_rows(ss: ModuleType) -> None:
    for state in ("IDENTITY_APP", "IDENTITY_HOST", "IDENTITY_NONE", "IDENTITY_UNCHOSEN"):
        assert state in (ss.__doc__ or "")


# -- S-082-9, S-082-11, S-082-12: the setup question, the skills' rule, and the docs --------

ROOT = Path(__file__).resolve().parents[1]
SIX_SKILLS = (
    "github-issue-triage",
    "github-issue-resolve",
    "github-pr-triage",
    "github-ship-watch",
    "product-intake",
    "shipmill-setup",
)
QUESTION = "Whom do agents write to GitHub as in this repo?"


def folded(*parts: str) -> str:
    """A doc with its line wrapping folded, so a statement reads as one line"""
    return " ".join(ROOT.joinpath(*parts).read_text(encoding="utf-8").split())


def between(text: str, start: str, end: str) -> str:
    assert text.count(start) == 1, start
    return text.split(start, 1)[1].split(end, 1)[0]


def test_s082_9_setup_asks_whom_agents_write_as_only_when_unchosen() -> None:
    text = folded("skills", "shipmill-setup", "SKILL.md")
    assert text.count(QUESTION) == 1
    step = between(text, "**Whom agents write as, asked once per repo (spec 082).**", "By hand instead")
    assert "Ask only when it reads `IDENTITY_UNCHOSEN`" in step
    assert "a repo whose row reads a recorded value is not asked" in step
    assert "Ask in the round of the other questions (D-20)" in step
    assert "and so does step 3's identity question when the checklist reads `IDENTITY_UNCHOSEN`" in text


def test_s082_9_the_options_come_in_order_the_app_the_owners_login_nobody() -> None:
    step = folded("skills", "shipmill-setup", "SKILL.md").split(QUESTION, 1)[1]
    app = step.index("1. **The App (recommended).**")
    host = step.index('2. **The owner\'s login** (`identity = "host"`)')
    none = step.index('3. **Nobody** (`identity = "none"`)')
    assert app < host < none
    offered = step[app:host]
    assert "When the row names an App" in offered and "offer it" in offered
    assert "when it names none, offer to create one with `$CR app-create`" in offered
    assert "these writes can't be told from the owner's own" in step[host:none]


def test_s082_9_app_id_is_written_only_after_the_check_exits_0() -> None:
    step = folded("skills", "shipmill-setup", "SKILL.md").split(QUESTION, 1)[1]
    check_at = step.index("Before you write `app_id`, run `$CR app-install <owner/repo> --app-id <id> --check`")
    assert check_at < step.index("On exit 0 (`App <id> (<slug>[bot]) can read <owner/repo>`), write `app_id = <id>`")
    assert "On any other exit write no `app_id`" in step
    assert "Write the answer to `[agents]` of `.github/shipmill.toml`" in step
    assert "With `host` or `none` chosen, install no gate (D-19)" in step


def write_rule(skill: str) -> str:
    """The skill's "Write as the App" rule, folded: its paragraph or list item"""
    text = folded("skills", skill, "SKILL.md")
    assert text.count("**Write as the App") == 1, skill
    at = text.index("**Write as the App")
    ends = [i for i in (text.find(" **", at + 5), text.find(" ## ", at)) if i != -1]
    return text[at : min(ends)] if ends else text[at:]


@pytest.mark.parametrize("skill", SIX_SKILLS)
def test_s082_11_every_write_runs_as_shipmill_gh_in_every_repo_whatever_the_config_sets(skill: str) -> None:
    rule = write_rule(skill)
    assert "runs as `shipmill gh <the same arguments>`" in rule
    assert "in every repo, whatever `.github/shipmill.toml` sets" in rule
    assert "sets `[agents] app_id`, every `gh` call" not in rule  # no longer only with app_id
    assert "with `[agents] app_id` set, every `gh` call" not in rule
    assert (
        "runs `shipmill app-token --check` before its first write to GitHub, a push included, in every repo, "
        "whatever the config sets"
    ) in rule


@pytest.mark.parametrize("skill", SIX_SKILLS)
def test_s082_11_on_the_owners_choice_the_skill_stops_hands_over_and_never_passes_as_host(skill: str) -> None:
    rule = write_rule(skill)
    owners = between(rule, 'With `[agents] identity = "none"` the repo\'s owner chose', "Without `app_id`")
    for phrase in (
        "from the check or from `shipmill gh`, the skill stops",
        "its report's first line says the owner chose that agents don't write here",
        "shipmill wrote nothing to GitHub",
        "hands over the text of each write it would have made, each with its target",
        "it never offers or passes `--as-host` there",
    ):
        assert phrase in owners, (skill, phrase)


@pytest.mark.parametrize("skill", SIX_SKILLS)
def test_s082_11_no_instruction_files_prose_decides_the_identity(skill: str) -> None:
    rule = write_rule(skill)
    assert "Whom agents write as is the config's choice alone" in rule
    assert "no instruction file's prose" in rule and "decides the identity" in rule


@pytest.mark.parametrize("skill", SIX_SKILLS)
def test_s082_11_no_other_paragraph_runs_shipmill_gh_only_with_app_id(skill: str) -> None:
    # a write named outside the rule mustn't read as plain `gh` without app_id (the rule's "in every repo")
    assert "through `shipmill gh` with `[agents] app_id` set" not in folded("skills", skill, "SKILL.md")


def test_s082_11_the_version_pins_still_match_once_each() -> None:
    config = tomllib.loads((ROOT / ".github" / "shipmill.toml").read_text(encoding="utf-8"))
    lines = [line for line in config["version_lines"] if line["file"].endswith("/SKILL.md")]
    assert {line["file"] for line in lines} == {f"skills/{skill}/SKILL.md" for skill in SIX_SKILLS}
    for line in lines:
        text = (ROOT / line["file"]).read_text(encoding="utf-8")
        assert len(re.findall(line["pattern"], text)) == 1, (line["file"], line["pattern"])


def test_s082_12_install_names_the_three_values_the_question_none_and_all_repositories() -> None:
    section = between(folded("docs", "install.md"), "### Give the sessions their own identity", " ### ")
    for value in ("`app_id = <id>`", '`identity = "host"`', '`identity = "none"`'):
        assert value in section, value
    assert QUESTION in section
    assert '`identity = "none"` refuses every write through `shipmill gh`, and `--as-host` too' in section
    assert "An App installed with access to **All repositories** of an account reaches a new repo there" in section
    assert "with no installation step" in section
    assert "the App can then read and write every repository of the account, private ones included" in section


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


# -- S-082-10: doctor's identity row --------------------------------------------------------


def files(top: Path) -> dict[str, bytes]:
    return {str(p.relative_to(top)): p.read_bytes() for p in sorted(top.rglob("*")) if p.is_file()}


def identity_rows(tmp_path: Path, text: str, api: ReachApi | None = None, key: bool = True) -> list[Check]:
    """doctor's identity rows for a repo whose config adds text to POLICY, the App's key at its
    default path in the home when key; the probe reads through the fake API and signer, and
    doctor writes nothing, the token included"""
    root = config(tmp_path / "repo", POLICY + text)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    home = tmp_path / "home"
    if key:
        found = home / ".config" / "shipmill"
        found.mkdir(parents=True)
        key_file(found).rename(found / f"app-{APP_ID}.pem")
    before = files(tmp_path)
    probe = identity_on_host(None, home, FakeSigner(), api or ReachApi(app=CHECK_APP), CheckClock())
    rows = [c for c in doctor(root, repo=REPO, home=home, identity=probe) if c.name == "identity"]
    assert files(tmp_path) == before
    return rows


def test_s082_10_the_app_reading_the_repo_passes_naming_its_id_bot_and_the_repo(tmp_path: Path) -> None:
    api = ReachApi(app=CHECK_APP)
    rows = identity_rows(tmp_path, WITH_APP, api)
    assert rows == [Check("PASS", "identity", f"the App {APP_ID} (demo-agent[bot]) can read {REPO}")]
    assert (REPO_PATH, SECRET) in api.calls  # the token minted for the repo read it
    assert [e for e in api.events if e.startswith("POST")] == [f"POST {ACCESS}"]  # the mint, and no write


@pytest.mark.parametrize(
    "api",
    [
        ReachApi(app=CHECK_APP, installed=False),
        ReachApi(app=CHECK_APP, repo=Answer(404, '{"message": "Not Found"}')),
    ],
)
def test_s082_10_the_app_that_cant_read_the_repo_fails_naming_the_page_and_app_install(
    tmp_path: Path, api: ReachApi
) -> None:
    [row] = identity_rows(tmp_path, WITH_APP, api)
    assert (row.status, row.name) == ("FAIL", "identity")
    assert row.detail.startswith(f"the App {APP_ID} can't read {REPO}: ")
    assert CHECK_PAGE in row.detail and f"`{cli_command()} app-install {REPO}`" in row.detail


def test_s082_10_the_app_without_its_key_on_the_host_warns(tmp_path: Path) -> None:
    api = ReachApi(app=CHECK_APP)
    rows = identity_rows(tmp_path, WITH_APP, api, key=False)
    assert rows == [Check("WARN", "identity", f"the App {APP_ID}, unchecked: its key isn't on this host")]
    assert api.events == []  # nothing asked of GitHub


def test_s082_10_identity_host_passes(tmp_path: Path) -> None:
    rows = identity_rows(tmp_path, HOST)
    assert rows == [Check("PASS", "identity", "host: writes through shipmill gh go as the host's gh login")]


def test_s082_10_identity_none_passes(tmp_path: Path) -> None:
    rows = identity_rows(tmp_path, NONE)
    assert rows == [Check("PASS", "identity", "none: agents don't write to GitHub here")]


@pytest.mark.parametrize("text", [AGENTS, AGENTS + 'identity = "app"\n'])
def test_s082_10_not_chosen_with_an_agents_section_warns_naming_the_three_choices(tmp_path: Path, text: str) -> None:
    rows = identity_rows(tmp_path, text)
    detail = "; ".join(["not chosen: a write through shipmill gh is refused", *choices(REPO)])
    assert rows == [Check("WARN", "identity", detail)]


def test_s082_10_not_chosen_without_an_agents_section_passes(tmp_path: Path) -> None:
    rows = identity_rows(tmp_path, "")
    assert rows == [Check("PASS", "identity", "; ".join(["not chosen (no [agents] section)", *choices(REPO)]))]
