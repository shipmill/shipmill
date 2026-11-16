"""#1215: github-pr-triage's landed.py matches patch ids with whitespace kept (D-92), and on a
git without `git patch-id --verbatim` matches none, in a scratch repository"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "github-pr-triage" / "scripts"
LANDED = SCRIPTS / "landed.py"
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}
# the old-git path: main() with the capability injected as missing, run in the repository
OLD_GIT = (
    "import sys; sys.path.insert(0, sys.argv[1]); import landed; sys.exit(landed.main(sys.argv[2:], verbatim=False))"
)
BASE = "x = 1\n"
INDENTED = BASE + "if x:\n    print(1)\n    print(2)\n"
REINDENTED = BASE + "if x:\n    print(1)\nprint(2)\n"


def git(repo: Path, *args: str, stdin: str | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, env=ENV, capture_output=True, text=True, input=stdin, check=True)
    return proc.stdout


def commit(repo: Path, name: str, text: str, message: str) -> str:
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", "--", name)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """main holds a landed commit adding an indented block; topic re-indents it; copy is a
    byte-identical rebased copy of it"""
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, "a.py", BASE, "base")
    git(tmp_path, "branch", "topic")
    git(tmp_path, "branch", "copy")
    commit(tmp_path, "a.py", INDENTED, "add the block")
    git(tmp_path, "switch", "-q", "topic")
    commit(tmp_path, "a.py", REINDENTED, "add the block")
    git(tmp_path, "switch", "-q", "copy")
    commit(tmp_path, "b.txt", "other\n", "something else first")
    git(tmp_path, "cherry-pick", "main")
    commit(tmp_path, "CHANGELOG.md", "## Unreleased\n", "changelog only")
    git(tmp_path, "switch", "-q", "main")
    return tmp_path


def landed(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LANDED), *args, "--onto", "main"], cwd=repo, env=ENV, capture_output=True, text=True
    )


def landed_on_old_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", OLD_GIT, str(SCRIPTS), *args, "--onto", "main"],
        cwd=repo,
        env=ENV,
        capture_output=True,
        text=True,
    )


def test_a_reindent_only_commit_did_not_land(repo: Path) -> None:
    stable = [git(repo, "patch-id", "--stable", stdin=git(repo, "show", ref)).split()[0] for ref in ("main", "topic")]
    assert stable[0] == stable[1]  # --stable, as before #1215, hashed them the same
    proc = landed(repo, "topic")
    assert proc.returncode == 1, proc.stderr
    assert "NOT LANDED: add the block" in proc.stdout


def test_a_byte_identical_rebased_copy_landed(repo: Path) -> None:
    proc = landed(repo, "copy~1")
    assert proc.returncode == 0, proc.stderr
    assert "landed as" in proc.stdout


def test_on_old_git_no_commit_lands_by_patch_id(repo: Path) -> None:
    proc = landed_on_old_git(repo, "copy~1")
    assert proc.returncode == 1, proc.stderr
    assert "NOT LANDED: add the block" in proc.stdout
    assert "matching by ancestry only" in proc.stderr


def test_on_old_git_ancestry_still_lands(repo: Path) -> None:
    proc = landed_on_old_git(repo, "main~1", "main")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.count("on main itself") == 2


def test_on_old_git_a_changelog_only_commit_is_compared_by_hand(repo: Path) -> None:
    proc = landed_on_old_git(repo, "copy")
    assert proc.returncode == 1, proc.stderr
    assert "changes only CHANGELOG.md; compare by hand" in proc.stdout
