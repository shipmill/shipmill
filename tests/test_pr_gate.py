"""github-pr-triage's merge gate reads the PR's plan, the direction, and REVIEW.md's
Protected areas from the default branch (spec 024), end to end with a stand-in gh on PATH"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-pr-triage" / "scripts" / "pr_gate.py"
BOT = "shipmill-demo[bot]"

DIRECTION = """\
# demo

## Mission

Ships demos.

## Users

- U-1: A maintainer

## Goals

- G-1: Ship
- G-3: Ship faster

## Non-goals

## Quality bar

- Q-1: Fail fast
"""

REVIEW = """\
# Review

## Passes

Bugs first.

## Protected areas

- `src/land.py`: it pushes tags
"""

PLAN = """\
Fixes #7

## Plan

- Serves: G-3
- Files: src/app.py, tests/test_app.py
- Order:
  1. the failing test
  2. the fix
- Proof: tests/test_app.py

## Tests

pytest
"""

FAKE_GH = """#!{python}
import json, os, sys
fake = json.loads(open(os.environ["FAKE_GH_DATA"]).read())
args = sys.argv[1:]
pr = fake[args[2]]
if args[:2] == ["pr", "view"]:
    print(json.dumps(pr))
elif args[:2] == ["pr", "diff"]:
    print("\\n".join(pr["all_files"]))
else:
    sys.exit("unexpected gh call: " + " ".join(args))
"""


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pr_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


gate = load()


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def checkout(tmp_path: Path, files: dict[str, str]) -> Path:
    """A clone whose origin's default branch holds files; the clone's own tree may differ"""
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    git(origin, "config", "user.email", "t@example.com")
    git(origin, "config", "user.name", "t")
    (origin / "README.md").write_text("demo\n")
    for name, text in files.items():
        (origin / name).parent.mkdir(parents=True, exist_ok=True)
        (origin / name).write_text(text)
    git(origin, "add", "-A")
    git(origin, "commit", "-q", "-m", "base")
    git(tmp_path, "clone", "-q", str(origin), "work")
    return tmp_path / "work"


def pr(
    body: str = PLAN,
    login: str = "app/shipmill-demo",
    files: tuple[str, ...] = ("src/app.py",),
    changed: int | None = None,
) -> dict[str, Any]:
    return {
        "state": "OPEN",
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefOid": "abcdef0123",
        "statusCheckRollup": [{"name": "test", "status": "COMPLETED", "conclusion": "SUCCESS"}],
        "author": {"login": login, "is_bot": login.startswith("app/")},
        "body": body,
        "files": [{"path": f} for f in files[:100]],
        "changedFiles": len(files) if changed is None else changed,
        "all_files": list(files),
    }


def run_gate(
    tmp_path: Path, work: Path, prs: dict[int, dict[str, Any]], *args: str
) -> subprocess.CompletedProcess[str]:
    fakes = tmp_path / "fakes"
    fakes.mkdir(exist_ok=True)
    gh = fakes / "gh"
    gh.write_text(FAKE_GH.format(python=sys.executable), encoding="utf-8")
    gh.chmod(0o700)
    data = tmp_path / "gh.json"
    data.write_text(json.dumps({str(n): p for n, p in prs.items()}), encoding="utf-8")
    env = {**os.environ, "PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]), "FAKE_GH_DATA": str(data)}
    cmd = [sys.executable, str(SCRIPT), *map(str, prs), "--checkout", str(work), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, env=env, cwd=work)


@pytest.fixture
def directed(tmp_path: Path) -> Path:
    return checkout(tmp_path, {"docs/product.md": DIRECTION, "REVIEW.md": REVIEW})


# S-024-7: the plan of an agent's pull request


def test_s024_7_an_agents_pr_with_a_valid_plan_is_ready(tmp_path: Path, directed: Path) -> None:
    proc = run_gate(tmp_path, directed, {7: pr()}, "--bot-login", BOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.startswith("#7 READY state=OPEN")


def test_s024_7_an_agents_pr_without_a_plan_is_refused(tmp_path: Path, directed: Path) -> None:
    proc = run_gate(tmp_path, directed, {7: pr(body="Fixes #7\n\nPlan: tests first\n")}, "--bot-login", BOT)
    assert proc.returncode == gate.REFUSED == 6
    assert proc.stdout.splitlines()[0].startswith("#7 REFUSED state=OPEN")
    assert "  refused: no `## Plan` section" in proc.stdout


def test_s024_7_a_serves_naming_an_unknown_id_is_refused(tmp_path: Path, directed: Path) -> None:
    proc = run_gate(tmp_path, directed, {7: pr(body=PLAN.replace("G-3", "G-2"))}, "--bot-login", BOT)
    assert proc.returncode == 6
    assert "  refused: `Serves:` names G-2, which docs/product.md doesn't list" in proc.stdout


def test_s024_7_a_moved_goals_section_lists_its_ids(tmp_path: Path) -> None:
    moved = DIRECTION.replace("- G-1: Ship\n- G-3: Ship faster\n", "See [Goals](product/goals.md).\n")
    goals = "## Goals\n\n- G-1: Ship\n- G-3: Ship faster\n"
    work = checkout(tmp_path, {"docs/product.md": moved, "docs/product/goals.md": goals})
    assert run_gate(tmp_path, work, {7: pr()}, "--bot-login", BOT).returncode == 0
    refused = run_gate(tmp_path, work, {7: pr(body=PLAN.replace("G-3", "G-4"))}, "--bot-login", BOT)
    assert refused.returncode == 6, refused.stdout


def test_s024_7_a_person_s_pr_is_never_refused_for_its_plan(tmp_path: Path, directed: Path) -> None:
    proc = run_gate(tmp_path, directed, {7: pr(body="Fixes #7", login="amy")}, "--bot-login", BOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert run_gate(tmp_path, directed, {7: pr(body="Fixes #7", login="amy")}).returncode == 0


def test_s024_7_agent_marks_every_named_pr_as_an_agents(tmp_path: Path, directed: Path) -> None:
    proc = run_gate(tmp_path, directed, {7: pr(body="Fixes #7", login="amy")}, "--agent")
    assert proc.returncode == 6


def test_s024_7_without_a_direction_the_plan_is_not_checked(tmp_path: Path) -> None:
    work = checkout(tmp_path, {})
    proc = run_gate(tmp_path, work, {7: pr(body="Fixes #7")}, "--bot-login", BOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (
        proc.stdout
        == "#7 READY state=OPEN mergeable=MERGEABLE base=main head=abcdef0 checks=1 green=1 pending=0 failed=0\n"
    )


def test_s024_7_the_direction_is_read_from_the_default_branch_not_the_checkout(tmp_path: Path, directed: Path) -> None:
    (directed / "docs" / "product.md").write_text(DIRECTION.replace("- G-1: Ship\n", "- G-1: Ship\n- G-2: Local\n"))
    proc = run_gate(tmp_path, directed, {7: pr(body=PLAN.replace("G-3", "G-2"))}, "--bot-login", BOT)
    assert proc.returncode == 6


# S-024-7: Protected areas ask the maintainer


def test_s024_7_a_diff_matching_a_protected_glob_needs_a_decision(tmp_path: Path, directed: Path) -> None:
    proc = run_gate(tmp_path, directed, {7: pr(files=("src/app.py", "src/land.py"))}, "--bot-login", BOT)
    assert proc.returncode == gate.NEEDS_DECISION == 5
    assert proc.stdout.splitlines()[0].startswith("#7 NEEDS_DECISION ")
    assert "  needs-decision: src/land.py matches `src/land.py` (REVIEW.md): it pushes tags" in proc.stdout
    person = run_gate(tmp_path, directed, {7: pr(login="amy", files=("src/land.py",))})
    assert person.returncode == 5  # whoever wrote it


def test_s024_7_the_maintainers_acceptance_lets_the_protected_change_through(tmp_path: Path, directed: Path) -> None:
    proc = run_gate(tmp_path, directed, {7: pr(files=("src/land.py",))}, "--bot-login", BOT, "--maintainer-accepted")
    assert proc.returncode == 0, proc.stdout


def test_s024_7_a_subdirectory_review_md_guards_changes_under_it(tmp_path: Path) -> None:
    sub = "## Protected areas\n\n- `skills/**`: skills ship in the wheel\n"
    work = checkout(tmp_path, {"skills/REVIEW.md": sub})
    proc = run_gate(tmp_path, work, {7: pr(files=("skills/a/SKILL.md",))})
    assert proc.returncode == 5
    assert "`skills/**` (skills/REVIEW.md)" in proc.stdout


def test_s024_7_files_past_the_first_hundred_are_matched_too(tmp_path: Path, directed: Path) -> None:
    files = tuple(f"src/m{i}.py" for i in range(100)) + ("src/land.py",)
    assert run_gate(tmp_path, directed, {7: pr(files=files)}, "--bot-login", BOT).returncode == 5


def test_s024_7_a_malformed_protected_item_stops_the_gate(tmp_path: Path) -> None:
    work = checkout(tmp_path, {"REVIEW.md": "## Protected areas\n\n- src/land.py: no backticks\n"})
    proc = run_gate(tmp_path, work, {7: pr()})
    assert proc.returncode == 2
    assert "REVIEW.md:3: a Protected areas item" in proc.stderr


# proves: S-024-11
def test_s024_7_a_pr_editing_the_direction_needs_the_maintainer(tmp_path: Path, directed: Path) -> None:
    for path in ("docs/product.md", "docs/product/goals.md"):
        proc = run_gate(tmp_path, directed, {7: pr(files=(path,))}, "--bot-login", BOT)
        assert proc.returncode == 5, proc.stdout
        assert f"  needs-decision: {path} edits the product's direction, which only the maintainer changes" in (
            proc.stdout
        )


def test_the_worst_verdict_across_prs_is_the_exit_code(tmp_path: Path, directed: Path) -> None:
    proc = run_gate(tmp_path, directed, {7: pr(), 8: pr(body="none")}, "--bot-login", BOT)
    assert proc.returncode == 6
    assert [line.split()[1] for line in proc.stdout.splitlines() if line.startswith("#")] == ["READY", "REFUSED"]


def test_a_gh_failure_exits_2(tmp_path: Path, directed: Path) -> None:
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    (fakes / "gh").write_text("#!/bin/sh\necho 'no such PR' >&2\nexit 1\n")
    (fakes / "gh").chmod(0o700)
    env = {**os.environ, "PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"])}
    failed = subprocess.run(
        [sys.executable, str(SCRIPT), "9", "--checkout", str(directed)], capture_output=True, text=True, env=env
    )
    assert failed.returncode == 2
    assert "pr_gate: gh for #9 failed: no such PR" in failed.stderr


def test_a_checkout_of_another_repo_is_refused(tmp_path: Path, directed: Path) -> None:
    proc = run_gate(tmp_path, directed, {7: pr()}, "-R", "other/repo")
    assert proc.returncode == 2
    assert "not other/repo" in proc.stderr


# The parts, without gh


@pytest.mark.parametrize(
    ("glob", "path", "hit"),
    [
        ("src/land.py", "src/land.py", True),
        ("src/land.py", "src/land.pyc", False),
        ("skills/**", "skills/a/b.py", True),
        ("docs/product", "docs/product/goals.md", True),
        ("*.lock", "a/uv.lock", True),
        ("src/*.py", "tests/x.py", False),
    ],
)
def test_a_glob_matches_as_decisions_scopes_do(glob: str, path: str, hit: bool) -> None:
    assert gate.matches(glob, path) is hit


@pytest.mark.parametrize(
    ("serves", "problem"),
    [
        ("G-1, G-3", None),
        ("quality bar", None),
        ("", "`Serves:` is empty"),
        ("Q-1", "`Serves:` names 'Q-1'; it names goal ids (G-n) or `quality bar`"),
        ("G-1, G-7", "`Serves:` names G-7, which docs/product.md doesn't list"),
    ],
)
def test_s024_7_serves_names_listed_goals_or_the_quality_bar(serves: str, problem: str | None) -> None:
    body = PLAN.replace("- Serves: G-3", f"- Serves: {serves}")
    found = gate.plan_problems(body, frozenset({"G-1", "G-3", "Q-1"}))
    if problem is None:
        assert found == []
    else:
        assert len(found) == 1 and found[0].startswith(problem), found


def test_s024_7_every_plan_field_is_required() -> None:
    body = PLAN.replace("- Proof: tests/test_app.py\n", "")
    assert gate.plan_problems(body, frozenset({"G-3"})) == ["the plan has no `Proof:` line"]


def test_a_plan_inside_a_code_fence_is_not_a_plan() -> None:
    body = "```\n## Plan\n- Serves: G-3\n```\n"
    assert gate.plan_problems(body, frozenset({"G-3"}))[0].startswith("no `## Plan` section")
