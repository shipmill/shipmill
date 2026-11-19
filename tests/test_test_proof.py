"""Spec 076 (#1283): github-pr-triage's test_proof.py reads a fix's or a refactor's proof from
the pull request's history, in throwaway git repositories"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "github-pr-triage" / "scripts" / "test_proof.py"
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}
# runs each test file named on the command line, or with none every tests/*.py; an assert fails it
RUNNER = (
    "import glob, runpy, sys\n"
    "files = sys.argv[1:] or sorted(glob.glob('tests/*.py'))\n"
    "for i in range(50):\n"
    "    print(f'line-{i:02d}')\n"
    "for path in files:\n"
    "    runpy.run_path(path)\n"
)
COMMAND = [sys.executable, "-u", "-c", RUNNER, "{tests}"]  # unbuffered: a traceback lands last
SOURCE_OLD = "def value():\n    return 1\n"
SOURCE_NEW = "def value():\n    return 2\n"
TEST = "import sys\nsys.path.insert(0, '.')\nimport src\nassert src.value() == 2\n"
OLD_TEST = "import sys\nsys.path.insert(0, '.')\nimport src\nassert src.value() >= 1\n"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_proof", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


proof = load()


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, env=ENV, capture_output=True, text=True, check=True)
    return proc.stdout


def commit(repo: Path, files: dict[str, str | None], message: str) -> str:
    """Write each file (None deletes it) and commit them"""
    for name, text in files.items():
        path = repo / name
        if text is None:
            git(repo, "rm", "-q", "--", name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        git(repo, "add", "--", name)
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """main holds src.py returning 1 and an existing test; the work happens on topic"""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"src.py": SOURCE_OLD, "tests/test_old.py": OLD_TEST}, "base")
    git(repo, "switch", "-q", "-c", "topic")
    return repo


def run(repo: Path, *args: str, command: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    words = [sys.executable, str(SCRIPT), *args, "--base", "main", "--", *(COMMAND if command is None else command)]
    return subprocess.run(words, cwd=repo, env=ENV, capture_output=True, text=True)


def marker_command(marker: Path) -> list[str]:
    """A command that records that it ran"""
    return [sys.executable, "-c", "import sys; open(sys.argv[1], 'w').close()", str(marker)]


def fixed(repo: Path) -> tuple[str, str]:
    """A fix in history order: the failing test alone, then the fix"""
    first = commit(repo, {"tests/test_value.py": TEST}, "test the value")
    head = commit(repo, {"src.py": SOURCE_NEW}, "fix the value")
    return first, head


def worktrees(repo: Path) -> list[str]:
    return [line for line in git(repo, "worktree", "list", "--porcelain").splitlines() if line.startswith("worktree ")]


# S-076-1


def test_s076_1_a_test_first_fix_is_proven(repo: Path) -> None:
    first, _ = fixed(repo)
    proc = run(repo, "fix")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = proc.stdout.splitlines()
    assert lines[0] == "test_proof: PROVEN (fix)"
    assert [line.split(":")[0] for line in lines if line.startswith(("ok:", "fail:"))] == ["ok"] * 4
    assert first[:7] in proc.stdout


# S-076-2


def test_s076_2_a_first_commit_with_the_fix_is_unproven(repo: Path) -> None:
    first = commit(repo, {"tests/test_value.py": TEST, "src.py": SOURCE_NEW}, "test and fix together")
    proc = run(repo, "fix")
    assert proc.returncode == 1
    assert proc.stdout.splitlines()[0] == "test_proof: UNPROVEN (fix)"
    assert f"fail: first-commit-tests-only: {first[:7]} changes files that aren't test files: src.py" in proc.stdout


def test_s076_2_a_test_that_passes_on_the_first_commit_is_unproven(repo: Path) -> None:
    first = commit(repo, {"tests/test_value.py": OLD_TEST}, "a test that already passes")
    commit(repo, {"src.py": SOURCE_NEW}, "the fix")
    proc = run(repo, "fix")
    assert proc.returncode == 1
    assert proc.stdout.splitlines()[0] == "test_proof: UNPROVEN (fix)"
    fail = next(line for line in proc.stdout.splitlines() if line.startswith("fail:"))
    assert fail.startswith(f"fail: fails-before: {first[:7]} (tests/test_value.py)")
    # the unexpectedly passing run's last 40 lines, and no more
    assert "    line-49" in proc.stdout
    assert "    line-10" in proc.stdout
    assert "line-09" not in proc.stdout


def test_s076_2_a_head_that_still_fails_is_unproven(repo: Path) -> None:
    commit(repo, {"tests/test_value.py": TEST}, "test the value")
    head = commit(repo, {"README.md": "no fix\n"}, "not a fix")
    proc = run(repo, "fix")
    assert proc.returncode == 1
    fail = next(line for line in proc.stdout.splitlines() if line.startswith("fail:"))
    assert fail.startswith(f"fail: passes-after: {head[:7]} (tests/test_value.py): the command exits 1")
    assert "AssertionError" in proc.stdout  # the failed run's tail


# S-076-3


@pytest.mark.parametrize(
    ("later", "ok", "says"),
    [
        ({"tests/test_value.py": TEST + "assert src.value() > 0\n"}, True, "only add lines"),
        ({"tests/test_value.py": TEST.replace("== 2", ">= 2")}, False, "removes or changes 1 of tests/test_value.py"),
        ({"tests/test_value.py": None}, False, "deletes tests/test_value.py"),
    ],
)
def test_s076_3_a_later_commit_may_only_add_lines(
    repo: Path, later: dict[str, str | None], ok: bool, says: str
) -> None:
    fixed(repo)
    later_sha = commit(repo, later, "touch the test again")
    proc = run(repo, "fix", "--json")
    record = json.loads(proc.stdout)
    kept = next(check for check in record["checks"] if check["name"] == "tests-kept")
    assert kept["ok"] is ok
    assert says in kept["detail"]
    if not ok:
        assert later_sha[:7] in kept["detail"]


def test_s076_3_a_rename_fails_and_tests_changed_exempts_it(repo: Path, tmp_path: Path) -> None:
    fixed(repo)
    git(repo, "mv", "tests/test_value.py", "tests/test_renamed.py")
    renamed = commit(repo, {}, "rename the test")
    proc = run(repo, "fix")
    assert proc.returncode == 1
    assert f"fail: tests-kept: {renamed[:7]} renames tests/test_value.py to tests/test_renamed.py" in proc.stdout

    plan = tmp_path / "body.md"
    plan.write_text(
        "## Plan\n\n- Serves: G-2\n- Kind: fix\n- Tests changed: `tests/test_value.py`: moved beside its fixture\n",
        encoding="utf-8",
    )
    proc = run(
        repo, "fix", "--plan-file", str(plan), command=[sys.executable, "-u", "-c", RUNNER, "tests/test_renamed.py"]
    )
    lines = proc.stdout.splitlines()
    kept = next(line for line in lines if "tests-kept" in line)
    assert kept.startswith("ok: tests-kept:")
    assert "tests/test_value.py (moved beside its fixture)" in kept


def test_s076_3_a_tests_changed_line_outside_the_plan_exempts_nothing() -> None:
    assert proof.tests_changed("## Summary\n\nTests changed: `tests/a.py`: why\n") == {}
    body = (
        "## Plan\n\n```\nTests changed: `tests/b.py`: fenced\n```\n- Tests changed: `tests/a.py`: why; `t/c.py`: so\n"
    )
    assert proof.tests_changed(body) == {"tests/a.py": "why", "t/c.py": "so"}


# S-076-4


def test_s076_4_a_change_with_no_test_file_reads_no_test(repo: Path, tmp_path: Path) -> None:
    first = commit(repo, {"src.py": SOURCE_NEW}, "fix with no test")
    marker = tmp_path / "ran"
    proc = run(repo, "fix", command=marker_command(marker))
    assert proc.returncode == 0
    assert proc.stdout.splitlines()[0] == "test_proof: NO_TEST (fix)"
    assert not marker.exists()
    record = json.loads(run(repo, "fix", "--json", command=marker_command(marker)).stdout)
    assert record == {"verdict": "NO_TEST", "kind": "fix", "first_commit": first, "test_files": [], "checks": []}
    assert not marker.exists()


# S-076-5


def refactor_command() -> list[str]:
    return list(COMMAND)


def test_s076_5_a_refactor_that_adds_a_test_is_proven(repo: Path) -> None:
    commit(repo, {"src.py": "def value():\n    one = 1\n    return one\n"}, "refactor")
    commit(repo, {"tests/test_more.py": OLD_TEST}, "a new test")
    proc = run(repo, "refactor", command=refactor_command())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[0] == "test_proof: PROVEN (refactor)"
    assert "ok: baseline-green:" in proc.stdout
    assert "ok: tests-unchanged:" in proc.stdout


@pytest.mark.parametrize(
    ("files", "verb"),
    [
        ({"tests/test_old.py": OLD_TEST + "assert True\n"}, "modifies"),
        ({"tests/test_old.py": None}, "deletes"),
    ],
)
def test_s076_5_a_refactor_that_edits_a_test_is_unproven(repo: Path, files: dict[str, str | None], verb: str) -> None:
    edit = commit(repo, files, "refactor and its test")
    proc = run(repo, "refactor", command=refactor_command())
    assert proc.returncode == 1
    assert proc.stdout.splitlines()[0] == "test_proof: UNPROVEN (refactor)"
    assert f"fail: tests-unchanged: {edit[:7]} {verb} tests/test_old.py" in proc.stdout


def test_s076_5_a_rename_is_unproven_unless_tests_changed_names_it(repo: Path, tmp_path: Path) -> None:
    git(repo, "mv", "tests/test_old.py", "tests/test_moved.py")
    moved = commit(repo, {}, "move a test")
    proc = run(repo, "refactor", command=refactor_command())
    assert proc.returncode == 1
    assert f"fail: tests-unchanged: {moved[:7]} renames tests/test_old.py" in proc.stdout

    plan = tmp_path / "body.md"
    plan.write_text("## Plan\n\nTests changed: `tests/test_old.py`: the module moved\n", encoding="utf-8")
    proc = run(repo, "refactor", "--plan-file", str(plan), command=refactor_command())
    assert proc.returncode == 0, proc.stdout
    assert "exempt on Tests changed: tests/test_old.py (the module moved)" in proc.stdout


# S-076-6


def test_s076_6_a_red_base_reads_baseline_red_and_checks_nothing_else(repo: Path) -> None:
    git(repo, "switch", "-q", "main")
    commit(repo, {"tests/test_old.py": TEST}, "a red main")
    git(repo, "switch", "-q", "-c", "red-topic")
    commit(repo, {"tests/test_old.py": None}, "delete a test, which would fail the check")
    proc = run(repo, "refactor", command=refactor_command())
    assert proc.returncode == 1
    lines = proc.stdout.splitlines()
    assert lines[0] == "test_proof: BASELINE_RED (refactor)"
    assert [line for line in lines if line.startswith(("ok:", "fail:"))] == [
        next(line for line in lines if line.startswith("fail: baseline-green:"))
    ]
    assert "AssertionError" in proc.stdout


# S-076-7


@pytest.mark.parametrize(
    "path",
    [
        "tests/helpers.py",
        "pkg/test/data.json",
        "web/__tests__/a.js",
        "spec/a_spec.rb",
        "test_a.py",
        "src/a_test.py",
        "conftest.py",
        "web/a.test.ts",
        "web/a.spec.js",
        "cmd/a_test.go",
        "src/a_test.rs",
    ],
)
def test_s076_7_the_default_test_files(path: str) -> None:
    assert proof.TestFiles([])(path)


@pytest.mark.parametrize("path", ["src/a.py", "testing/a.py", "src/tests.py", "spec.md", "a_tests.py", "atest_a.py"])
def test_s076_7_other_files_are_not_test_files(path: str) -> None:
    assert not proof.TestFiles([])(path)


def test_s076_7_test_path_globs_replace_the_defaults() -> None:
    is_test = proof.TestFiles(["checks/**", "src/*_check.py"])
    assert is_test("checks/a/b.py")
    assert is_test("src/a_check.py")
    assert not is_test("src/a/b_check.py")
    assert not is_test("tests/test_a.py")


# S-076-8


def test_s076_8_the_command_runs_without_a_shell_in_a_temp_worktree(repo: Path, tmp_path: Path) -> None:
    fixed(repo)
    branch, head = git(repo, "branch", "--show-current"), git(repo, "rev-parse", "HEAD")
    before = worktrees(repo)
    log = tmp_path / "log.jsonl"
    record = (
        "import json, os, sys\n"
        "with open(sys.argv[1], 'a') as f: f.write(json.dumps([os.getcwd(), sys.argv[2:]]) + '\\n')\n"
        "sys.exit(0 if os.path.exists('src.py') and 'return 2' in open('src.py').read() else 1)\n"
    )
    proc = run(repo, "fix", command=[sys.executable, "-c", record, str(log), "{tests}", "$HOME;", "`x`"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    runs = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(runs) == 2
    temp = os.path.realpath(tempfile.gettempdir())
    for cwd, argv in runs:
        real = os.path.realpath(cwd)
        assert real.startswith(temp + os.sep)
        assert not real.startswith(os.path.realpath(repo))
        assert argv == ["tests/test_value.py", "$HOME;", "`x`"]  # no shell read them
    assert worktrees(repo) == before
    assert (git(repo, "branch", "--show-current"), git(repo, "rev-parse", "HEAD")) == (branch, head)


def test_s076_8_refactor_drops_tests_and_leaves_no_worktree_on_any_verdict(repo: Path, tmp_path: Path) -> None:
    commit(repo, {"tests/test_old.py": None}, "delete a test")
    log = tmp_path / "log.jsonl"
    record = "import json, sys\nopen(sys.argv[1], 'a').write(json.dumps(sys.argv[2:]) + '\\n')\n"
    before = worktrees(repo)
    proc = run(repo, "refactor", command=[sys.executable, "-c", record, str(log), "{tests}", "-q"])
    assert proc.returncode == 1  # UNPROVEN
    assert json.loads(log.read_text(encoding="utf-8")) == ["-q"]
    assert worktrees(repo) == before
    proc = run(repo, "refactor", command=[sys.executable, "-c", "raise SystemExit(3)"])
    assert proc.returncode == 1  # BASELINE_RED
    assert worktrees(repo) == before
    assert git(repo, "branch", "--show-current") == "topic\n"


# S-076-9


@pytest.mark.parametrize(
    ("args", "says"),
    [
        (["--base", "nope"], "--base nope is not a commit"),
        (["--head", "nope"], "--head nope is not a commit"),
        (["--head", "main"], "no commit between the merge base"),
    ],
)
def test_s076_9_a_bad_ref_or_empty_change_exits_2_running_nothing(
    repo: Path, tmp_path: Path, args: list[str], says: str
) -> None:
    fixed(repo)
    marker = tmp_path / "ran"
    words = [sys.executable, str(SCRIPT), "fix", "--base", "main", *args, "--", *marker_command(marker)]
    proc = subprocess.run(words, cwd=repo, env=ENV, capture_output=True, text=True)
    assert proc.returncode == 2
    assert says in proc.stderr
    assert not marker.exists()


def test_s076_9_no_command_exits_2(repo: Path) -> None:
    fixed(repo)
    for words in (["fix", "--base", "main"], ["fix", "--base", "main", "--"]):
        proc = subprocess.run([sys.executable, str(SCRIPT), *words], cwd=repo, env=ENV, capture_output=True, text=True)
        assert proc.returncode == 2
        assert "no command after --; give the test command" in proc.stderr


def test_s076_9_a_tests_changed_entry_with_no_reason_exits_2(repo: Path, tmp_path: Path) -> None:
    fixed(repo)
    plan = tmp_path / "body.md"
    plan.write_text("## Plan\n\n- Tests changed: `tests/test_value.py`\n", encoding="utf-8")
    marker = tmp_path / "ran"
    proc = run(repo, "fix", "--plan-file", str(plan), command=marker_command(marker))
    assert proc.returncode == 2
    assert "names `tests/test_value.py` with no reason" in proc.stderr
    assert not marker.exists()


def test_s076_9_a_run_past_the_timeout_exits_2_and_leaves_no_worktree(repo: Path) -> None:
    fixed(repo)
    before = worktrees(repo)
    proc = run(repo, "fix", "--timeout", "1", command=[sys.executable, "-c", "import time; time.sleep(30)"])
    assert proc.returncode == 2
    assert "ran past --timeout 1s" in proc.stderr
    assert worktrees(repo) == before


# S-076-10


def test_s076_10_json_prints_one_object(repo: Path) -> None:
    first, _ = fixed(repo)
    proc = run(repo, "fix", "--json")
    record = json.loads(proc.stdout)
    assert {k: record[k] for k in ("verdict", "kind", "first_commit", "test_files")} == {
        "verdict": "PROVEN",
        "kind": "fix",
        "first_commit": first,
        "test_files": ["tests/test_value.py"],
    }
    assert [check["name"] for check in record["checks"]] == [
        "first-commit-tests-only",
        "fails-before",
        "passes-after",
        "tests-kept",
    ]
    for check in record["checks"]:
        assert check["ok"] is True
        assert isinstance(check["detail"], str)

    refactor = json.loads(run(repo, "refactor", "--json", command=refactor_command()).stdout)
    assert refactor["kind"] == "refactor"
    assert refactor["first_commit"] is None
    assert refactor["verdict"] == "PROVEN"
    assert {"name", "ok", "detail"} <= set(refactor["checks"][0])
