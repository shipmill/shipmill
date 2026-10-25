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
    tmp_path: Path, work: Path | None, prs: dict[int, dict[str, Any]], *args: str
) -> subprocess.CompletedProcess[str]:
    """The gate with --checkout work, or, for None, run in a folder outside any checkout"""
    fakes = tmp_path / "fakes"
    fakes.mkdir(exist_ok=True)
    gh = fakes / "gh"
    gh.write_text(FAKE_GH.format(python=sys.executable), encoding="utf-8")
    gh.chmod(0o700)
    data = tmp_path / "gh.json"
    data.write_text(json.dumps({str(n): p for n, p in prs.items()}), encoding="utf-8")
    env = {
        **os.environ,
        "PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]),
        "FAKE_GH_DATA": str(data),
        "GIT_CEILING_DIRECTORIES": str(tmp_path),  # so no checkout above tmp_path counts
    }
    where = ["--checkout", str(work)] if work is not None else []
    cwd = work if work is not None else tmp_path / "outside"
    cwd.mkdir(exist_ok=True)
    cmd = [sys.executable, str(SCRIPT), *map(str, prs), *where, *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, env=env, cwd=cwd)


MAIN_READY = "#7 READY state=OPEN mergeable=MERGEABLE base=main head=abcdef0 checks=1 green=1 pending=0 failed=0\n"


@pytest.fixture
def directed(tmp_path: Path) -> Path:
    return checkout(tmp_path, {"docs/product.md": DIRECTION, "REVIEW.md": REVIEW})


# S-024-7: the plan of an agent's pull request


def test_s024_7_an_agents_pr_with_a_valid_plan_is_ready(tmp_path: Path, directed: Path) -> None:
    proc = run_gate(tmp_path, directed, {7: pr()}, "--bot-login", BOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.startswith("#7 READY state=OPEN")


def test_s024_7_a_fix_serving_the_quality_bar_is_ready(tmp_path: Path, directed: Path) -> None:
    """github-issue-resolve's template writes `- Serves: quality bar` for a fix, without backticks"""
    proc = run_gate(tmp_path, directed, {7: pr(body=PLAN.replace("G-3", "quality bar"))}, "--bot-login", BOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr


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


MEASURED = DIRECTION.replace(
    "- G-1: Ship\n- G-3: Ship faster\n",
    "- G-1: Ship\n  measure: deploy_frequency >= 5/week\n- G-3: Ship faster\n  measure: lead_time_median < 2.5d\n",
)


def ids_of(files: dict[str, str]) -> frozenset[str]:
    ids: frozenset[str] = gate.direction_ids(files.get)
    return ids


def test_s027_6_the_gate_reads_the_goal_ids_of_a_direction_whose_goals_carry_measures(tmp_path: Path) -> None:
    expected = {"U-1", "G-1", "G-3", "Q-1"}
    assert ids_of({"docs/product.md": MEASURED}) == expected
    moved = DIRECTION.replace("- G-1: Ship\n- G-3: Ship faster\n", "See [Goals](product/goals.md).\n")
    goals = "## Goals\n\n- G-1: Ship\n  measure: human_touch <= 20%\n- G-3: Ship faster\n"
    assert ids_of({"docs/product.md": moved, "docs/product/goals.md": goals}) == expected
    work = checkout(tmp_path, {"docs/product.md": MEASURED})
    proc = run_gate(tmp_path, work, {7: pr()}, "--bot-login", BOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize(
    ("text", "line"),
    [
        pytest.param(
            MEASURED.replace("- U-1: A maintainer\n", "- U-1: A maintainer\n  measure: human_touch < 5%\n"),
            10,
            id="under a user",
        ),
        pytest.param(
            MEASURED.replace("- Q-1: Fail fast\n", "- Q-1: Fail fast\n  measure: human_touch < 5%\n"),
            23,
            id="under the quality bar",
        ),
        pytest.param(MEASURED.replace("- G-1: Ship\n", "- G-1: Ship\n\n"), 15, id="after a blank line"),
        pytest.param(
            MEASURED.replace("  measure: deploy_frequency >= 5/week\n", "  measure: a\n  measure: b\n"),
            15,
            id="a second measure",
        ),
        pytest.param(
            MEASURED.replace("- G-3: Ship faster\n", "- G-3: Ship faster\n  wrapped text\n"),
            16,
            id="another indented line",
        ),
        pytest.param(MEASURED.replace("  measure: deploy", "   measure: deploy"), 14, id="indented by three"),
    ],
)
def test_s027_6_the_gate_still_stops_on_any_other_non_item_line(text: str, line: int) -> None:
    with pytest.raises(gate.GateError, match=rf"^docs/product.md:{line}: not a `- [UGQ]-<n>: <text>` item"):
        ids_of({"docs/product.md": text})


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
    assert proc.stdout == MAIN_READY


def test_a_base_with_neither_file_gates_as_before_spec_024(tmp_path: Path) -> None:
    """No direction and no REVIEW.md: a PR editing docs/product.md isn't asked about either"""
    work = checkout(tmp_path, {})
    proc = run_gate(tmp_path, work, {7: pr(body="Fixes #7", files=("docs/product.md",))}, "--agent")
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, MAIN_READY, "")


def test_outside_a_checkout_the_gate_is_as_before_spec_024(tmp_path: Path) -> None:
    proc = run_gate(tmp_path, None, {7: pr(body="Fixes #7", files=("src/land.py",))}, "--agent")
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, MAIN_READY, "")


# S-032-14: a downstream check is read like any check


def downstream(status: str, conclusion: str | None, name: str = "downstream: acme/app") -> dict[str, Any]:
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion}


def with_checks(*extra: dict[str, Any]) -> dict[str, Any]:
    data = pr(body="Fixes #7", login="amy")
    data["statusCheckRollup"] = [*data["statusCheckRollup"], *extra]
    return data


@pytest.mark.parametrize("conclusion", ["FAILURE", "TIMED_OUT", "ACTION_REQUIRED"])
def test_s032_14_a_failing_downstream_check_fails_the_gate(tmp_path: Path, conclusion: str) -> None:
    proc = run_gate(tmp_path, None, {7: with_checks(downstream("COMPLETED", conclusion))})
    assert proc.returncode == gate.FAILED == 1, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[0].startswith("#7 FAILED ")
    assert proc.stdout.splitlines()[0].endswith(" checks=2 green=1 pending=0 failed=1")
    assert f"  failed: downstream: acme/app ({conclusion})" in proc.stdout.splitlines()


def test_s032_14_a_running_downstream_check_keeps_the_gate_pending(tmp_path: Path) -> None:
    proc = run_gate(tmp_path, None, {7: with_checks(downstream("IN_PROGRESS", None))})
    assert proc.returncode == gate.PENDING == 3, proc.stdout + proc.stderr
    assert proc.stdout.splitlines() == [
        "#7 PENDING state=OPEN mergeable=MERGEABLE base=main head=abcdef0 checks=2 green=1 pending=1 failed=0",
        "  pending: downstream: acme/app",
    ]


def test_s032_14_neutral_and_success_downstream_checks_are_green(tmp_path: Path) -> None:
    checks = (downstream("COMPLETED", "NEUTRAL"), downstream("COMPLETED", "SUCCESS", "downstream: acme/cli"))
    proc = run_gate(tmp_path, None, {7: with_checks(*checks)})
    assert (proc.returncode, proc.stderr) == (0, "")
    assert proc.stdout == MAIN_READY.replace("checks=1 green=1", "checks=3 green=3")


def test_without_origin_head_the_prs_base_branch_is_read(tmp_path: Path, directed: Path) -> None:
    git(directed, "remote", "set-head", "origin", "--delete")
    proc = run_gate(tmp_path, directed, {7: pr(body="Fixes #7")}, "--bot-login", BOT)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "  refused: no `## Plan` section" in proc.stdout


def test_without_origin_head_or_the_base_branch_the_gate_stops(tmp_path: Path, directed: Path) -> None:
    git(directed, "remote", "set-head", "origin", "--delete")
    proc = run_gate(tmp_path, directed, {7: {**pr(), "baseRefName": "release"}}, "--bot-login", BOT)
    assert proc.returncode == 2
    assert "neither origin/HEAD nor origin/release is in" in proc.stderr


def test_a_named_checkout_that_is_not_one_stops_the_gate(tmp_path: Path) -> None:
    folder = tmp_path / "plain"
    folder.mkdir()
    proc = run_gate(tmp_path, folder, {7: pr()})
    assert proc.returncode == 2
    assert "is not a git checkout" in proc.stderr


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


def test_547_a_spec_pr_is_landable_like_any_other_once_green(tmp_path: Path, directed: Path) -> None:
    # D-49: a spec PR approved by an answer lands on the gate's READY; the gate holds no spec
    spec = ("docs/specs/030-decision-policy.md", "docs/decisions.md")
    proc = run_gate(tmp_path, directed, {7: pr(files=spec)}, "--bot-login", BOT)
    assert proc.returncode == 0, proc.stdout
    assert proc.stdout.splitlines()[0].startswith("#7 READY ")


def test_547_a_spec_pr_editing_the_direction_still_waits_on_the_maintainer(tmp_path: Path, directed: Path) -> None:
    # D-34: the spec's answer is no --maintainer-accepted, so the direction's edit holds it
    files = ("docs/specs/030-decision-policy.md", "docs/product.md")
    proc = run_gate(tmp_path, directed, {7: pr(files=files)}, "--bot-login", BOT)
    assert proc.returncode == 5, proc.stdout
    assert "  needs-decision: docs/product.md edits the product's direction" in proc.stdout


def test_the_worst_verdict_across_prs_is_the_exit_code(tmp_path: Path, directed: Path) -> None:
    proc = run_gate(tmp_path, directed, {7: pr(), 8: pr(body="none")}, "--bot-login", BOT)
    assert proc.returncode == 6
    assert [line.split()[1] for line in proc.stdout.splitlines() if line.startswith("#")] == ["READY", "REFUSED"]


def test_a_gh_failure_exits_1_as_before(tmp_path: Path, directed: Path) -> None:
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    (fakes / "gh").write_text("#!/bin/sh\necho 'no such PR' >&2\nexit 1\n")
    (fakes / "gh").chmod(0o700)
    env = {**os.environ, "PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"])}
    failed = subprocess.run(
        [sys.executable, str(SCRIPT), "9", "--checkout", str(directed)], capture_output=True, text=True, env=env
    )
    assert failed.returncode == 1
    assert failed.stderr == "pr_gate: gh failed for #9: no such PR\n"


def test_a_checkout_of_another_repo_is_not_read(tmp_path: Path, directed: Path) -> None:
    proc = run_gate(tmp_path, directed, {7: pr(body="none", files=("src/land.py",))}, "--agent", "-R", "other/repo")
    assert (proc.returncode, proc.stdout) == (0, MAIN_READY)
    assert "is not a checkout of other/repo; REVIEW.md and the direction unread" in proc.stderr


@pytest.mark.parametrize("repo", ["demo/app", "Demo/App", "github.com/demo/app"])
def test_a_checkout_of_the_repo_r_names_is_read_whatever_its_case(tmp_path: Path, directed: Path, repo: str) -> None:
    """GitHub names ignore case, and gh takes [HOST/]OWNER/NAME: neither skips the direction"""
    git(directed, "remote", "set-url", "origin", "git@github.com:Demo/App.git")
    proc = run_gate(tmp_path, directed, {7: pr(body="none")}, "--bot-login", BOT, "-R", repo)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert proc.stderr == ""


def test_a_subdirectory_review_md_glob_also_matches_relative_to_its_folder(tmp_path: Path) -> None:
    """`shipmill review protect --dir skills github-pr-triage/**` writes a glob under skills/"""
    sub = "## Protected areas\n\n- `github-pr-triage/**`: it merges\n"
    work = checkout(tmp_path, {"skills/REVIEW.md": sub})
    proc = run_gate(tmp_path, work, {7: pr(files=("skills/github-pr-triage/scripts/pr_gate.py",))})
    assert proc.returncode == 5, proc.stdout
    assert "matches `github-pr-triage/**` (skills/REVIEW.md): it merges" in proc.stdout
    assert run_gate(tmp_path, work, {7: pr(files=("skills/other/x.py",))}).returncode == 0


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
