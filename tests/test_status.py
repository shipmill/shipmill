"""Spec 008: `shipmill status`, github-ship-watch's report from the CLI"""

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

import shipmill.cli
from shipmill.app import INSTEAD_OF, SSH_REMOTES
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.gate import StateRead, WatchState, skills_dir, watch_command
from shipmill.walk import Changes

NOW = dt.datetime(2026, 10, 27, 12, 0, tzinfo=dt.UTC)
CHANGES = Changes("x", known={"default_branch": "main", "held": False, "prs": [], "incidents": [], "runs": []})

REPO = "acme/web"
SCRIPT = skills_dir() / "github-ship-watch" / "scripts" / "watch_state.py"
TABLE = "BOT_FAILED     acme/web  release.yml failed\nPUBLISHED      v1.2.0    on PyPI\n"
ROW = '{"agent": true, "detail": "release.yml failed", "state": "BOT_FAILED", "subject": "acme/web"}\n'


class Script:
    """watch_state.py as the fake answers it; seen holds each command it was given"""

    def __init__(self, code: int = 0, stdout: str = TABLE, stderr: str = "") -> None:
        self.code, self.stdout, self.stderr = code, stdout, stderr
        self.seen: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        self.seen.append(cmd)
        return subprocess.CompletedProcess(cmd, self.code, self.stdout, self.stderr)


def plain_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """git without the host's config: no GIT_CONFIG_* pairs, no global or system file"""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "0")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture(autouse=True)
def _plain_git(monkeypatch: pytest.MonkeyPatch) -> None:
    # #833: the gate runs its agents with SSH remotes rewritten to https (app.session_env), and
    # `git remote get-url` prints the rewrite, so the origins these tests assert on would follow
    # the host's config
    plain_git(monkeypatch)


def checkout(root: Path, origin: str = f"git@github.com:{REPO}.git") -> Path:
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", origin], check=True)
    return root.resolve()


HOST = "octocat"  # the host's gh login, the maintainer of a config without [agents.roles] (spec 036)
ROLES = ["--role", f"maintainer={HOST}"]


def status(root: Path, script: Script, *extra: str) -> int:
    """Spec 008's report: --rows for its table (spec 009's picture is the default now)"""
    shown = extra if "--json" in extra else ("--rows", *extra)
    return main(["--repo", str(root), "status", *shown], state=script, login=lambda: HOST)


def test_s008_1_the_default_repo_is_origins_with_the_checkouts_top_level(tmp_path: Path) -> None:
    root = checkout(tmp_path / "repo")
    (root / "src").mkdir()
    script = Script()
    assert status(root / "src", script) == 0
    assert script.seen == [[sys.executable, str(SCRIPT), REPO, "--repo-dir", str(root), *ROLES]]


def test_s008_2_an_origin_off_github_asks_for_the_repo(tmp_path: Path) -> None:
    root = checkout(tmp_path / "repo", "https://gitlab.com/acme/web.git")
    script = Script()
    with pytest.raises(ReleaseError, match=r"origin isn't a GitHub repo; name the repo"):
        status(root, script)
    assert script.seen == []


def test_s008_3_a_named_repo_must_be_the_checkouts_origin(tmp_path: Path) -> None:
    root = checkout(tmp_path / "repo")
    script = Script()
    with pytest.raises(ReleaseError, match=r"origin is git@github\.com:acme/web\.git, not acme/api"):
        status(root, script, "acme/api")
    assert script.seen == []
    assert status(root, script, REPO) == 0
    assert script.seen[0][2] == REPO


def gate_rewrite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The env the gate launches an agent with: SSH remotes go over https"""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", INSTEAD_OF)
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", SSH_REMOTES[0])


def global_rewrite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A host whose ~/.gitconfig rewrites SSH remotes to https"""
    config = tmp_path / "gitconfig"
    config.write_text(f'[url "https://github.com/"]\n\tinsteadOf = {SSH_REMOTES[0]}\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))


@pytest.mark.parametrize("host", [gate_rewrite, global_rewrite])
def test_s008_3_holds_under_the_hosts_url_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: Callable[[pytest.MonkeyPatch, Path], None]
) -> None:
    # #833: the host's rewrite really reaches git, and plain_git keeps it from the checkouts
    root = checkout(tmp_path / "repo")
    host(monkeypatch, tmp_path)
    get_url = ["git", "-C", str(root), "remote", "get-url", "origin"]
    rewritten = subprocess.run(get_url, check=True, capture_output=True, text=True).stdout
    assert rewritten == f"https://github.com/{REPO}.git\n"
    plain_git(monkeypatch)
    (tmp_path / "plain").mkdir()
    test_s008_3_a_named_repo_must_be_the_checkouts_origin(tmp_path / "plain")


def test_s008_4_the_table_and_the_json_lines_are_printed_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path / "repo")
    assert status(root, Script()) == 0
    assert capsys.readouterr().out == TABLE
    script = Script(stdout=ROW)
    assert status(root, script, "--json") == 0
    out = capsys.readouterr().out
    assert out.startswith(ROW)  # spec 040 adds one line after them, the AUTONOMY one (S-040-10)
    assert json.loads(out.removeprefix(ROW))["state"] == "AUTONOMY"
    assert script.seen[0][-3:] == ["--json", *ROLES]


def test_s008_5_the_scripts_answer_is_the_exit_code(tmp_path: Path) -> None:
    root = checkout(tmp_path / "repo")
    assert status(root, Script(code=1)) == 1
    assert status(root, Script(code=0)) == 0


def test_a_gate_without_an_app_makes_status_exit_1(tmp_path: Path) -> None:
    # #204, D-19: watch_state.py exits 1 on any ACTION row, GATE_NO_APP among them, and status passes it on
    spec = importlib.util.spec_from_file_location("watch_state_status", SCRIPT)
    assert spec is not None and spec.loader is not None
    ws = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ws  # dataclasses look their module up by name
    spec.loader.exec_module(ws)
    assert "GATE_NO_APP" in ws.ACTION
    (row,) = ws.gate_app_rows({"prompt": '"/github-issue-triage {repo}"'})
    root = checkout(tmp_path / "repo")
    assert status(root, Script(code=1, stdout=row.text() + "\n")) == 1


@pytest.mark.parametrize(("code", "stdout"), [(2, ""), (2, TABLE), (3, ""), (1, ""), (1, "\n")])
def test_s008_6_a_failed_script_exits_2_with_its_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], code: int, stdout: str
) -> None:
    root = checkout(tmp_path / "repo")
    assert status(root, Script(code=code, stdout=stdout, stderr="error: gh repo view...: auth\n")) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err == f"error: gh repo view...: auth\nshipmill: watch_state.py failed (exit {code})\n"


def test_s008_7_the_gate_and_status_share_watch_command(tmp_path: Path) -> None:
    root = checkout(tmp_path / "repo")
    base = [sys.executable, str(SCRIPT), REPO, "--repo-dir", str(root)]
    assert watch_command(REPO, root, StateRead()) == [*base, "--json"]
    assert watch_command(REPO, root, StateRead(), json=False) == base
    assert watch_command(REPO, root, StateRead(True, "x[bot]"), json=False) == [
        *base,
        "--trusted-only",
        "--bot-login",
        "x[bot]",
    ]
    script = Script(stdout=ROW)
    WatchState(REPO, root, StateRead(), tmp_path / "state", NOW, run=script).sweep(Changes("x"))
    assert script.seen == [[*base, "--json", "--sweep"]]  # spec 046: the gate's reads are a tier or the sweep


def test_s008_8_the_docstring_names_status_and_its_exit_1() -> None:
    doc = shipmill.cli.__doc__ or ""
    assert "\n  status " in doc
    assert "status found a row that needs\naction" in doc


@pytest.mark.parametrize("extra", [(), (REPO,)])
def test_s008_9_outside_a_checkout_status_says_to_run_it_in_one(tmp_path: Path, extra: tuple[str, ...]) -> None:
    script = Script()
    with pytest.raises(
        ReleaseError, match=r"is not a git checkout; run status in a checkout of the repo, or pass --repo PATH"
    ):
        status(tmp_path, script, *extra)
    assert script.seen == []


def test_s008_10_stderr_passes_through_on_0_and_1_and_whole_on_a_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path / "repo")
    for code in (0, 1):
        assert status(root, Script(code=code, stderr="warning: slow PyPI\n")) == code
        assert capsys.readouterr() == (TABLE, "warning: slow PyPI\n")
    trace = (
        "Traceback (most recent call last):\n"
        + "  frame\n" * 200
        + "urllib.error.URLError: <urlopen error timed out>\n"
    )
    assert status(root, Script(code=1, stdout="", stderr=trace)) == 2
    assert capsys.readouterr().err.startswith(trace)


def test_s008_11_the_gate_fails_on_a_crashed_script_with_the_end_of_stderr(tmp_path: Path) -> None:
    root = checkout(tmp_path / "repo")
    trace = (
        "Traceback (most recent call last):\n" + "  frame\n" * 200 + "urllib.error.URLError: <urlopen error timed out>"
    )

    def read(script: Script) -> list[str]:
        return [
            f.state for f in WatchState(REPO, root, StateRead(), tmp_path / "state", NOW, run=script).tier(2, CHANGES)
        ]

    with pytest.raises(
        ReleaseError, match=r"(?s)watch_state\.py --tier 2 failed \(exit 1\): .*URLError: <urlopen error timed out>$"
    ):
        read(Script(code=1, stdout="", stderr=trace))
    with pytest.raises(ReleaseError, match=r"failed \(exit 2\)"):
        read(Script(code=2, stdout="", stderr="error"))
    assert read(Script(code=1, stdout=ROW)) == ["BOT_FAILED"]


def test_s008_12_the_docs_name_shipmill_status() -> None:
    root = Path(__file__).resolve().parents[1]
    for doc in ("README.md", "skills/github-ship-watch/SKILL.md"):
        assert "shipmill status" in (root / doc).read_text(encoding="utf-8"), doc
