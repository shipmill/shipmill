"""Spec 038, S-038-4: a repo in no product, whose config has no [product] table, gets the same
tokens, states, and rows as before the spec. The expected values below are what the code
before spec 038 (02008b1) gave for the same inputs, written out rather than "no error"; no
test reaches the network"""

import datetime as dt
import importlib.util
import io
import json
import shlex
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from shipmill.app import CACHE, Token, app_check, save_token, write_helpers
from shipmill.cli import main
from shipmill.gate import state_dir
from shipmill.gitrepo import Git

from .test_agent_marker import sent
from .test_app import APP_ID, BOT_PATH, REPO, FakeApi, FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, Runner, checkout, gh
from .test_app_token import FAKE_GH, FAKE_PYTHON, GET, MintApi, executable
from .test_triage_state import comment, open_issue
from .test_triage_upstream import run_triage

ROOT = Path(__file__).resolve().parents[1]
WATCH = ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
TRIAGE = ROOT / "skills" / "github-issue-triage" / "scripts" / "triage_state.py"
BOT = "demo-agent[bot]"
ELSEWHERE = "https://github.com/romamo/elsewhere.git"
# A session's token before spec 038: one repo, these permissions
SESSION = {
    "contents": "write",
    "pull_requests": "write",
    "issues": "write",
    "actions": "write",
    "workflows": "write",
    "checks": "read",
    "statuses": "read",
    "discussions": "read",
    "metadata": "read",
}
# Configs in no product: the App alone, and the App with every table a gate repo may have
NO_PRODUCT = [WITH_APP, WITH_APP + '\n[hooks]\ndefault_branch = true\n\n[changelog]\nfragments = "changelog.d"\n']
# Spec 043: a repo that stands alone, [product] standalone = true, reads as one with no table,
# so each S-038-4 test below runs on these configs too and pins the same tokens, states, and rows
# proves: S-043-2
STANDALONE = [config + "\n[product]\nstandalone = true\n" for config in NO_PRODUCT]
NO_PRODUCT += STANDALONE


@pytest.fixture
def host(tmp_path: Path) -> Host:
    fakes, record, home = tmp_path / "fakes", tmp_path / "record", tmp_path / "home"
    for folder in (fakes, record, home):
        folder.mkdir()
    executable(fakes / "gh", FAKE_GH)
    return Host(fakes, record, home)


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    spec = importlib.util.spec_from_file_location("watch_state_no_product", WATCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def token(root: Path, tmp_path: Path, repo: str, api: MintApi, host: Host, *extra: str) -> int:
    argv = ["--repo", str(root), "app-token", repo, "--app-id", str(APP_ID), "--app-key", str(key_file(tmp_path))]
    return main([*argv, *extra], api=api, signer=FakeSigner(), environ={}, home=host.home, stdin=io.StringIO(GET))


@pytest.mark.parametrize("config", NO_PRODUCT)
@pytest.mark.parametrize("origin", [f"https://github.com/{REPO}.git", ELSEWHERE])
def test_s038_4_app_token_mints_the_one_repo_session_token_as_before(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str], config: str, origin: str
) -> None:
    # whatever the checkout's origin: before spec 038 app-token never compared the two
    root = checkout(tmp_path, config, origin=origin)
    api = MintApi()
    assert token(root, tmp_path, REPO, api, host) == 0
    assert capsys.readouterr() == ("token-1\n", "")
    assert [(path, body) for path, _, body in api.posts] == [
        ("/app/installations/77/access_tokens", {"repositories": ["demo"], "permissions": SESSION})
    ]
    state = state_dir(Git(root))
    assert sorted(p.name for p in state.iterdir()) == [CACHE]  # no product cache beside it
    cached = json.loads((state / CACHE).read_text(encoding="utf-8"))
    assert (cached["repository"], cached["app_id"], cached["token"]) == (REPO, APP_ID, "token-1")
    # git's credential helper answers with the same token, reused
    assert token(root, tmp_path, REPO, MintApi(), host, "--git-credential", "get") == 0
    assert capsys.readouterr().out == "username=x-access-token\npassword=token-1\n"


@pytest.mark.parametrize("config", NO_PRODUCT)
@pytest.mark.parametrize(
    ("origin", "args"),
    [
        (f"https://github.com/{REPO}.git", ["issue", "comment", "250", "--body", "c"]),
        (f"https://github.com/{REPO}.git", ["issue", "list", "-R", REPO]),
        (ELSEWHERE, ["issue", "comment", "3", "-R", REPO, "--body", "c"]),  # a repo not its origin
        # --product's refusals aren't read; a merge is classified first (S-030-13, tests/test_app_gh_merge.py)
        (f"https://github.com/{REPO}.git", ["pr", "edit", "1", "--title", "x"]),
        (f"https://github.com/{REPO}.git", ["workflow", "run", "ci.yml"]),
    ],
)
def test_s038_4_shipmill_gh_runs_gh_with_the_session_token_as_before(
    tmp_path: Path, host: Host, config: str, origin: str, args: list[str]
) -> None:
    root = checkout(tmp_path, config, origin=origin)
    key_file(tmp_path)
    api, runner = MintApi(), Runner()
    assert gh(root, ["--app-key", str(tmp_path / "app.pem"), *args], host, api, runner) == 7
    [(argv, env)] = runner.calls
    assert argv == [host.gh, *(sent(args) if "--body" in args else args)]  # spec 050 marks a body
    assert env["GH_TOKEN"] == "token-1" and "GH_REPO" not in env
    assert [body for _, _, body in api.posts] == [{"repositories": ["demo"], "permissions": SESSION}]
    assert sorted(p.name for p in state_dir(Git(root)).iterdir()) == [CACHE]


@pytest.mark.parametrize("config", NO_PRODUCT)
def test_s038_4_the_gates_helpers_and_app_check_are_as_before(tmp_path: Path, config: str) -> None:
    root = checkout(tmp_path, config)
    git = Git(root)
    # the gate checks its own repo only: the App, the installation, the bot account
    api = FakeApi()
    app_check(REPO, key_file(tmp_path), tmp_path, FakeSigner(), api)(APP_ID)
    assert [path for path, _ in api.calls] == ["/app", f"/repos/{REPO}/installation", BOT_PATH]
    # the helpers' files, byte for byte as spec 004 wrote them
    fakes, record = tmp_path / "fakes", tmp_path / "record"
    fakes.mkdir()
    record.mkdir()
    executable(fakes / "gh", FAKE_GH)
    executable(fakes / "python", FAKE_PYTHON)
    folder = state_dir(git) / "bin"
    path = f"{folder}:{fakes}:/usr/bin:/bin"
    key = tmp_path / "absent.pem"
    helpers = write_helpers(folder, Path(sys.executable), root, REPO, APP_ID, key, path)
    command = shlex.join(
        [sys.executable, "-m", "shipmill", "--repo", str(root.resolve()), "app-token", REPO]
        + ["--app-id", str(APP_ID), "--app-key", str(key.resolve())]
    )
    header = "#!/bin/sh\n# Written by shipmill gate (spec 004). It holds no token: each call mints or reuses one.\n"
    real_gh = shlex.quote(str((fakes / "gh").resolve()))
    assert helpers.gh.read_text(encoding="utf-8") == (
        f'{header}token=$({command}) || exit $?\nGH_TOKEN=$token\nexport GH_TOKEN\nunset token\nexec {real_gh} "$@"\n'
    )
    assert helpers.git_credential.read_text(encoding="utf-8") == f'{header}exec {command} --git-credential "$1"\n'
    # run end to end through this shipmill, from a cached session token
    save_token(
        state_dir(git) / CACHE, Token("cached-secret", dt.datetime.now(dt.UTC) + dt.timedelta(hours=1), REPO, APP_ID)
    )
    env = {"PATH": path, "RECORD": str(record)}
    done = subprocess.run(
        [str(helpers.git_credential), "get"], input=GET, capture_output=True, text=True, check=False, env=env
    )
    assert (done.returncode, done.stdout, done.stderr) == (0, "username=x-access-token\npassword=cached-secret\n", "")
    done = subprocess.run([str(helpers.gh), "api", "user"], capture_output=True, text=True, check=False, env=env)
    assert (done.returncode, done.stdout, done.stderr) == (7, "", "")
    assert (record / "gh-token").read_text() == "cached-secret"


def issues() -> list[dict[str, object]]:
    """One issue for each state a repo's triage reads most: NEW, NEEDS_PR, TRIAGED, BLOCKED,
    POSTPONED, and NEEDS_DECISION"""
    question = {
        **comment("<!-- shipmill:needs-decision -->\n@amy which way?"),
        "author": {"__typename": "Bot", "login": "demo-agent"},
        "authorAssociation": "NONE",
    }
    return [
        open_issue(1),
        open_issue(2, [comment("Triage: **implement**. I'll link the PR here.")]),
        open_issue(3, [comment("Triage: **needs a decision**. Which default?")]),
        open_issue(4, [comment("Triage: **implement**.")], labels=("blocked",)),
        open_issue(5, [comment("Triage: **postponed to 1.1**.")], labels=("postponed",)),
        open_issue(6, [comment("Triage: **implement**."), question], labels=("needs-decision",)),
    ]


EXPECTED = [
    {"number": 1, "state": "NEW", "title": "issue 1", "note": ""},
    {"number": 2, "state": "NEEDS_PR", "title": "issue 2", "note": ""},
    {"number": 3, "state": "TRIAGED", "title": "issue 3", "note": ""},
    {"number": 4, "state": "BLOCKED", "title": "issue 4", "note": "labelled blocked"},
    {"number": 5, "state": "POSTPONED", "title": "issue 5", "note": ""},
    {"number": 6, "state": "NEEDS_DECISION", "title": "issue 6", "note": "waits on a reply"},
]


def test_s038_4_triage_state_reads_the_same_states_without_home(tmp_path: Path) -> None:
    proc = run_triage(tmp_path, issues(), "--bot-login", BOT)
    assert proc.returncode == 1, proc.stderr
    rows = sorted((json.loads(line) for line in proc.stdout.splitlines()), key=lambda r: r["number"])
    assert [{k: r[k] for k in ("number", "state", "title", "note")} for r in rows] == EXPECTED


@pytest.mark.parametrize("config", NO_PRODUCT)
def test_s038_4_watch_state_runs_triage_as_before_and_adds_no_product_row(
    ws: ModuleType, tmp_path: Path, config: str
) -> None:
    policy = tmp_path / "shipmill.toml"
    assert ws.product_home(config, policy) is None and ws.product_repos(config, policy) is None
    assert ws.triage_command("o/r", BOT, True, ws.product_home(config, policy)) == [
        sys.executable,
        str(TRIAGE),
        "o/r",
        "--json",
        "--bot-login",
        BOT,
        "--trusted-only",
    ]
    ran: list[list[str]] = []

    def execute(cmd: list[str], cwd: Path | None, env: dict[str, str] | None) -> subprocess.CompletedProcess[str]:
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "")

    assert ws.coordinator_rows(config, policy, "o/r", tmp_path, BOT, execute) == []
    assert ran == []  # no upstream_state.py
    lines = "\n".join(json.dumps(row) for row in EXPECTED)
    rows = ws.intake("o/r", 1, lines, [], lambda n: [], BOT, True)
    assert [(r.state, r.detail, r.json()["agent"]) for r in rows] == [
        ("ISSUES", "NEEDS_PR #2; NEW #1", True),
        ("ISSUES_OPEN", "BLOCKED #4; POSTPONED #5; TRIAGED #3", False),
        ("NEEDS_DECISION", "#6", False),
    ]
