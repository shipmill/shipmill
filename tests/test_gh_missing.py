"""#1000: with no gh on PATH, as on a self-hosted runner without GitHub's CLI, shipmill exits 2
with a line naming the fix instead of a FileNotFoundError traceback"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from shipmill.errors import ReleaseError
from shipmill.github import GH_MISSING, GhCli

from .conftest import Repo


def stub_gh(folder: Path) -> Path:
    folder.mkdir(exist_ok=True)
    gh = folder / "gh"
    gh.write_text("#!/bin/sh\necho stub\n", encoding="utf-8")
    gh.chmod(0o755)
    return gh


def test_no_gh_on_the_env_path_is_refused_when_built(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ReleaseError) as caught:
        GhCli(tmp_path, env={"PATH": str(empty)})
    assert str(caught.value) == GH_MISSING
    assert GH_MISSING == "gh not found on PATH; install GitHub's CLI, https://cli.github.com"


def test_an_env_without_path_finds_no_gh(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="gh not found on PATH"):
        GhCli(tmp_path, env={"GH_TOKEN": "t"})


def test_gh_on_the_env_path_is_found(tmp_path: Path) -> None:
    stub_gh(tmp_path / "bin")
    hub = GhCli(tmp_path, env={"PATH": str(tmp_path / "bin")})
    assert hub._gh("version") == "stub\n"


def test_a_missing_explicit_gh_is_refused(tmp_path: Path) -> None:
    missing = tmp_path / "nowhere" / "gh"
    with pytest.raises(ReleaseError, match=f"gh not found at {missing}; install GitHub's CLI"):
        GhCli(tmp_path, gh=str(missing))


def test_an_explicit_gh_needs_no_path(tmp_path: Path) -> None:
    gh = stub_gh(tmp_path / "bin")
    assert GhCli(tmp_path, gh=str(gh), env={"PATH": ""})._gh("version") == "stub\n"


def shipmill(root: Path, tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """`python -m shipmill` in root with a PATH that holds git and no gh"""
    git = shutil.which("git")
    assert git is not None
    bin_dir = tmp_path / "no-gh"
    bin_dir.mkdir(exist_ok=True)
    if not (bin_dir / "git").exists():
        (bin_dir / "git").symlink_to(git)
    env = {"PATH": str(bin_dir), "HOME": os.environ.get("HOME", str(tmp_path))}
    cmd = [sys.executable, "-m", "shipmill", "--repo", str(root), *args]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", check=False)


@pytest.mark.parametrize(
    "args",
    [
        ["plan", "--dry-run"],
        ["prepare", "--lane", "dev", "--version", "1.0.1.dev1", "--base", "main"],
        ["land", "--lane", "dev", "--version", "1.0.1.dev1", "--sha", "0" * 40, "--base", "main"],
        ["operate", "--dry-run"],
    ],
)
def test_a_release_command_without_gh_exits_2_with_the_fix(repo: Repo, tmp_path: Path, args: list[str]) -> None:
    done = shipmill(repo.root, tmp_path, *args)
    assert done.returncode == 2, done.stderr
    assert done.stderr == f"shipmill: {GH_MISSING}\n"


def test_a_command_that_reads_no_github_runs_without_gh(repo: Repo, tmp_path: Path) -> None:
    done = shipmill(repo.root, tmp_path, "settle-minutes")
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().isdigit()
