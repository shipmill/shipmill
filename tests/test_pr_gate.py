"""github-pr-triage's merge gate reads the PR's plan, the direction, and REVIEW.md's
Protected areas from the default branch (spec 024), end to end with a stand-in gh on PATH"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .conftest import copy_tree, no_auto_maintenance

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-pr-triage" / "scripts" / "pr_gate.py"
BOT = "shipmill-demo[bot]"
BASE_SHA = "ba5e0123456789"

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
import json, os, re, sys
fake = json.loads(open(os.environ["FAKE_GH_DATA"]).read())
args = sys.argv[1:]
with open(os.environ["FAKE_GH_CALLS"], "a") as calls:
    calls.write(json.dumps({{"args": args, "GH_REPO": os.environ.get("GH_REPO")}}) + "\\n")
files = re.compile(r"repos/(.+)/pulls/([0-9]+)/files[?]per_page=100")
base = fake["base"]
if args[:2] == ["pr", "view"]:
    print(json.dumps(fake[args[2]]))
elif args[0] == "api" and any(a.endswith("/status?per_page=100") for a in args):  # the base's statuses (D-75)
    statuses = base["statuses"]
    print(json.dumps({{"sha": base["sha"], "total_count": len(statuses), "statuses": statuses}}))
elif args[0] == "api" and any(a.endswith("/check-runs?per_page=100") for a in args):
    for run in base["check_runs"]:  # one object a line, as gh --jq .check_runs[] prints them
        print(json.dumps(run))
elif args[:2] == ["pr", "diff"]:
    sys.exit("HTTP 406: Sorry, the diff exceeded the maximum number of files (300)")
elif args[0] == "api" and "--paginate" in args and args[args.index("--jq") + 1] == ".[]":
    found = [files.fullmatch(a) for a in args if files.fullmatch(a)]
    pr = fake[found[0].group(2)]
    for path in pr["all_files"][: pr["listed"]]:  # every page, one object a line, as gh --jq prints them
        old = pr["renamed"].get(path)
        status = "renamed" if old else "added" if path in pr["added"] else "modified"
        print(json.dumps({{"filename": path, "status": status, **({{"previous_filename": old}} if old else {{}})}}))
elif args[0] == "api" and "graphql" in args:  # the issues a spec PR's lines name, as GitHub answers them
    query = [a for a in args if a.startswith("query=")][0]
    found, errors = {{"nameWithOwner": fake["repo"]}}, []
    for alias, number in re.findall(r"(i[0-9]+): issueOrPullRequest[(]number: ([0-9]+)[)]", query):
        found[alias] = fake["issues"].get(number)
        if found[alias] is None:
            errors.append({{"type": "NOT_FOUND", "path": ["repository", alias], "message": "Could not resolve"}})
    print(json.dumps({{"data": {{"repository": found}}, **({{"errors": errors}} if errors else {{}})}}))
    if errors:
        sys.exit("gh: Could not resolve to an issue or pull request")
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
    no_auto_maintenance(origin)
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
    listed: int | None = None,
    renamed: dict[str, str] | None = None,
    draft: bool = False,
    added: tuple[str, ...] = (),
    commits: tuple[str, ...] = ("Change the app",),
    title: str = "Change the app",
) -> dict[str, Any]:
    """listed caps the files the files API returns (GitHub's stops at 3000); renamed maps a
    file's new path to its old one; the files API reads added's files `added`, the others
    `modified` (or `renamed`); commits are the PR's commit messages, each on its own commit"""
    return {
        "title": title,
        "commits": [
            {"oid": f"abc{i}234fff", "messageHeadline": m.split("\n", 1)[0], "messageBody": m.partition("\n")[2]}
            for i, m in enumerate(commits, start=1)
        ],
        "state": "OPEN",
        "isDraft": draft,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefOid": "abcdef0123",
        "statusCheckRollup": [{"name": "test", "status": "COMPLETED", "conclusion": "SUCCESS"}],
        "author": {"login": login, "is_bot": login.startswith("app/")},
        "body": body,
        "files": [{"path": f} for f in files[:100]],
        "changedFiles": len(files) if changed is None else changed,
        "all_files": list(files),
        "listed": len(files) if listed is None else listed,
        "renamed": renamed or {},
        "added": list(added),
    }


def run_gate(
    tmp_path: Path,
    work: Path | None,
    prs: dict[int, dict[str, Any]],
    *args: str,
    issues: dict[int, dict[str, str]] | None = None,
    base: dict[str, Any] | None = None,
) -> subprocess.CompletedProcess[str]:
    """The gate with --checkout work, or, for None, run in a folder outside any checkout; issues
    are what GitHub's GraphQL answers for the repo demo/app's numbers; base, the base branch head's
    sha, statuses, and check_runs (default: a head with no checks)"""
    fakes = tmp_path / "fakes"
    fakes.mkdir(exist_ok=True)
    gh = fakes / "gh"
    gh.write_text(FAKE_GH.format(python=sys.executable), encoding="utf-8")
    gh.chmod(0o700)
    data = tmp_path / "gh.json"
    fake = {
        **{str(n): p for n, p in prs.items()},
        "repo": "demo/app",
        "issues": {str(n): i for n, i in (issues or {}).items()},
        "base": {"sha": BASE_SHA, "statuses": [], "check_runs": [], **(base or {})},
    }
    data.write_text(json.dumps(fake), encoding="utf-8")
    env = {
        **os.environ,
        "PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]),
        "FAKE_GH_DATA": str(data),
        "FAKE_GH_CALLS": str(tmp_path / "gh-calls"),
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


def test_a_fix_serving_a_listed_quality_bar_id_is_ready(tmp_path: Path, directed: Path) -> None:
    """#1016: `Serves:` names the Quality bar's ids too, alone or in `quality bar (...)`"""
    for serves in ("Q-1", "quality bar (Q-1)"):
        proc = run_gate(tmp_path, directed, {7: pr(body=PLAN.replace("G-3", serves))}, "--bot-login", BOT)
        assert proc.returncode == 0, proc.stdout + proc.stderr


def test_a_direction_without_a_quality_bar_section_lists_no_quality_bar_ids(tmp_path: Path) -> None:
    barless = DIRECTION.replace("## Quality bar\n\n- Q-1: Fail fast\n", "")
    assert ids_of({"docs/product.md": barless}) == {"U-1", "G-1", "G-3"}
    work = checkout(tmp_path, {"docs/product.md": barless})
    assert run_gate(tmp_path, work, {7: pr()}, "--bot-login", BOT).returncode == 0
    refused = run_gate(tmp_path, work, {7: pr(body=PLAN.replace("G-3", "Q-1"))}, "--bot-login", BOT)
    assert refused.returncode == 6, refused.stdout
    assert "  refused: `Serves:` names Q-1, which docs/product.md doesn't list" in refused.stdout


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


# #962: a check run twice on one head (a PR closed and reopened) counts once, its newest run


def run_of(conclusion: str | None, started: str | None, workflow: str = "CI", name: str = "test") -> dict[str, Any]:
    status = "IN_PROGRESS" if conclusion is None else "COMPLETED"
    run = {"__typename": "CheckRun", "workflowName": workflow, "name": name, "status": status, "conclusion": conclusion}
    return {**run, "startedAt": started} if started is not None else run


def with_rollup(*entries: dict[str, Any]) -> dict[str, Any]:
    data = pr(body="Fixes #7", login="amy")
    data["statusCheckRollup"] = list(entries)
    return data


def test_an_older_failure_and_a_newer_success_of_one_check_read_ready(tmp_path: Path) -> None:
    rollup = with_rollup(run_of("FAILURE", "2026-11-08T08:00:00Z"), run_of("SUCCESS", "2026-11-08T09:00:00Z"))
    proc = run_gate(tmp_path, None, {7: rollup})
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, MAIN_READY, "")


def test_an_older_success_and_a_newer_failure_of_one_check_read_failed(tmp_path: Path) -> None:
    """The newest run wins by its start, not by where the rollup lists it"""
    rollup = with_rollup(run_of("FAILURE", "2026-11-08T09:00:00Z"), run_of("SUCCESS", "2026-11-08T08:00:00Z"))
    proc = run_gate(tmp_path, None, {7: rollup})
    assert proc.returncode == gate.FAILED, proc.stdout + proc.stderr
    assert proc.stdout.splitlines() == [
        "#7 FAILED state=OPEN mergeable=MERGEABLE base=main head=abcdef0 checks=1 green=0 pending=0 failed=1",
        "  failed: test (FAILURE)",
    ]


def test_a_newer_run_in_flight_keeps_the_check_pending(tmp_path: Path) -> None:
    """A re-run not started yet has no start (gh's zero time), so the later entry wins"""
    for started in ("0001-01-01T00:00:00Z", None):
        rollup = with_rollup(run_of("SUCCESS", "2026-11-08T08:00:00Z"), run_of(None, started))
        proc = run_gate(tmp_path, None, {7: rollup})
        assert proc.returncode == gate.PENDING, proc.stdout + proc.stderr
        assert proc.stdout.splitlines()[0].endswith(" checks=1 green=0 pending=1 failed=0")


def test_a_run_in_flight_listed_before_an_older_pass_keeps_the_check_pending() -> None:
    """The rollup's order is not the runs' order: a run not started yet still wins"""
    for started in ("0001-01-01T00:00:00Z", None):
        checks = gate.newest_checks([run_of(None, started), run_of("SUCCESS", "2026-11-08T08:00:00Z")])
        assert checks == (gate.Check("test", False, ""),)


def test_a_start_with_a_fraction_of_any_length_is_read() -> None:
    """Python 3.10's fromisoformat takes neither Z nor a fraction other than 3 or 6 digits"""
    for older, newer in (
        ("2026-11-08T07:37:15.12Z", "2026-11-08T07:37:15.123Z"),
        ("2026-11-08T07:37:15.1234567Z", "2026-11-08T07:37:16Z"),
        ("2026-11-08T08:37:15+01:00", "2026-11-08T07:37:15.5Z"),
    ):
        checks = gate.newest_checks([run_of("SUCCESS", newer), run_of("FAILURE", older)])
        assert checks == (gate.Check("test", True, "SUCCESS"),), (older, newer)


def test_two_workflows_with_one_job_name_stay_two_checks(tmp_path: Path) -> None:
    rollup = with_rollup(
        run_of("SUCCESS", "2026-11-08T09:00:00Z", workflow="CI"),
        run_of("FAILURE", "2026-11-08T08:00:00Z", workflow="Downstream"),
    )
    proc = run_gate(tmp_path, None, {7: rollup})
    assert proc.returncode == gate.FAILED, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[0].endswith(" checks=2 green=1 pending=0 failed=1")


def test_a_status_context_counts_its_newest_state() -> None:
    started = "2026-11-08T08:00:00Z"
    older = {"__typename": "StatusContext", "context": "ci/lint", "state": "FAILURE", "startedAt": started}
    newer = {**older, "state": "SUCCESS", "startedAt": "2026-11-08T09:00:00Z"}
    assert gate.newest_checks([newer, older]) == (gate.Check("ci/lint", True, "SUCCESS"),)


def test_a_malformed_start_stops_the_gate() -> None:
    with pytest.raises(gate.GateError, match="startedAt"):
        gate.newest_checks([run_of("SUCCESS", "yesterday")])


# D-75 (#963): no pull request lands on a red default branch, save the one that repairs it

RUN_URL = "https://github.com/demo/app/actions/runs/900"


def base_run(
    conclusion: str | None,
    status: str = "completed",
    name: str = "test",
    run: int = 900,
    job: int = 901,
    started: str | None = "2026-11-08T08:00:00Z",
) -> dict[str, Any]:
    """A check run on the base head as the check-runs API lists it; an Actions job's check run id is its job id"""
    url = f"https://github.com/demo/app/actions/runs/{run}/job/{job}"
    return {
        "id": job,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "started_at": started,
        "html_url": url,
        "details_url": url,
        "check_suite": {"id": run + 7},
    }


RED = "  base: red: test failed on main@ba5e012"
REPAIRS = "  base: repairs: test failed on main@ba5e012"


def test_963_a_green_pr_on_a_red_base_fails(tmp_path: Path) -> None:
    proc = run_gate(tmp_path, None, {7: pr(body="Fixes #7", login="amy")}, base={"check_runs": [base_run("failure")]})
    assert proc.returncode == gate.FAILED == 1, proc.stdout + proc.stderr
    assert proc.stdout.splitlines() == [MAIN_READY.replace("READY", "FAILED").rstrip("\n"), RED]
    assert calls_of(tmp_path) == ["pr view", *CLOSERS_READ, *BASE_READS]  # Fixes #7 names an issue


@pytest.mark.parametrize(
    "runs",
    [
        pytest.param([base_run("success")], id="a green base"),
        pytest.param([base_run(None, "in_progress")], id="a base check still running"),
        pytest.param([base_run(None, "queued", started=None)], id="a base check queued"),
        pytest.param([base_run("cancelled"), base_run("skipped", name="lint", job=902)], id="cancelled and skipped"),
        pytest.param([base_run("neutral")], id="neutral"),
        pytest.param(
            [base_run("failure"), base_run("success", job=905, started="2026-11-08T09:00:00Z")], id="a green rerun"
        ),
    ],
)
def test_963_a_base_that_is_not_red_keeps_the_verdict(tmp_path: Path, runs: list[dict[str, Any]]) -> None:
    proc = run_gate(tmp_path, None, {7: pr(body="Fixes #7", login="amy")}, base={"check_runs": runs})
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, MAIN_READY, "")


@pytest.mark.parametrize("conclusion", ["failure", "timed_out", "action_required"])
def test_963_each_failed_conclusion_on_the_base_is_red(tmp_path: Path, conclusion: str) -> None:
    proc = run_gate(tmp_path, None, {7: pr(body="Fixes #7", login="amy")}, base={"check_runs": [base_run(conclusion)]})
    assert proc.returncode == 1 and RED in proc.stdout.splitlines(), proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "line",
    [
        pytest.param(f"Repairs: {RUN_URL}", id="the run"),
        pytest.param(f"- Repairs: {RUN_URL}/attempts/1", id="an attempt of the run, after a bullet"),
        pytest.param(f"Repairs: {RUN_URL}/job/901", id="the job"),
        pytest.param("Repairs: https://github.com/demo/app/runs/901", id="the check run"),
    ],
)
def test_963_the_pr_whose_repairs_line_names_the_failed_run_passes(tmp_path: Path, line: str) -> None:
    data = pr(body=f"{line}\n\nFixes #7", login="amy")
    proc = run_gate(tmp_path, None, {7: data}, base={"check_runs": [base_run("failure")]})
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, MAIN_READY + REPAIRS + "\n", "")


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("Repairs: https://github.com/demo/app/actions/runs/800", id="another run"),
        pytest.param(f"Repairs: {RUN_URL}/job/999", id="another job of the run"),
        pytest.param(f"Fixes the base. Repairs: {RUN_URL}", id="mid-line"),
        pytest.param(f"```\nRepairs: {RUN_URL}\n```", id="in a code fence"),
    ],
)
def test_963_a_repairs_line_naming_another_run_fails(tmp_path: Path, line: str) -> None:
    data = pr(body=f"{line}\n\nFixes #7", login="amy")
    proc = run_gate(tmp_path, None, {7: data}, base={"check_runs": [base_run("failure")]})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[1:] == [RED]


def test_963_a_repairs_line_covers_only_the_run_it_names(tmp_path: Path) -> None:
    runs = [base_run("failure"), base_run("failure", name="lint", run=910, job=911)]
    proc = run_gate(tmp_path, None, {7: pr(body=f"Repairs: {RUN_URL}", login="amy")}, base={"check_runs": runs})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[1:] == ["  base: red: lint failed on main@ba5e012", REPAIRS]


def test_963_a_failed_commit_status_on_the_base_is_red_until_named(tmp_path: Path) -> None:
    url = "https://ci.example.com/build/12"
    status = {"context": "ci/ext", "state": "error", "target_url": url, "created_at": "2026-11-08T08:00:00Z"}
    base = {"statuses": [status, {**status, "context": "ci/pending", "state": "pending"}]}
    proc = run_gate(tmp_path, None, {7: pr(body="Fixes #7", login="amy")}, base=base)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[1:] == ["  base: red: ci/ext failed on main@ba5e012"]
    named = run_gate(tmp_path, None, {7: pr(body=f"Repairs: {url}", login="amy")}, base=base)
    assert named.returncode == 0, named.stdout + named.stderr
    assert named.stdout.splitlines()[1:] == ["  base: repairs: ci/ext failed on main@ba5e012"]


def test_963_the_base_is_read_once_for_prs_that_share_it(tmp_path: Path) -> None:
    proc = run_gate(
        tmp_path, None, {7: pr(login="amy"), 8: pr(login="amy")}, base={"check_runs": [base_run("failure")]}
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert calls_of(tmp_path) == ["pr view", *CLOSERS_READ, *BASE_READS, "pr view", *CLOSERS_READ]


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


def gh_calls(tmp_path: Path) -> list[dict[str, Any]]:
    """Each gh call the gate made: its args and the GH_REPO it ran with"""
    return [json.loads(line) for line in (tmp_path / "gh-calls").read_text(encoding="utf-8").splitlines()]


FILES_API = "repos/{owner}/{repo}/pulls/7/files?per_page=100"
BASE_READS = ["status", "check-runs"]  # the base head's checks, one read per endpoint (D-75)
CLOSERS_READ = ["graphql"]  # the issues PLAN's Fixes #7 names, read for a ## Check (D-76)


def test_630_a_pr_of_more_than_300_files_is_read_through_the_files_api(tmp_path: Path, directed: Path) -> None:
    """gh pr diff refuses a diff over 300 files with HTTP 406 (the fake gh does too), so the gate never asks it"""
    files = tuple(f"src/m{i}.py" for i in range(349)) + ("src/land.py",)
    proc = run_gate(tmp_path, directed, {7: pr(files=files)}, "--bot-login", BOT)
    assert proc.returncode == 5, proc.stdout + proc.stderr
    assert "  needs-decision: src/land.py matches `src/land.py`" in proc.stdout
    api = [c for c in gh_calls(tmp_path) if FILES_API in c["args"]]
    assert api == [{"args": ["api", "--paginate", FILES_API, "--jq", ".[]"], "GH_REPO": None}]


@pytest.mark.parametrize(
    ("repo", "host"), [("demo/app", []), ("Demo/App", []), ("github.com/demo/app", ["--hostname", "github.com"])]
)
def test_630_r_names_the_repo_the_files_api_reads(tmp_path: Path, directed: Path, repo: str, host: list[str]) -> None:
    git(directed, "remote", "set-url", "origin", "git@github.com:Demo/App.git")
    files = tuple(f"src/m{i}.py" for i in range(349)) + ("src/land.py",)
    proc = run_gate(tmp_path, directed, {7: pr(files=files)}, "--bot-login", BOT, "-R", repo)
    assert proc.returncode == 5, proc.stdout + proc.stderr
    api = [c for c in gh_calls(tmp_path) if FILES_API in c["args"]]
    assert api == [{"args": ["api", *host, "--paginate", FILES_API, "--jq", ".[]"], "GH_REPO": repo}]


def test_630_a_pr_gh_pr_view_lists_whole_reads_no_more(tmp_path: Path, directed: Path) -> None:
    proc = run_gate(tmp_path, directed, {7: pr(files=tuple(f"src/m{i}.py" for i in range(100)))}, "--bot-login", BOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert calls_of(tmp_path) == ["pr view", *CLOSERS_READ, *BASE_READS]


def test_630_a_list_short_of_changed_files_stops_the_gate(tmp_path: Path, directed: Path) -> None:
    """GitHub's files API lists at most 3000 files: the gate judges no partial list"""
    files = tuple(f"src/m{i}.py" for i in range(3001))
    proc = run_gate(tmp_path, directed, {7: pr(files=files, listed=3000)}, "--bot-login", BOT)
    assert proc.returncode == 1
    assert proc.stderr.startswith("pr_gate: #7 changes 3001 files but GitHub lists 3000"), proc.stderr
    assert proc.stdout == ""


def test_630_a_renamed_file_is_judged_by_its_new_path_as_gh_pr_view_names_it(tmp_path: Path, directed: Path) -> None:
    files = tuple(f"src/m{i}.py" for i in range(150))
    renamed = {"src/m120.py": "src/land.py"}
    proc = run_gate(tmp_path, directed, {7: pr(files=files, renamed=renamed)}, "--bot-login", BOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr


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
    proc = run_gate(tmp_path, directed, {7: spec_pr(files=spec)}, "--bot-login", BOT, issues={12: OPEN_ISSUE})
    assert proc.returncode == 0, proc.stdout
    assert proc.stdout.splitlines()[0].startswith("#7 READY ")


def test_547_a_spec_pr_editing_the_direction_still_waits_on_the_maintainer(tmp_path: Path, directed: Path) -> None:
    # D-34: the spec's answer is no --maintainer-accepted, so the direction's edit holds it
    files = ("docs/specs/030-decision-policy.md", "docs/product.md")
    proc = run_gate(tmp_path, directed, {7: spec_pr(files=files)}, "--bot-login", BOT, issues={12: OPEN_ISSUE})
    assert proc.returncode == 5, proc.stdout
    assert "  needs-decision: docs/product.md edits the product's direction" in proc.stdout


# S-053-9, S-053-10: a spec pull request names its feature issue

SPEC = "docs/specs/054-release-digest.md"
SPEC_BODY = PLAN.replace("Fixes #7", "Spec for #12")
OPEN_ISSUE = {"__typename": "Issue", "state": "OPEN"}
ISSUES = {
    12: OPEN_ISSUE,
    13: {"__typename": "Issue", "state": "CLOSED"},
    14: {"__typename": "PullRequest"},
}
NO_ISSUE = '  spec: names no feature issue: add "Spec for #N" for the open issue it specifies'
MAIN_REFUSED = MAIN_READY.replace("READY", "REFUSED") + NO_ISSUE + "\n"


def spec_pr(body: str = SPEC_BODY, files: tuple[str, ...] = (SPEC,), **kw: Any) -> dict[str, Any]:
    """A PR adding its files under docs/specs/ (the files API reads them `added`)"""
    added = kw.pop("added", tuple(f for f in files if f.startswith("docs/specs/")))
    return pr(body=body, files=files, added=added, **kw)


def calls_of(tmp_path: Path) -> list[str]:
    """Each gh call the gate made, by its kind: `pr view`, `files` (the files API), `graphql`, or the
    base head's `status` and `check-runs` (D-75)"""
    kinds = []
    for call in gh_calls(tmp_path):
        args = call["args"]
        base = [a.rsplit("/", 1)[-1].split("?")[0] for a in args if a.startswith("repos/") and "/commits/" in a]
        kinds.append(
            base[0] if base else "graphql" if "graphql" in args else "files" if args[0] == "api" else " ".join(args[:2])
        )
    return kinds


@pytest.mark.parametrize("login", ["app/shipmill-demo", "amy"])
def test_s053_9_a_spec_pr_naming_no_issue_is_refused_whoever_opened_it(
    tmp_path: Path, directed: Path, login: str
) -> None:
    """an agent's PR with a valid plan and a person's alike, and --maintainer-accepted lifts nothing"""
    for accepted in ((), ("--maintainer-accepted",)):
        data = {7: spec_pr(body=PLAN, login=login)}
        proc = run_gate(tmp_path, directed, data, "--bot-login", BOT, *accepted, issues=ISSUES)
        assert proc.returncode == gate.REFUSED == 6, proc.stdout + proc.stderr
        assert proc.stdout == MAIN_REFUSED
    # outside a checkout nothing is read from the default branch, and the spec is still checked
    outside = run_gate(tmp_path, None, {7: spec_pr(body="Fixes #7", login=login)}, issues=ISSUES)
    assert (outside.returncode, outside.stdout) == (6, MAIN_REFUSED), outside.stderr


@pytest.mark.parametrize(
    ("line", "reads"),
    [
        pytest.param("Spec for #13", True, id="a closed issue"),
        pytest.param("Spec for #14", True, id="a pull request"),
        pytest.param("Spec for #99", True, id="no such number"),
        pytest.param("Spec for other/repo#12", True, id="another repo's issue"),
        pytest.param("Adds the spec. Spec for #12", False, id="mid-line"),
        pytest.param("`Spec for #12`", False, id="in a code span"),
        pytest.param("```\nSpec for #12\n```", False, id="in a code fence"),
        pytest.param("Spec for #99999999999", False, id="past any issue number"),
    ],
)
def test_s053_9_a_spec_for_line_naming_no_open_issue_of_the_repo_is_refused(
    tmp_path: Path, directed: Path, line: str, reads: bool
) -> None:
    proc = run_gate(tmp_path, directed, {7: spec_pr(body=f"{line}\n\n{PLAN}")}, "--bot-login", BOT, issues=ISSUES)
    assert (proc.returncode, proc.stdout) == (6, MAIN_REFUSED), proc.stderr
    assert calls_of(tmp_path) == ["pr view", "files", *(["graphql"] if reads else []), *CLOSERS_READ, *BASE_READS]


def test_s053_9_an_ask_or_never_zone_doesnt_hide_the_refusal(tmp_path: Path, agents: Path) -> None:
    """a spec PR reads the scope zone until --maintainer-accepted: the refusal holds with it, and
    REFUSED ranks above MAINTAINER_ONLY"""
    classify_as(tmp_path, {7: [PROTECTED_ZONE], 8: [DIRECTION_ZONE]})
    for accepted in ((), ("--maintainer-accepted",)):
        proc = run_gate(tmp_path, agents, {7: spec_pr(body=PLAN)}, "--bot-login", BOT, *accepted, issues=ISSUES)
        assert proc.returncode == 6, proc.stdout + proc.stderr
        assert NO_ISSUE in proc.stdout.splitlines()
    never = run_gate(tmp_path, agents, {8: spec_pr(body=PLAN)}, "--bot-login", BOT, issues=ISSUES)
    assert never.returncode == 6, never.stdout + never.stderr
    assert never.stdout.startswith("#8 REFUSED ")


def test_s053_9_a_draft_or_conflicting_spec_pr_keeps_its_verdict(tmp_path: Path, directed: Path) -> None:
    draft = run_gate(tmp_path, directed, {7: spec_pr(body=PLAN, draft=True)}, issues=ISSUES)
    assert draft.returncode == gate.DRAFT == 8, draft.stdout + draft.stderr  # D-52
    assert calls_of(tmp_path) == ["pr view"]  # a draft's files aren't read
    conflicting = spec_pr(body=PLAN)
    conflicting["mergeable"] = "CONFLICTING"
    blocked = run_gate(tmp_path, directed, {7: conflicting}, issues=ISSUES)
    assert blocked.returncode == gate.BLOCKED == 4, blocked.stdout  # as a conflicting plan refusal reads


@pytest.mark.parametrize("work", ["directed", None])
def test_s053_9_a_spec_past_the_first_hundred_files_is_found(
    tmp_path: Path, request: pytest.FixtureRequest, work: str | None
) -> None:
    """with a direction, all_files already read the files API: it isn't read again"""
    files = (*(f"src/m{i}.py" for i in range(120)), SPEC)
    checkout_ = request.getfixturevalue(work) if work else None
    proc = run_gate(tmp_path, checkout_, {7: spec_pr(body=PLAN, files=files)}, "--agent", issues=ISSUES)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert NO_ISSUE in proc.stdout.splitlines()
    assert calls_of(tmp_path) == ["pr view", "files", *CLOSERS_READ, *BASE_READS]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(SPEC_BODY, id="Spec for #N"),
        pytest.param(PLAN.replace("Fixes #7", "- Spec for #12"), id="after a list bullet"),
        pytest.param(PLAN.replace("Fixes #7", "* Spec for demo/app#12"), id="owner/repo#N of the repo"),
        pytest.param(PLAN.replace("Fixes #7", "Spec for Demo/App#12"), id="whatever its case"),
        pytest.param(PLAN.replace("Fixes #7", "Spec for #13\nSpec for #12"), id="a closed one, then an open one"),
    ],
)
def test_s053_10_a_spec_pr_naming_an_open_issue_is_not_refused(tmp_path: Path, directed: Path, body: str) -> None:
    proc = run_gate(tmp_path, directed, {7: spec_pr(body=body)}, "--bot-login", BOT, issues=ISSUES)
    assert (proc.returncode, proc.stdout) == (0, MAIN_READY), proc.stderr
    assert calls_of(tmp_path) == ["pr view", "files", "graphql", *BASE_READS]  # one read for every line's issue


def test_s053_10_r_names_the_repo_the_issues_are_read_from(tmp_path: Path, directed: Path) -> None:
    git(directed, "remote", "set-url", "origin", "git@github.com:demo/app.git")
    proc = run_gate(tmp_path, directed, {7: spec_pr()}, "--bot-login", BOT, "-R", "github.com/demo/app", issues=ISSUES)
    assert (proc.returncode, proc.stdout) == (0, MAIN_READY), proc.stderr
    [_, files, graphql, status, runs] = gh_calls(tmp_path)
    for call in (files, graphql, status, runs):
        assert call["args"][:3] == ["api", "--hostname", "github.com"]
        assert call["GH_REPO"] == "github.com/demo/app"
    assert graphql["args"][3:8] == ["graphql", "-F", "owner={owner}", "-F", "repo={repo}"]


@pytest.mark.parametrize(
    "kw",
    [
        pytest.param({"added": ()}, id="an edit of an existing spec"),
        pytest.param({"added": (), "renamed": {SPEC: "docs/specs/054-digest.md"}}, id="a renamed spec"),
    ],
)
def test_s053_10_a_pr_that_only_edits_a_spec_is_not_checked(tmp_path: Path, directed: Path, kw: Any) -> None:
    proc = run_gate(tmp_path, directed, {7: spec_pr(body=PLAN, **kw)}, "--bot-login", BOT, issues=ISSUES)
    assert (proc.returncode, proc.stdout) == (0, MAIN_READY), proc.stderr
    assert calls_of(tmp_path) == ["pr view", "files", *CLOSERS_READ, *BASE_READS]  # no spec issue to read


def test_s053_10_a_pr_adding_no_spec_path_reads_nothing_more(tmp_path: Path, directed: Path) -> None:
    files = ("docs/specs/TEMPLATE.md", "docs/specs/README.md", "docs/specs/54-short.md", "src/app.py")
    proc = run_gate(tmp_path, directed, {7: spec_pr(body=PLAN, files=files)}, "--bot-login", BOT, issues=ISSUES)
    assert (proc.returncode, proc.stdout) == (0, MAIN_READY), proc.stderr
    assert calls_of(tmp_path) == ["pr view", *CLOSERS_READ, *BASE_READS]


def test_s053_9_a_failing_issue_read_exits_1(tmp_path: Path, directed: Path) -> None:
    """gh's failure is never read as a missing issue: only a NOT_FOUND for a number the gate asked"""
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    (fakes / "gh").write_text(
        f"#!{sys.executable}\nimport json, sys\nargs = sys.argv[1:]\n"
        f"if args[:2] == ['pr', 'view']:\n    print({json.dumps(json.dumps(spec_pr()))})\n"
        "elif 'graphql' in args:\n    sys.exit('gh: HTTP 502')\n"
        "else:\n    print(json.dumps({'filename': " + repr(SPEC) + ", 'status': 'added'}))\n"
    )
    (fakes / "gh").chmod(0o700)
    env = {**os.environ, "PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"])}
    cmd = [sys.executable, str(SCRIPT), "7", "--checkout", str(directed)]
    failed = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert (failed.returncode, failed.stdout, failed.stderr) == (1, "", "pr_gate: gh failed for #7: gh: HTTP 502\n")


# D-76 (#965): a merge never closes an issue its PR is only part of, or one whose check has not run

CHECKED = {"__typename": "Issue", "state": "OPEN", "body": "Serve it.\n\n## Check\n\n`curl` shows it\n"}
LEAF = {"__typename": "Issue", "state": "OPEN", "body": "Serve it.\n"}
CLOSING = {12: LEAF, 13: CHECKED, 14: {**CHECKED, "state": "CLOSED"}, 15: {"__typename": "PullRequest"}}
REFUSED_LINE = MAIN_READY.replace("READY", "REFUSED")


def part_of(commits: tuple[str, ...], body: str = "Part of #12") -> dict[str, Any]:
    return pr(body=body, login="amy", commits=commits)


def test_965_a_commit_closing_a_part_of_issue_is_refused(tmp_path: Path) -> None:
    proc = run_gate(tmp_path, None, {7: part_of(("Serve it\n\nFixes #12",))}, issues=CLOSING)
    assert proc.returncode == gate.REFUSED == 6, proc.stdout + proc.stderr
    assert proc.stdout == REFUSED_LINE + "  refused: commit abc1234 closes #12, which the body lists as Part of #12\n"
    assert calls_of(tmp_path) == ["pr view", *BASE_READS]  # its issue needs no read


def test_965_a_commit_closing_an_issue_the_body_doesnt_list_as_part_of_is_ready(tmp_path: Path) -> None:
    for body in ("Fixes #12", "Part of #9"):
        proc = run_gate(tmp_path, None, {7: part_of(("Serve it\n\nFixes #12",), body=body)}, issues=CLOSING)
        assert (proc.returncode, proc.stdout, proc.stderr) == (0, MAIN_READY, "")


@pytest.mark.parametrize(
    ("commits", "body", "where"),
    [
        pytest.param(("Serve it\n\n- Closes #13",), "Serves it", "commit abc1234", id="in a commit"),
        pytest.param(("Fixes #13: serve it",), "Serves it", "commit abc1234", id="in a commit's headline"),
        pytest.param(("Serve it",), "Serves it\n\nResolves #13", "the body", id="in the body"),
    ],
)
def test_965_a_keyword_closing_an_open_issue_with_a_check_is_refused(
    tmp_path: Path, commits: tuple[str, ...], body: str, where: str
) -> None:
    proc = run_gate(tmp_path, None, {7: part_of(commits, body=body)}, issues=CLOSING)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    line = f"  refused: {where} closes #13, an open issue with a ## Check: write Part of #13 instead"
    assert proc.stdout == REFUSED_LINE + line + "\n"


def test_965_one_read_holds_every_issue_the_keywords_name(tmp_path: Path) -> None:
    commits = ("Serve it\n\nFixes #13", "Close it\n\nCloses #14\nFixes #15")
    proc = run_gate(tmp_path, None, {7: part_of(commits, body="Fixes #12\n\nPart of #14")}, issues=CLOSING)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[1:] == [
        "  refused: commit abc2234 closes #14, which the body lists as Part of #14",
        "  refused: commit abc1234 closes #13, an open issue with a ## Check: write Part of #13 instead",
    ]
    [graphql] = [c for c in gh_calls(tmp_path) if "graphql" in c["args"]]
    query = next(a for a in graphql["args"] if a.startswith("query="))
    assert [f"i{n}:" in query for n in (12, 13, 14, 15)] == [True, True, False, True]  # #14 is Part of


@pytest.mark.parametrize(
    ("commits", "body"),
    [
        pytest.param(("Serve it",), "Serves it\n\n```\nFixes #13\n```", id="in a code fence in the body"),
        pytest.param(("Serve it",), "Serves it, which fixes #13", id="mid-line in the body"),
        pytest.param(("Serve it",), "Serves it\n\n`Fixes #13`", id="in backticks in the body"),
        pytest.param(("Serve it",), "Serves it\n\nPart of #13", id="part of"),
        pytest.param(("Serve it, which prefixes #13 and unfixed #13",), "Serves it", id="not a whole word"),
        pytest.param(("Serve it, which fixes#13",), "Serves it", id="no space before the number"),
        pytest.param(("Serve it, which fixes #13a or closes #13_1",), "Serves it", id="not a number"),
        pytest.param(("Serve it, which fixing #13",), "Serves it", id="not a keyword"),
    ],
)
def test_965_a_keyword_that_names_nothing_reads_nothing(tmp_path: Path, commits: tuple[str, ...], body: str) -> None:
    proc = run_gate(tmp_path, None, {7: part_of(commits, body=body)}, issues=CLOSING)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, MAIN_READY, "")
    assert calls_of(tmp_path) == ["pr view", *BASE_READS]


def test_965_a_closed_issue_a_pull_request_or_no_issue_with_a_check_is_ready(tmp_path: Path) -> None:
    commits = ("Serve it\n\nFixes #14\nFixes #15\nFixes #99",)
    proc = run_gate(tmp_path, None, {7: part_of(commits, body="Serves it")}, issues=CLOSING)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, MAIN_READY, "")


def test_965_an_agents_pr_is_refused_for_its_plan_and_its_closers_alike(tmp_path: Path, directed: Path) -> None:
    data = pr(body="Fixes #13", commits=("Fixes #13",))
    proc = run_gate(tmp_path, directed, {7: data}, "--bot-login", BOT, issues=CLOSING)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    refused = [line for line in proc.stdout.splitlines() if line.startswith("  refused: ")]
    assert refused[0].startswith("  refused: no `## Plan` section")
    assert refused[1:] == [
        "  refused: commit abc1234 closes #13, an open issue with a ## Check: write Part of #13 instead",
        "  refused: the body closes #13, an open issue with a ## Check: write Part of #13 instead",
    ]


# #987: under a squash merge the title is the landed commit's subject (D-33), so its keyword closes too


def titled(title: str, body: str) -> dict[str, Any]:
    return pr(body=body, login="amy", commits=("Serve it",), title=title)


def test_987_a_title_closing_a_part_of_issue_is_refused(tmp_path: Path) -> None:
    proc = run_gate(tmp_path, None, {7: titled("Fixes #12: serve it", "Part of #12")}, issues=CLOSING)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert proc.stdout == REFUSED_LINE + "  refused: the title closes #12, which the body lists as Part of #12\n"
    assert calls_of(tmp_path) == ["pr view", *BASE_READS]  # its issue needs no read


@pytest.mark.parametrize("title", ["Fixes #13: serve it", "Serve it, which closes #13"])
def test_987_a_title_closing_an_open_issue_with_a_check_is_refused(tmp_path: Path, title: str) -> None:
    """a title's keyword counts anywhere outside code spans, keyword_closes' title rule"""
    proc = run_gate(tmp_path, None, {7: titled(title, "Serves it")}, issues=CLOSING)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    line = "  refused: the title closes #13, an open issue with a ## Check: write Part of #13 instead"
    assert proc.stdout == REFUSED_LINE + line + "\n"


@pytest.mark.parametrize(
    ("title", "body", "reads"),
    [
        pytest.param("Fixes #12: serve it", "Serves it", ["graphql"], id="an issue with neither"),
        pytest.param("Serve `Fixes #13`", "Serves it", [], id="in backticks"),
        pytest.param("Serve it (Part of #13)", "Serves it", [], id="part of"),
    ],
)
def test_987_a_title_naming_no_part_of_or_checked_issue_is_ready(
    tmp_path: Path, title: str, body: str, reads: list[str]
) -> None:
    proc = run_gate(tmp_path, None, {7: titled(title, body)}, issues=CLOSING)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, MAIN_READY, "")
    assert [c for c in calls_of(tmp_path) if c == "graphql"] == reads


# #988, D-79: GitHub closes an issue from a keyword anywhere in a landed commit's message, so a
# commit's keyword counts mid-line, in backticks, and in a fence too


@pytest.mark.parametrize(
    "commit",
    [
        pytest.param("Serve it, which fixes #12", id="mid-line"),
        pytest.param("Serve it\n\nThe `Fixes #12` line", id="in backticks"),
        pytest.param("Serve it\n\n```\nCLOSED: #12\n```", id="in a fence, upper case, with a colon"),
        pytest.param("Serve it\n\nand resolves Demo/App#12.", id="the repo's own owner/repo#N"),
    ],
)
def test_988_a_commit_closing_a_part_of_issue_anywhere_is_refused(tmp_path: Path, commit: str) -> None:
    proc = run_gate(tmp_path, None, {7: part_of((commit,))}, issues=CLOSING)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert proc.stdout == REFUSED_LINE + "  refused: commit abc1234 closes #12, which the body lists as Part of #12\n"


@pytest.mark.parametrize(
    "commit",
    [
        pytest.param("Serve it and fixes #13", id="mid-line"),
        pytest.param("Serve it (`closes #13`)", id="in backticks"),
        pytest.param("Serve it\n\nSee #12; this resolved demo/app#13, too", id="the repo's own owner/repo#N"),
    ],
)
def test_988_a_commit_closing_an_open_issue_with_a_check_anywhere_is_refused(tmp_path: Path, commit: str) -> None:
    proc = run_gate(tmp_path, None, {7: part_of((commit,), body="Serves it")}, issues=CLOSING)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    line = "  refused: commit abc1234 closes #13, an open issue with a ## Check: write Part of #13 instead"
    assert proc.stdout == REFUSED_LINE + line + "\n"


@pytest.mark.parametrize(
    ("commit", "reads"),
    [
        pytest.param("Serve it, which fixes #12", ["graphql"], id="an issue with neither, mid-line"),
        pytest.param("Serve it, which fixes other/repo#12 and closes other/repo#13", ["graphql"], id="another repo"),
    ],
)
def test_988_a_commit_naming_no_part_of_or_checked_issue_is_ready(
    tmp_path: Path, commit: str, reads: list[str]
) -> None:
    """another repo's owner/repo#N names nothing here, the read naming the PR's repo"""
    proc = run_gate(tmp_path, None, {7: part_of((commit,), body="Serves it\n\nPart of #14")}, issues=CLOSING)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, MAIN_READY, "")
    assert [c for c in calls_of(tmp_path) if c == "graphql"] == reads


def test_988_another_repos_issue_is_not_its_part_of(tmp_path: Path) -> None:
    proc = run_gate(tmp_path, None, {7: part_of(("Serve it\n\nFixes other/repo#12",))}, issues=CLOSING)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, MAIN_READY, "")


# #993: GitHub closes by an issue's URL after a keyword too, the PR's own repo's only


@pytest.mark.parametrize(
    "commit",
    [
        pytest.param("Serve it, which fixes https://github.com/demo/app/issues/12", id="mid-line"),
        pytest.param("Serve it\n\nCloses: https://github.com/Demo/App/issues/12.", id="a colon, the repo in any case"),
    ],
)
def test_993_a_commit_closing_a_part_of_issue_by_its_url_is_refused(tmp_path: Path, commit: str) -> None:
    proc = run_gate(tmp_path, None, {7: part_of((commit,))}, issues=CLOSING)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert proc.stdout == REFUSED_LINE + "  refused: commit abc1234 closes #12, which the body lists as Part of #12\n"


def test_993_a_commit_closing_an_open_issue_with_a_check_by_its_url_is_refused(tmp_path: Path) -> None:
    commit = "Serve it\n\n`resolves https://github.com/demo/app/issues/13`"
    proc = run_gate(tmp_path, None, {7: part_of((commit,), body="Serves it")}, issues=CLOSING)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    line = "  refused: commit abc1234 closes #13, an open issue with a ## Check: write Part of #13 instead"
    assert proc.stdout == REFUSED_LINE + line + "\n"


@pytest.mark.parametrize(
    "commit",
    [
        pytest.param("Serve it, which fixes https://github.com/other/repo/issues/13", id="another repo's issue"),
        pytest.param("Serve it, which fixes https://github.com/demo/app/pull/13", id="a pull request's URL"),
        pytest.param("Serve it, which fixes https://github.com/demo/app/issues/13a", id="not a number"),
    ],
)
def test_993_a_commit_url_naming_no_issue_of_the_repo_is_ready(tmp_path: Path, commit: str) -> None:
    proc = run_gate(tmp_path, None, {7: part_of((commit,), body="Serves it\n\nPart of #13")}, issues=CLOSING)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, MAIN_READY, "")


def test_the_worst_verdict_across_prs_is_the_exit_code(tmp_path: Path, directed: Path) -> None:
    proc = run_gate(tmp_path, directed, {7: pr(), 8: pr(body="none")}, "--bot-login", BOT)
    assert proc.returncode == 6
    assert [line.split()[1] for line in proc.stdout.splitlines() if line.startswith("#")] == ["READY", "REFUSED"]


# D-52, then D-67: a person's draft pull request belongs to them; the App's own is resumed (#914)


def test_673_a_green_draft_is_left_to_its_author(tmp_path: Path, directed: Path) -> None:
    proc = run_gate(tmp_path, directed, {7: pr(login="amy", draft=True)}, "--bot-login", BOT)
    assert proc.returncode == gate.DRAFT == 8, proc.stdout + proc.stderr
    assert proc.stdout.splitlines() == [
        "#7 DRAFT state=OPEN mergeable=MERGEABLE base=main head=abcdef0 checks=1 green=1 pending=0 failed=0",
        "  draft: left to its author until marked ready (D-67)",
    ]


@pytest.mark.parametrize("flags", [(), ("--bot-login", "other-app[bot]")])
def test_914_a_draft_without_the_bot_login_stays_its_authors(
    tmp_path: Path, directed: Path, flags: tuple[str, ...]
) -> None:
    """#914: an App draft read without --bot-login, or by another bot's, is anyone's draft"""
    proc = run_gate(tmp_path, directed, {7: pr(draft=True)}, *flags)
    assert proc.returncode == 8 and proc.stdout.endswith("  draft: left to its author until marked ready (D-67)\n")


def test_914_the_apps_own_draft_says_to_mark_it_ready(tmp_path: Path, directed: Path) -> None:
    """#914 (D-67): a draft the --bot-login authored still exits 8, its line telling the gate's
    session to mark it ready once nothing it waits on is open; its plan is still not read"""
    proc = run_gate(tmp_path, directed, {7: pr(body="none", draft=True)}, "--bot-login", BOT)
    assert proc.returncode == gate.DRAFT == 8, proc.stdout + proc.stderr
    assert proc.stdout.splitlines() == [
        "#7 DRAFT state=OPEN mergeable=MERGEABLE base=main head=abcdef0 checks=1 green=1 pending=0 failed=0",
        "  draft: the App's own, no session owns it: once nothing it waits on is open, mark it ready"
        " (gh pr ready 7, through shipmill gh) and run the gate again (D-67)",
    ]


def test_673_a_draft_is_judged_for_nothing_else(tmp_path: Path, directed: Path) -> None:
    """no plan, a protected file, a conflict, a failed check: still its author's, and --maintainer-accepted
    changes nothing"""
    draft = pr(body="none", files=("src/land.py",), draft=True)
    draft["mergeable"] = "CONFLICTING"
    draft["statusCheckRollup"] = [{"name": "test", "status": "COMPLETED", "conclusion": "FAILURE"}]
    for accepted in ((), ("--maintainer-accepted",)):
        proc = run_gate(tmp_path, directed, {7: draft}, "--bot-login", BOT, *accepted)
        assert proc.returncode == 8, proc.stdout + proc.stderr
        assert proc.stdout.startswith("#7 DRAFT state=OPEN mergeable=CONFLICTING")
        assert "refused:" not in proc.stdout and "needs-decision:" not in proc.stdout


def test_673_a_closed_draft_reads_blocked(tmp_path: Path, directed: Path) -> None:
    closed = pr(draft=True)
    closed["state"] = "CLOSED"
    proc = run_gate(tmp_path, directed, {7: closed})
    assert proc.returncode == 4, proc.stdout + proc.stderr


def test_673_a_draft_reads_neither_its_files_nor_its_zones(tmp_path: Path, agents: Path) -> None:
    record = classify_as(tmp_path, {7: [DIRECTION_ZONE]})
    proc = run_gate(tmp_path, agents, {7: pr(files=tuple(f"src/{n}.py" for n in range(150)), draft=True)})
    assert proc.returncode == 8, proc.stdout + proc.stderr
    assert uvx_calls(record) == []
    calls = [json.loads(line)["args"] for line in (tmp_path / "gh-calls").read_text().splitlines()]
    assert [c[:2] for c in calls] == [["pr", "view"]]


def test_673_draft_ranks_above_blocked_and_below_needs_decision(tmp_path: Path, directed: Path) -> None:
    conflicting = pr()
    conflicting["mergeable"] = "CONFLICTING"
    proc = run_gate(tmp_path, directed, {7: conflicting, 8: pr(draft=True)})
    assert proc.returncode == 8, proc.stdout + proc.stderr
    held = run_gate(tmp_path, directed, {7: pr(draft=True), 8: pr(files=("src/land.py",))})
    assert held.returncode == 5, held.stdout + held.stderr


def test_673_the_eval_cases_record_the_read_the_gate_makes() -> None:
    """evals/bin/gh answers only a recorded read: a gate asking other fields is a miss in every
    github-pr-triage case, and a recording without isDraft stops the gate"""
    evals = Path(__file__).resolve().parents[1] / "evals" / "github-pr-triage"
    found = 0
    for path in sorted(evals.glob("*/fixture/gh/*.json")):
        recording = json.loads(path.read_text(encoding="utf-8"))
        args = recording["args"]
        if args[:2] != ["pr", "view"] or "--json" not in args:
            continue
        fields = args[args.index("--json") + 1]
        if not {"statusCheckRollup", "changedFiles"} <= set(fields.split(",")):
            continue  # another skill step's read, not the gate's
        found += 1
        assert fields == gate.FIELDS, path
        assert set(json.loads(recording["stdout"])) == set(gate.FIELDS.split(",")), path
    assert found


def test_s053_9_the_eval_cases_record_a_spec_prs_reads() -> None:
    """a case whose gate read lists a spec file records the files API and the issues' GraphQL read
    too, as the gate asks them, or the case's no-miss grader fails"""
    evals = Path(__file__).resolve().parents[1] / "evals"
    found = 0
    for path in sorted(evals.glob("*/*/fixture/gh/*.json")):
        args = json.loads(path.read_text(encoding="utf-8"))["args"]
        if args[:2] != ["pr", "view"] or "--json" not in args or args[args.index("--json") + 1] != gate.FIELDS:
            continue
        shown = json.loads(json.loads(path.read_text(encoding="utf-8"))["stdout"])
        if not any(gate.SPEC_FILE.fullmatch(f["path"]) for f in shown["files"]):
            continue
        found += 1
        recorded = [json.loads(p.read_text(encoding="utf-8")) for p in path.parent.glob("*.json")]
        files_read = ["api", "--paginate", FILES_API.replace("/7/", f"/{args[2]}/"), "--jq", ".[]"]
        numbers = sorted({n for _, n in gate.spec_refs(shown["body"])})
        for read in (files_read, ["api", *gate.issues_read(numbers)]):
            assert [r for r in recorded if r["args"] == read and r["exit"] == 0], (path.parent, read[:3])
    assert found


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


# S-030-11, S-030-12: the decision policy's zones, from `shipmill decide classify`

AGENTS = '[agents]\nprompt = "/t"\n'
PLUGIN_VERSION = json.loads((SCRIPT.parents[3] / ".claude-plugin" / "plugin.json").read_text())["version"]
FAKE_UVX = """#!{python}
import json, os, sys
here = os.path.dirname(os.path.abspath(sys.argv[0]))
with open(os.path.join(here, "uvx-calls"), "a") as calls:
    calls.write(json.dumps(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
zones = json.loads(open(os.path.join(here, "zones.json")).read())
number = args[args.index("--pr") + 1]
if number not in zones:
    sys.exit("classify failed for #" + number)
print(json.dumps({{"level": None, "zones": zones[number], "candidates": []}}))
"""
DIRECTION_ZONE = {
    "zone": "direction",
    "level": "never",
    "reason": "docs/product.md edits the product's direction, which only the maintainer changes (D-34)",
}
PROTECTED_ZONE = {
    "zone": "protected",
    "level": "ask",
    "reason": "src/land.py matches `src/land.py` (REVIEW.md): pushes",
}
SECURITY_ZONE = {"zone": "security", "level": "notify", "reason": ".github/workflows/ci.yml is under .github/"}


def classify_as(tmp_path: Path, zones: dict[int, list[dict[str, str]]]) -> Path:
    """A uvx on the gate's PATH whose `shipmill decide classify` prints zones; its calls are recorded"""
    fakes = tmp_path / "fakes"
    fakes.mkdir(exist_ok=True)
    uvx = fakes / "uvx"
    uvx.write_text(FAKE_UVX.format(python=sys.executable), encoding="utf-8")
    uvx.chmod(0o700)
    (fakes / "zones.json").write_text(json.dumps({str(n): z for n, z in zones.items()}), encoding="utf-8")
    return fakes / "uvx-calls"


def uvx_calls(record: Path) -> list[list[str]]:
    return [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []


@pytest.fixture(scope="module")
def agents_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("agents")
    checkout(base, {"docs/product.md": DIRECTION, "REVIEW.md": REVIEW, ".github/shipmill.toml": AGENTS})
    return base


@pytest.fixture
def agents(tmp_path: Path, agents_template: Path) -> Path:
    """checkout() with the direction, a REVIEW.md, and [agents], copied from one built once"""
    copy_tree(agents_template, tmp_path)
    return tmp_path / "work"


def test_s030_11_a_never_zone_is_maintainer_only_with_or_without_acceptance(tmp_path: Path, agents: Path) -> None:
    record = classify_as(tmp_path, {7: [DIRECTION_ZONE]})
    for accepted in ((), ("--maintainer-accepted",)):
        proc = run_gate(tmp_path, agents, {7: pr(files=("docs/product.md",))}, "--bot-login", BOT, *accepted)
        assert proc.returncode == gate.MAINTAINER_ONLY == 7, proc.stdout + proc.stderr
        lines = proc.stdout.splitlines()
        assert lines[0].startswith("#7 MAINTAINER_ONLY state=OPEN")
        assert lines[1:] == [f"  maintainer-only: direction: {DIRECTION_ZONE['reason']}"]  # the D-34 ask is classify's
    [call, _] = uvx_calls(record)
    assert call == [
        f"shipmill=={PLUGIN_VERSION}", "--repo", str(agents), "decide", "classify", "--pr", "7",
        "--ref", "origin/main", "--json",
    ]  # fmt: skip


def test_s030_11_maintainer_only_ranks_above_needs_decision_and_below_refused(tmp_path: Path, agents: Path) -> None:
    classify_as(tmp_path, {7: [DIRECTION_ZONE], 8: [PROTECTED_ZONE], 9: []})
    held = run_gate(tmp_path, agents, {7: pr(), 8: pr()}, "--bot-login", BOT)
    assert held.returncode == 7, held.stdout + held.stderr
    refused = run_gate(tmp_path, agents, {7: pr(), 9: pr(body="none")}, "--bot-login", BOT)
    assert refused.returncode == 6, refused.stdout + refused.stderr
    assert [line.split()[1] for line in refused.stdout.splitlines() if line.startswith("#")] == [
        "MAINTAINER_ONLY",
        "REFUSED",
    ]


def test_s030_12_an_ask_zone_needs_a_decision_until_the_maintainer_accepts(tmp_path: Path, agents: Path) -> None:
    classify_as(tmp_path, {7: [PROTECTED_ZONE]})
    proc = run_gate(tmp_path, agents, {7: pr(files=("src/land.py",))}, "--bot-login", BOT)
    assert proc.returncode == 5, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[1:] == [f"  needs-decision: protected: {PROTECTED_ZONE['reason']}"]
    accepted = run_gate(tmp_path, agents, {7: pr(files=("src/land.py",))}, "--bot-login", BOT, "--maintainer-accepted")
    assert (accepted.returncode, accepted.stdout) == (0, MAIN_READY)
    failing = pr(files=("src/land.py",))
    failing["statusCheckRollup"] = [{"name": "test", "status": "COMPLETED", "conclusion": "FAILURE"}]
    ci = run_gate(tmp_path, agents, {7: failing}, "--bot-login", BOT, "--maintainer-accepted")
    assert ci.returncode == 1, ci.stdout  # CI alone judges it
    assert ci.stdout.splitlines()[1:] == ["  failed: test (FAILURE)"]


def test_s030_12_a_notify_zone_keeps_the_ci_verdict_and_prints_a_notify_line(tmp_path: Path, agents: Path) -> None:
    classify_as(tmp_path, {7: [SECURITY_ZONE, {"zone": "protected", "level": "act", "reason": "x"}]})
    proc = run_gate(tmp_path, agents, {7: pr(files=(".github/workflows/ci.yml",))}, "--bot-login", BOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout == MAIN_READY + f"  notify: security: {SECURITY_ZONE['reason']}\n"  # an act zone prints nothing
    failing = pr(files=(".github/workflows/ci.yml",))
    failing["statusCheckRollup"] = [{"name": "test", "status": "COMPLETED", "conclusion": "FAILURE"}]
    ci = run_gate(tmp_path, agents, {7: failing}, "--bot-login", BOT)
    assert ci.returncode == 1
    assert ci.stdout.splitlines()[1:] == ["  failed: test (FAILURE)", f"  notify: security: {SECURITY_ZONE['reason']}"]


DIRECTION_ASK = (
    "#7 NEEDS_DECISION state=OPEN mergeable=MERGEABLE base=main head=abcdef0 checks=1 green=1 pending=0 failed=0\n"
    "  needs-decision: docs/product.md edits the product's direction, which only the maintainer changes (D-34)\n"
)


@pytest.mark.parametrize("config", [None, "[release]\n", "# [agents]\n"])
def test_s030_12_without_agents_on_the_base_a_direction_edit_gates_as_before(
    tmp_path: Path, config: str | None
) -> None:
    files = {"docs/product.md": DIRECTION, "REVIEW.md": REVIEW}
    work = checkout(tmp_path, files if config is None else {**files, ".github/shipmill.toml": config})
    (work / ".github").mkdir(exist_ok=True)
    (work / ".github" / "shipmill.toml").write_text(AGENTS)  # the working tree's config is not the base's
    record = classify_as(tmp_path, {7: [DIRECTION_ZONE]})
    proc = run_gate(tmp_path, work, {7: pr(files=("docs/product.md",))}, "--bot-login", BOT)
    assert (proc.returncode, proc.stdout, proc.stderr) == (5, DIRECTION_ASK, "")
    assert uvx_calls(record) == []


def test_s030_11_a_failing_classify_stops_the_gate(tmp_path: Path, agents: Path) -> None:
    classify_as(tmp_path, {})
    proc = run_gate(tmp_path, agents, {7: pr()}, "--bot-login", BOT)
    assert proc.returncode == 2
    assert "decide classify --pr 7 --ref origin/main --json` failed for #7: classify failed for #7" in proc.stderr
    assert (
        f"shipmill=={PLUGIN_VERSION} is the release the plugin pins: if PyPI doesn't serve it yet, wait for its "
        "publish, or pass --tool <path or URL> to run another shipmill" in proc.stderr
    )  # the fix is named (Q-1)
    tool = run_gate(tmp_path, agents, {7: pr()}, "--bot-login", BOT, "--tool", "./shipmill")
    assert tool.returncode == 2
    assert (
        "failed for #7: classify failed for #7; check that --tool ./shipmill is a shipmill uvx can run" in tool.stderr
    )


@pytest.mark.skipif(shutil.which("uvx", path="/usr/bin:/bin") is not None, reason="uvx is on the gate's PATH")
def test_s030_11_without_uvx_the_gate_stops_naming_the_fix(tmp_path: Path, agents: Path) -> None:
    proc = run_gate(tmp_path, agents, {7: pr()}, "--bot-login", BOT)
    assert (proc.returncode, proc.stdout) == (2, "")
    assert "uvx is not on PATH" in proc.stderr
    assert "install uv, https://docs.astral.sh/uv/" in proc.stderr


def test_s030_11_a_zone_the_gate_doesnt_know_stops_it() -> None:
    with pytest.raises(gate.GateError, match="zone 'nope' at 'never'"):
        gate.parse_zones(json.dumps({"zones": [{"zone": "nope", "level": "never", "reason": "x"}]}), 7)
    with pytest.raises(gate.GateError, match="no zones list"):
        gate.parse_zones("{}", 7)


def test_s030_11_tool_runs_classify_from_another_shipmill(tmp_path: Path, agents: Path) -> None:
    record = classify_as(tmp_path, {7: []})
    proc = run_gate(tmp_path, agents, {7: pr()}, "--bot-login", BOT, "--tool", "git+https://example.com/x")
    assert (proc.returncode, proc.stdout) == (0, MAIN_READY), proc.stderr
    assert uvx_calls(record)[0][:3] == ["--from", "git+https://example.com/x", "shipmill"]


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
        ("Q-6", None),
        ("quality bar (Q-6)", None),
        ("G-2, Q-4", None),
        ("quality bar (Q-4, Q-6)", None),
        ("G-2, quality bar (Q-4, Q-6)", None),
        ("N-1", "`Serves:` names 'N-1'; it names goal ids (G-n), `quality bar`, or quality-bar ids (Q-n)"),
        ("G-1, G-7", "`Serves:` names G-7, which docs/product.md doesn't list"),
        ("Q-9", "`Serves:` names Q-9, which docs/product.md doesn't list"),
        ("quality bar (Q-9)", "`Serves:` names Q-9, which docs/product.md doesn't list"),
        ("quality bar (X)", "`Serves:` names 'X' in `quality bar (...)`; it holds quality-bar ids (Q-n)"),
        ("quality bar (G-2)", "`Serves:` names 'G-2' in `quality bar (...)`"),
        ("quality bar ()", "`Serves:` names '' in `quality bar (...)`"),
        ("quality bar (Q-4", "`Serves:` names 'quality bar (Q-4'"),
    ],
)
def test_s024_7_serves_names_listed_goals_or_the_quality_bar(serves: str, problem: str | None) -> None:
    """#1016: a listed quality-bar id serves too, alone or as `quality bar (Q-n[, Q-m])`"""
    body = PLAN.replace("- Serves: G-3", f"- Serves: {serves}")
    found = gate.plan_problems(body, frozenset({"G-1", "G-2", "G-3", "N-1", "Q-1", "Q-4", "Q-6"}))
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
