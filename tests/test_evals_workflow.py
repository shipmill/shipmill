"""Spec 025: `.github/workflows/evals.yml` runs the suite and gates a pull request on it (D-37).

The workflow is read with the eval suite's own strict YAML reader, and its small shell steps
(choosing the run, refusing a fork, minting the Anthropic token) run here as bash with the env GitHub gives
them, so their exits and lines are proved, not only their text."""

import json
import os
import re
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest

from shipmill import evals

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "evals.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
DOC: Any = evals._Yaml(TEXT, "evals.yml").mapping()
JOB = DOC["jobs"]["evals"]
STEPS: list[dict[str, Any]] = JOB["steps"]
FORK_LINE = "evals: a fork's pull request runs only by hand: gh workflow run evals.yml -f pr={pr} -f sha={sha}"
SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"
PIN = "Read the pull request's head before any checkout (S-025-20)"
MERGE = "Check the merge ref's head is the one read (S-025-21)"
MOVED = "evals: the head of #{pr} is {current}, not {sha}; read the new commits and dispatch again with "
MOVED += "-f sha={current}"
MINT = "Mint the Anthropic token (S-025-24, S-025-26)"
NO_TOKEN = "evals: no Anthropic token from Workload Identity Federation ({reason}), so no case ran"
MAIN_RULE = "fdrl_01Pk7bGkjpHPcaWhVmDNMffp"
PR_RULE = "fdrl_01UA2FpuviYTtJHRe7EJskA2"
OIDC = "ACTIONS_ID_TOKEN_REQUEST_URL", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"


def _step(name: str) -> dict[str, Any]:
    found = [s for s in STEPS if s.get("name") == name]
    assert len(found) == 1, f"one step named {name!r}"
    return found[0]


def _index(name: str) -> int:
    return STEPS.index(_step(name))


def _env(name: str) -> dict[str, object]:
    env = _step(name).get("env", {})
    assert isinstance(env, dict)
    return env


def _script(name: str) -> str:
    """A step's run script as GitHub runs it: the block scalar, dedented"""
    lines = TEXT.splitlines()
    start = lines.index(f"      - name: {name}")
    run = next(i for i in range(start, len(lines)) if lines[i] == "        run: |")
    body: list[str] = []
    for line in lines[run + 1 :]:
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line)
    return textwrap.dedent("\n".join(body))


def _bash(name: str, tmp_path: Path, **env: str) -> tuple[int, str, dict[str, str]]:
    """Run a step's script with `bash -e`, as the runner does; its exit, stdout, and outputs"""
    return _bash_in(None, name, tmp_path, env)


def _bash_in(cwd: Path | None, name: str, tmp_path: Path, env: dict[str, str]) -> tuple[int, str, dict[str, str]]:
    """_bash in the directory cwd, as a step runs in the checkout"""
    output, summary = tmp_path / "output", tmp_path / "summary"
    output.write_text("")
    summary.write_text("")
    full = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary)}
    proc = subprocess.run(
        ["bash", "-e", "-c", _script(name)], env=full | env, capture_output=True, text=True, check=False, cwd=cwd
    )
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    return proc.returncode, proc.stdout, outputs


def _matches(pattern: str, path: str) -> bool:
    """GitHub's path filter glob: `**` crosses directories, `*` does not"""
    regex = re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.fullmatch(regex, path) is not None


# S-025-10: the triggers


def test_s025_10_runs_only_by_hand_while_d72_holds() -> None:
    # no schedule and no pull_request trigger until the baseline passes 60% of its runs (D-72, #950)
    on = DOC["on"]
    assert isinstance(on, dict)
    assert sorted(on) == ["workflow_dispatch"]
    header = TEXT[: TEXT.index("\nname: evals\n")]
    assert "Only by hand while D-72 holds (#950): no schedule and no pull_request trigger." in header
    assert "passes at least 60%" in header
    assert "schedule:" not in TEXT and "cron" not in TEXT and "weekly" not in TEXT
    assert "schedule)" not in _script("Choose what this run is")


@pytest.mark.parametrize(
    ("path", "runs"),
    [
        ("skills/github-pr-triage/SKILL.md", True),
        ("skills/github-issue-triage/agents/openai.yaml", True),
        (".claude-plugin/plugin.json", True),
        ("evals/cases.toml", True),
        ("evals/product-intake/no-goal-not-proposed/prompt.md", True),
        ("src/shipmill/gate.py", True),
        ("src/shipmill/cli.py", False),
        ("src/shipmill/gate_extra.py", False),
        ("docs/specs/025-agent-evals.md", False),
        ("tests/test_evals.py", False),
        (".github/workflows/evals.yml", False),
        ("CHANGELOG.md", False),
    ],
)
def test_s025_10_the_trigger_to_restore_covers_only_the_agents(path: str, runs: bool) -> None:
    # the header keeps the paths the pull_request trigger comes back with (D-72)
    found = re.search(r"^#     paths: (\[.*\])$", TEXT, re.MULTILINE)
    assert found is not None
    paths = json.loads(found[1])
    assert paths == ["skills/**", ".claude-plugin/**", "evals/**", "src/shipmill/gate.py"]
    assert any(_matches(p, path) for p in paths) is runs


def test_s025_19_dispatch_takes_a_pr_a_sha_and_a_model() -> None:
    inputs = DOC["on"]["workflow_dispatch"]["inputs"]
    assert sorted(inputs) == ["model", "pr", "sha"]
    assert all(i["type"] == "string" and i["default"] == "" for i in inputs.values())


@pytest.mark.parametrize(
    ("env", "outputs"),
    [
        ({"EVENT": "pull_request", "PR_EVENT": "41"}, {"mode": "pr", "pr": "41", "ref": "", "sha": ""}),
        ({"EVENT": "workflow_dispatch"}, {"mode": "baseline", "pr": "", "ref": "", "sha": ""}),
        (
            {"EVENT": "workflow_dispatch", "PR_INPUT": "7", "SHA_INPUT": SHA},
            {"mode": "pr", "pr": "7", "ref": "refs/pull/7/merge", "sha": SHA},
        ),
        ({"EVENT": "workflow_dispatch", "MODEL_INPUT": "claude-other"}, {"mode": "model", "model": "claude-other"}),
    ],
)
def test_s025_10_each_event_chooses_its_run(tmp_path: Path, env: dict[str, str], outputs: dict[str, str]) -> None:
    base = {"REF": "refs/heads/main", "DEFAULT": "main", "EVALS_MODEL": "claude-pinned"}
    code, _, got = _bash("Choose what this run is", tmp_path, **(base | env))
    assert code == 0
    assert got | outputs == got, got
    if "MODEL_INPUT" not in env:
        assert got["model"] == "claude-pinned"


@pytest.mark.parametrize(
    "env",
    [
        {"EVENT": "workflow_dispatch", "REF": "refs/heads/feature"},  # the baseline is the default branch's
        {"EVENT": "workflow_dispatch", "PR_INPUT": "7; rm -rf /"},
        {"EVENT": "push"},
        {"EVENT": "schedule"},  # only by hand while D-72 holds (#950)
    ],
)
def test_s025_10_a_run_elsewhere_is_refused(tmp_path: Path, env: dict[str, str]) -> None:
    base = {"REF": "refs/heads/main", "DEFAULT": "main", "EVALS_MODEL": "claude-pinned"}
    code, out, _ = _bash("Choose what this run is", tmp_path, **(base | env))
    assert code == 1
    assert out.startswith("::error::evals: ")


# S-025-11: the eval run


def _command() -> str:
    """The suite's one command line, from its subshell's `(cd` to its close"""
    script = _script("Run the suite")
    start = script.index('(cd "$tree"')
    return script[start : script.index(") || code=$?", start)]


def test_s025_11_the_run_passes_the_spec_flags() -> None:
    command = _command()
    # 25 USD: 48 runs at about 0.36 USD each exceed 15, so a run ended partial (#954); three
    # runs a case, the count D-37's rules are written for
    for flag in ("--ablation none", "--no-publish", '--model "$MODEL"', "--runs 3", "-j 4", "--max-cost-usd 25"):
        assert re.search(rf"(?<!\S){re.escape(flag)}(?!\S)", command), flag
    assert "--trust-plugin" in command and "--scaffold" in command and "--json" in command


def test_s025_11_the_model_is_the_gate_sessions_written_once() -> None:
    pinned = DOC["env"]["EVALS_MODEL"]
    assert isinstance(pinned, str) and pinned.startswith("claude-")
    assert TEXT.count(pinned) == 1
    assert _env("Run the suite")["MODEL"] == "${{ steps.plan.outputs.model }}"
    assert "model=${MODEL_INPUT:-$EVALS_MODEL}" in _script("Choose what this run is")


def test_s025_11_s025_29_the_stub_is_first_on_path_and_no_token_reaches_the_run() -> None:
    # proves: S-025-29
    command = _command()
    unset = "GH_TOKEN GITHUB_TOKEN ACTIONS_ID_TOKEN_REQUEST_URL ACTIONS_ID_TOKEN_REQUEST_TOKEN"
    unset += " ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN"
    assert re.search(r"env " + r" \\?\s*".join(f"-u {v}" for v in unset.split()), command), command
    # the session can't read the tree, so an entry in it lets the real gh answer (#933): the
    # stub is the workspace's copy, found from the workspace or a worktree two levels down
    assert 'ANTHROPIC_IDENTITY_TOKEN_FILE="$token_file" PATH=".eval/bin:../.eval/bin:../../.eval/bin:$PATH"' in command
    assert "evals/bin" not in command
    env = _env("Run the suite")
    assert not {"GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"} & set(env)
    assert all("github.token" not in str(v) and "GITHUB_TOKEN" not in str(v) for v in env.values())
    # only the head read and the baseline lookup hold a token; the checkout the cases clone keeps none
    holders = [s.get("name") for s in STEPS if re.search(r"github\.token|GITHUB_TOKEN|GH_TOKEN", str(s.get("env", "")))]
    assert holders == [PIN, "Find the default branch's baseline (S-025-12)"]
    checkout = next(s for s in STEPS if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] == "false"
    assert JOB["permissions"] == {"contents": "read", "actions": "read", "pull-requests": "read", "id-token": "write"}
    assert DOC["permissions"] == {"contents": "read"}


def test_s025_11_uploads_the_json_result_and_the_html_report() -> None:
    upload = _step("Upload the result and the report")
    assert str(upload["uses"]).startswith("actions/upload-artifact@")
    paths = upload["with"]["path"].split("\n")
    assert "${{ runner.temp }}/evals/head/" in paths  # aggregate-result.json
    assert "evals/results/" in paths  # the runner's HTML report
    assert "always()" in str(upload["if"])


def test_s025_11_the_summary_holds_the_moved_cases_the_pass_rates_and_the_spend() -> None:
    compare = _script("Compare against the default branch (D-37)")
    assert 'uv run shipmill evals compare --base "$base" --head "$head"' in compare
    assert 'cat "$RUNNER_TEMP/compare.txt"' in compare and 'tee -a "$GITHUB_STEP_SUMMARY"' in compare
    spend = _script("Report the spend")
    assert ".costUsd" in spend and ".turns" in spend and ".durationSeconds" in spend
    assert 'tee -a "$GITHUB_STEP_SUMMARY"' in spend
    assert "always()" in str(_step("Report the spend")["if"])


def test_s025_11_no_expression_inside_a_run_script() -> None:
    # github.event values reach a script through env, never as ${{ }} text (script injection)
    for step in STEPS:
        assert "${{" not in str(step.get("run", "")), step.get("name")


# S-025-12: the baseline


def test_s025_12_the_baseline_is_the_latest_successful_default_branch_run() -> None:
    lookup = _script("Find the default branch's baseline (S-025-12)")
    assert 'gh run list -R "$REPO" --workflow evals.yml --branch "$DEFAULT" --status success' in lookup
    assert 'select(.event == "schedule" or .event == "workflow_dispatch")' in lookup
    assert 'gh run download "$id" -R "$REPO" -n evals-baseline' in lookup
    assert '"$age" -gt $(( 14 * 86400 ))' in lookup
    assert '"$base_model" != "$MODEL"' in lookup
    assert "fresh=true" in lookup and "fresh=false" in lookup
    assert _index("Find the default branch's baseline (S-025-12)") < _index("Run the suite")


def test_s025_12_only_a_full_pinned_run_on_the_default_branch_becomes_the_baseline() -> None:
    keep = _step("Keep the run as the baseline")
    assert keep["if"] == "steps.plan.outputs.mode == 'baseline' && steps.run.outcome == 'success'"
    assert ".partial" in _script("Keep the run as the baseline")
    upload = _step("Upload the baseline")
    assert upload["if"] == "steps.baseline.outcome == 'success'"
    assert upload["with"]["name"] == "evals-baseline"
    assert "${{ runner.temp }}/evals/head/meta.json" in upload["with"]["path"]
    assert "{model: $model, commit: $commit, claude: $claude, exit: $code," in _script("Run the suite")


KEEP = "Keep the run as the baseline"
REFUSED = "evals: no case ran ({errored} of {runs} runs errored, {turns} turns), so the run is no baseline"
ESCAPES = 'case "c": path "../../scaffold.sh" escapes the case directory'


def _arm(turns: int, error: str | None = None) -> dict[str, object]:
    return {"score": 0, "passed": False, "turns": turns, "costUsd": 0, "error": error, "graders": []}


def _keep(tmp_path: Path, arms: list[list[dict[str, object]]], partial: bool = False) -> tuple[int, str, str]:
    """The baseline step on a result whose cases hold these runs; its exit, stdout, summary"""
    head = tmp_path / "evals" / "head"
    head.mkdir(parents=True)
    cases = [{"name": f"c{n}", "dir": f"evals/s/c{n}", "arms": {"with": runs}} for n, runs in enumerate(arms)]
    result = {"schemaVersion": 1, "partial": partial, "cases": cases, "aggregates": {"casesTotal": len(cases)}}
    (head / "aggregate-result.json").write_text(json.dumps(result), encoding="utf-8")
    code, out, _ = _bash(KEEP, tmp_path, RUNNER_TEMP=str(tmp_path))
    return code, out, (tmp_path / "summary").read_text()


def test_s025_28_a_run_where_every_case_errored_before_a_turn_is_no_baseline(tmp_path: Path) -> None:
    # run 42242802136: all 14 cases refused their scaffold, partial false, 0 turns (#929)
    code, out, summary = _keep(tmp_path, [[_arm(0, ESCAPES)] * 3] * 2)
    line = REFUSED.format(errored=6, runs=6, turns=0)
    assert code == 1
    assert f"::error::{line}" in out
    assert summary == line + "\n"


@pytest.mark.parametrize(
    ("arms", "line"),
    [
        ([], REFUSED.format(errored=0, runs=0, turns=0)),  # no case at all
        ([[_arm(0)] * 3], REFUSED.format(errored=0, runs=3, turns=0)),  # no error, but no turn either
        ([[_arm(12, "timeout"), _arm(5, "timeout")]], REFUSED.format(errored=2, runs=2, turns=17)),
    ],
)
def test_s025_28_a_run_with_no_completed_run_is_no_baseline(
    tmp_path: Path, arms: list[list[dict[str, object]]], line: str
) -> None:
    code, _, summary = _keep(tmp_path, arms)
    assert (code, summary) == (1, line + "\n")


def test_s025_28_a_run_where_one_case_ran_is_kept(tmp_path: Path) -> None:
    code, out, summary = _keep(tmp_path, [[_arm(0, ESCAPES)] * 3, [_arm(9), _arm(11, "timeout"), _arm(7)]])
    assert (code, out, summary) == (0, "", "")


def test_s025_12_a_partial_run_is_no_baseline(tmp_path: Path) -> None:
    code, out, _ = _keep(tmp_path, [[_arm(9)] * 3], partial=True)
    assert code == 1
    assert "::error::evals: the run stopped early (partial), so it is no baseline" in out


def test_s025_28_a_baseline_that_ran_no_case_is_skipped_for_the_merge_base() -> None:
    lookup = _script("Find the default branch's baseline (S-025-12)")
    assert 'select((.error // "") == "" and (.turns // 0) > 0)' in lookup
    assert 'reason="the baseline, run $id, ran no case"' in lookup
    assert lookup.index("ran no case") < lookup.index("fresh=true")


def test_s025_27_the_virtualenv_lies_outside_the_checkout_the_runner_scans(tmp_path: Path) -> None:
    # `claude plugin eval` refused every case for a hard link uv made into .venv in the checkout (#929)
    [sync] = [s for s in STEPS if "uv sync" in str(s.get("run", ""))]
    assert STEPS.index(sync) < _index("Run the suite")
    workspace, temp, bin_dir = tmp_path / "workspace", tmp_path / "temp", tmp_path / "bin"
    for d in (workspace, temp, bin_dir):
        d.mkdir()
    (bin_dir / "uv").write_text(f'#!/bin/sh\necho "$UV_PROJECT_ENVIRONMENT" >> {tmp_path / "uv.log"}\n')
    (bin_dir / "uv").chmod(0o755)
    github_env = tmp_path / "github_env"
    github_env.write_text("")
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "RUNNER_TEMP": str(temp), "GITHUB_WORKSPACE": str(workspace)}
    env["GITHUB_ENV"] = str(github_env)
    subprocess.run(["bash", "-e", "-c", str(sync["run"])], env=env, cwd=workspace, check=True)
    venv = Path((tmp_path / "uv.log").read_text().strip())
    assert venv.is_absolute() and venv.is_relative_to(temp) and not venv.is_relative_to(workspace)
    # every later step, `uv run` too, gets the same virtualenv
    assert github_env.read_text().splitlines() == [f"UV_PROJECT_ENVIRONMENT={venv}"]


SANDBOX = "Install the sandbox the cases' shell tool needs (S-025-27)"


def _sandbox(tmp_path: Path, userns: bool) -> tuple[int, list[str]]:
    """Run the sandbox step with stub sudo, apt-get, sysctl, and bwrap; its exit and the commands run"""
    bin_dir, log, lifted = tmp_path / "bin", tmp_path / "calls.log", tmp_path / "lifted"
    bin_dir.mkdir()
    stubs = {
        "sudo": 'exec "$@"',
        "apt-get": f'echo "apt-get $*" >> {log}',
        "sysctl": f'echo "sysctl $*" >> {log}; touch {lifted}',
        # bwrap gets a user namespace when the runner allows one, or once the sysctl lifted the limit
        "bwrap": f'echo "bwrap" >> {log}; [ {"true" if userns else "false"} = true ] || [ -e {lifted} ]',
    }
    for name, body in stubs.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_dir / name).chmod(0o755)
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    proc = subprocess.run(["bash", "-e", "-c", _script(SANDBOX)], env=env, check=False)
    return proc.returncode, log.read_text().splitlines()


def test_s025_27_the_sandbox_is_installed_before_the_suite_runs(tmp_path: Path) -> None:
    # every case was refused before a turn: bubblewrap and socat not installed (#929)
    step = _step(SANDBOX)
    assert step["if"] == "steps.token.outputs.ok == 'true'"
    assert _index("Install Claude Code") < _index(SANDBOX) < _index("Run the suite")
    code, calls = _sandbox(tmp_path, userns=True)
    assert code == 0
    assert "apt-get install -y -q bubblewrap socat" in calls
    # AppArmor's limit stays as it is when bwrap already gets a user namespace
    assert not [c for c in calls if c.startswith("sysctl")]


def test_s025_27_the_user_namespace_limit_is_lifted_only_when_bwrap_fails(tmp_path: Path) -> None:
    code, calls = _sandbox(tmp_path, userns=False)
    assert code == 0
    assert calls[-3:] == ["bwrap", "sysctl -w kernel.apparmor_restrict_unprivileged_userns=0", "bwrap"]


def test_s025_12_the_merge_base_runs_first_when_the_baseline_is_missing_stale_or_another_models() -> None:
    env = _env("Run the suite")
    assert env["ON_MERGE_BASE"] == "${{ steps.plan.outputs.mode == 'pr' && steps.base.outputs.fresh != 'true' }}"
    script = _script("Run the suite")
    merge_base = script.index('suite "$RUNNER_TEMP/evals/base-tree" "$RUNNER_TEMP/evals/base"')
    head = script.index('suite "$GITHUB_WORKSPACE" "$RUNNER_TEMP/evals/head"')
    assert 'merge_base=$(git merge-base "origin/$DEFAULT" HEAD)' in script
    assert merge_base < head
    checkout = next(s for s in STEPS if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == "0"


def test_s025_12_a_case_the_pull_request_changed_is_judged_on_its_own() -> None:
    compare = _script("Compare against the default branch (D-37)")
    assert 'git diff --quiet "$merge_base" HEAD -- "evals/$case_path" || changed+=(--changed "$case_path")' in compare
    assert '"${changed[@]}"' in compare
    assert "--tolerance" not in TEXT  # never changed in the pull request job


# S-025-18: a fork's pull request


def test_s025_18_a_fork_fails_first_naming_the_dispatch_command_with_the_head_sha(tmp_path: Path) -> None:
    fork = _step("Refuse a fork's pull request, which runs only by hand (D-16)")
    assert STEPS.index(fork) == 0
    assert fork["if"] == (
        "github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name != github.repository"
    )
    assert fork["env"]["HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert "continue-on-error" not in fork
    code, out, _ = _bash(str(fork["name"]), tmp_path, PR="57", HEAD_SHA=SHA)
    line = FORK_LINE.format(pr=57, sha=SHA)
    assert line == f"evals: a fork's pull request runs only by hand: gh workflow run evals.yml -f pr=57 -f sha={SHA}"
    assert code == 1
    assert out.splitlines() == ["::error::" + line]  # the check's annotation
    assert (tmp_path / "summary").read_text() == line + "\n"


def test_s025_18_after_a_fork_fails_no_case_runs() -> None:
    # a failed step skips every later step whose `if` lacks always() or failure()
    run = _step("Run the suite")
    assert "always()" not in str(run["if"]) and "failure()" not in str(run["if"])
    for step in STEPS:
        if "always()" in str(step.get("if", "")):
            assert "steps.run.outcome != 'skipped'" in str(step["if"]), step.get("name")


def _checkout() -> int:
    [checkout] = [i for i, s in enumerate(STEPS) if str(s.get("uses", "")).startswith("actions/checkout@")]
    return checkout


def _with_token() -> list[int]:
    """The steps that mint an Anthropic token or run with one"""
    found = [i for i, s in enumerate(STEPS) if "OIDC token" in str(s.get("run", "")) or s.get("name") == MINT]
    assert [STEPS[i].get("name") for i in found] == [MINT, "Run the suite"]
    return found


def test_s025_18_a_dispatched_run_checks_out_the_pull_requests_merge_ref() -> None:
    checkout = STEPS[_checkout()]
    assert checkout["with"]["ref"] == "${{ steps.plan.outputs.ref }}"
    assert _index("Choose what this run is") < _checkout()


# S-025-19: a dispatch with pr names the head SHA it is for

PLAN = {"EVENT": "workflow_dispatch", "REF": "refs/heads/main", "DEFAULT": "main", "EVALS_MODEL": "claude-pinned"}


@pytest.mark.parametrize(
    ("env", "named"),
    [
        ({"PR_INPUT": "7"}, "a run with pr needs sha, the head SHA you read: -f pr=7 -f sha=<head SHA>"),
        ({"PR_INPUT": "7", "SHA_INPUT": SHA[:12]}, "sha is the 40 lowercase hexadecimal characters"),
        ({"PR_INPUT": "7", "SHA_INPUT": SHA.upper()}, "sha is the 40 lowercase hexadecimal characters"),
        ({"PR_INPUT": "7", "SHA_INPUT": SHA + "0"}, "sha is the 40 lowercase hexadecimal characters"),
        ({"PR_INPUT": "7", "SHA_INPUT": f"{SHA}\n::warning::x"}, "sha is the 40 lowercase hexadecimal characters"),
        ({"SHA_INPUT": SHA}, "sha pins a pull request's run; dispatch it with -f pr=<N> beside it"),
        ({"SHA_INPUT": SHA, "MODEL_INPUT": "claude-other"}, "sha pins a pull request's run"),
    ],
)
def test_s025_19_a_bad_pr_and_sha_combination_exits_1_naming_the_input(
    tmp_path: Path, env: dict[str, str], named: str
) -> None:
    code, out, outputs = _bash("Choose what this run is", tmp_path, **(PLAN | env))
    assert code == 1
    assert out.startswith(f"::error::evals: {named}")
    assert "::warning::" not in out  # the input's text is never echoed
    assert outputs == {}


def test_s025_19_a_dispatch_with_neither_runs_as_the_baseline(tmp_path: Path) -> None:
    code, _, outputs = _bash("Choose what this run is", tmp_path, **PLAN)
    assert (code, outputs["mode"], outputs["sha"]) == (0, "baseline", "")


def test_s025_19_the_inputs_are_checked_before_any_checkout() -> None:
    assert _index("Choose what this run is") < _checkout()
    assert _env("Choose what this run is")["SHA_INPUT"] == "${{ inputs.sha }}"


# S-025-20: the pull request's head is read before any checkout or secret


def _fake_gh(tmp_path: Path, head: str) -> Path:
    """A directory holding a gh that logs its arguments and answers the pull request's head"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\necho "$*" >> {tmp_path / "gh.log"}\necho {head}\n', encoding="utf-8")
    gh.chmod(0o755)
    return bin_dir


def test_s025_20_the_head_is_read_before_the_checkout_and_every_step_with_the_secret() -> None:
    pin = _index(PIN)
    assert _index("Choose what this run is") < pin < _checkout()
    assert all(pin < i for i in _with_token())
    assert STEPS[pin]["if"] == "steps.plan.outputs.sha != ''"
    env = _env(PIN)
    assert env["GH_TOKEN"] == "${{ github.token }}" and "secrets." not in str(env)
    assert (env["PR"], env["SHA"]) == ("${{ steps.plan.outputs.pr }}", "${{ steps.plan.outputs.sha }}")


def test_s025_20_a_moved_head_runs_no_case_and_exits_1_naming_both(tmp_path: Path) -> None:
    bin_dir = _fake_gh(tmp_path, OTHER)
    path = f"{bin_dir}:{os.environ['PATH']}"
    code, out, _ = _bash(PIN, tmp_path, PATH=path, GH_TOKEN="t", REPO="shipmill/shipmill", PR="57", SHA=SHA)
    line = MOVED.format(pr=57, current=OTHER, sha=SHA)
    assert code == 1
    assert out.splitlines() == ["::error::" + line]
    assert (tmp_path / "summary").read_text() == line + "\n"
    assert (tmp_path / "gh.log").read_text() == "api repos/shipmill/shipmill/pulls/57 --jq .head.sha\n"
    run = _step("Run the suite")  # a failed step skips the run, which has no always()
    assert "always()" not in str(run["if"]) and "failure()" not in str(run["if"])


def test_s025_20_the_head_read_goes_on(tmp_path: Path) -> None:
    bin_dir = _fake_gh(tmp_path, SHA)
    path = f"{bin_dir}:{os.environ['PATH']}"
    code, out, _ = _bash(PIN, tmp_path, PATH=path, GH_TOKEN="t", REPO="shipmill/shipmill", PR="57", SHA=SHA)
    assert (code, out, (tmp_path / "summary").read_text()) == (0, "", "")


# S-025-21: the merge ref's head parent is the SHA read


def _merge_ref(tmp_path: Path) -> tuple[Path, str]:
    """A checkout like refs/pull/<N>/merge: HEAD merges a head commit into the default branch"""
    tree = tmp_path / "tree"
    git = ["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(tree)], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "base"], check=True)
    subprocess.run([*git, "switch", "-q", "-c", "topic"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "the head"], check=True)
    head = subprocess.run([*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run([*git, "switch", "-q", "main"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "main moved"], check=True)
    subprocess.run([*git, "merge", "-q", "--no-ff", "-m", "merge", "topic"], check=True)
    return tree, head


def test_s025_21_the_merge_check_runs_after_the_checkout_and_before_the_secret() -> None:
    merge = _index(MERGE)
    assert merge == _checkout() + 1
    assert all(merge < i for i in _with_token())
    assert STEPS[merge]["if"] == "steps.plan.outputs.sha != ''"
    assert "secrets." not in str(_env(MERGE)) and "token" not in str(_env(MERGE))
    assert "git rev-parse --verify --quiet 'HEAD^2^{commit}'" in _script(MERGE)


def test_s025_21_a_head_parent_that_isnt_sha_exits_1_naming_both(tmp_path: Path) -> None:
    tree, head = _merge_ref(tmp_path)
    code, out, _ = _bash_in(tree, MERGE, tmp_path, {"PR": "57", "SHA": SHA})
    line = MOVED.format(pr=57, current=head, sha=SHA)
    assert code == 1
    assert out.splitlines() == ["::error::" + line]
    assert (tmp_path / "summary").read_text() == line + "\n"


def test_s025_21_a_checkout_without_a_head_parent_exits_1(tmp_path: Path) -> None:
    tree, head = _merge_ref(tmp_path)
    subprocess.run(["git", "-C", str(tree), "checkout", "-q", "--detach", "HEAD^1"], check=True)
    code, out, _ = _bash_in(tree, MERGE, tmp_path, {"PR": "57", "SHA": head})
    assert code == 1
    assert out == "::error::evals: the checkout of refs/pull/57/merge has no head parent, so no case runs\n"


# S-025-22: the run records what it measured


def test_s025_22_the_summary_starts_with_what_the_run_measured(tmp_path: Path) -> None:
    tree, head = _merge_ref(tmp_path)
    code, out, _ = _bash_in(tree, MERGE, tmp_path, {"PR": "57", "SHA": head})
    assert (code, out) == (0, "")
    assert (tmp_path / "summary").read_text() == f"evals: measured {head} of #57\n"
    # no step before it writes the summary on a dispatched run that goes on: the fork refusal
    # runs only on pull_request, and the head read writes only when it exits 1
    before = [str(s.get("name")) for s in STEPS[: _index(MERGE)] if "GITHUB_STEP_SUMMARY" in str(s.get("run", ""))]
    assert before == ["Refuse a fork's pull request, which runs only by hand (D-16)", PIN]
    assert "pull_request" in str(_step(before[0])["if"])
    pin = _script(PIN)
    assert pin.index('echo "$line" >>"$GITHUB_STEP_SUMMARY"') > pin.index('if [ "$current" != "$SHA" ]; then')


def test_s025_22_meta_json_holds_the_pr_and_the_head(tmp_path: Path) -> None:
    script = _script("Run the suite")
    found = re.search(r"'(\{model: \$model.*?\})' >\"\$out/meta.json\"", script, re.S)
    assert found is not None
    env = _env("Run the suite")
    assert (env["PR"], env["HEAD_SHA"]) == ("${{ steps.plan.outputs.pr }}", "${{ steps.plan.outputs.sha }}")
    assert '--arg pr "$PR" --arg head "$HEAD_SHA"' in script

    def meta(pr: str, head: str) -> dict[str, object]:
        args = ["jq", "-n", "--arg", "model", "m", "--arg", "commit", "c", "--arg", "claude", "v"]
        args += ["--argjson", "code", "0", "--arg", "pr", pr, "--arg", "head", head, found[1]]
        result: dict[str, object] = json.loads(subprocess.run(args, check=True, capture_output=True, text=True).stdout)
        return result

    assert meta("57", SHA) == {"model": "m", "commit": "c", "claude": "v", "exit": 0, "pr": 57, "head": SHA}
    assert meta("", "") == {"model": "m", "commit": "c", "claude": "v", "exit": 0, "pr": None, "head": None}
    upload = _step("Upload the result and the report")
    assert "${{ runner.temp }}/evals/head/" in upload["with"]["path"].split("\n")  # meta.json is in it


# S-025-16: the gate turns on with the first suite


def test_s025_16_the_gate_is_read_before_the_run() -> None:
    gate = _script("Check the suite, and whether the gate is on (S-025-16)")
    assert "uv run shipmill evals check --gate" in gate
    assert 'echo "on=true"' in gate and 'echo "on=false"' in gate
    assert _index("Check the suite, and whether the gate is on (S-025-16)") < _index(MINT)
    assert _index(MINT) < _index("Run the suite")


def test_s025_16_while_the_gate_is_off_the_pull_request_job_reports_and_exits_0() -> None:
    run = _step("Run the suite")
    assert run["continue-on-error"] == "${{ steps.plan.outputs.mode == 'pr' && steps.gate.outputs.on != 'true' }}"
    compare = _script("Compare against the default branch (D-37)")
    # the comparison is written to the summary before the exit is chosen
    assert compare.index('tee -a "$GITHUB_STEP_SUMMARY"') < compare.index(
        'if [ "$GATE_ON" = true ]; then\n  exit "$code"'
    )
    assert compare.rstrip().endswith('so the pull request job exits 0"')


# S-025-24, S-025-25, S-025-26: the Anthropic token comes from Workload Identity Federation


def _fake_curl(tmp_path: Path, oidc: str, status: str) -> str:
    """A PATH whose curl answers GitHub's OIDC request with oidc and the exchange with status,
    logging each call's arguments and the exchange's body"""
    bin_dir = tmp_path / "curlbin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    log = tmp_path / "curl.log"
    curl.write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> {log}\n'
        'case "$*" in\n'
        f'  *oauth/token*) cat > {tmp_path / "body.json"}; printf %s "{status}";;\n'
        f"  *) {oidc};;\n"
        "esac\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return f"{bin_dir}:{os.environ['PATH']}"


def _mint(tmp_path: Path, mode: str = "pr", gate: str = "false", **env: str) -> tuple[int, str, dict[str, str]]:
    request = {"ACTIONS_ID_TOKEN_REQUEST_URL": "https://gh.test/oidc?x=1", "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "rt"}
    ids = {"ANTHROPIC_FEDERATION_RULE_ID": "fdrl_x", "ANTHROPIC_ORGANIZATION_ID": "org", "RUNNER_TEMP": str(tmp_path)}
    ids["ANTHROPIC_SERVICE_ACCOUNT_ID"] = "svac_x"
    return _bash(MINT, tmp_path, MODE=mode, GATE_ON=gate, **(request | ids | env))


@pytest.mark.parametrize(
    ("mode", "gate", "code"),
    [
        ("pr", "false", 0),  # today: no token and a short suite never block a skill pull request
        ("pr", "true", 1),
        ("baseline", "false", 1),
        ("model", "false", 1),
    ],
)
def test_s025_24_no_token_fails_unless_the_gate_is_off(tmp_path: Path, mode: str, gate: str, code: int) -> None:
    got, out, outputs = _mint(tmp_path, mode, gate, PATH=_fake_curl(tmp_path, 'echo \'{"value": "jwt"}\'', "401"))
    line = NO_TOKEN.format(reason="the exchange with rule fdrl_x got HTTP 401")
    assert (got, outputs) == (code, {"ok": "false"})
    level = "warning" if code == 0 else "error"
    assert out.splitlines()[-1].startswith(f"::{level}::{line}")
    assert (tmp_path / "summary").read_text() == line + "\n"
    later = [s for s in STEPS[_index(MINT) + 1 :] if "uses" not in s]
    for step in later:  # with no token every later step is skipped
        assert "steps.token.outputs.ok == 'true'" in str(step.get("if", "")) or "steps.run.outcome" in str(
            step.get("if", "")
        ), step.get("name")


@pytest.mark.parametrize(
    ("oidc", "env", "reason"),
    [
        ("exit 7", {}, "the GitHub OIDC token request failed"),
        ("echo '{}'", {}, "the GitHub OIDC token request failed"),
        ("echo x", {"ACTIONS_ID_TOKEN_REQUEST_URL": ""}, "GitHub gave the job no OIDC token request"),
    ],
)
def test_s025_24_the_line_names_what_failed(tmp_path: Path, oidc: str, env: dict[str, str], reason: str) -> None:
    got, _, outputs = _mint(tmp_path, "baseline", PATH=_fake_curl(tmp_path, oidc, "200"), **env)
    assert (got, outputs) == (1, {"ok": "false"})
    assert (tmp_path / "summary").read_text() == NO_TOKEN.format(reason=reason) + "\n"
    assert not (tmp_path / "body.json").exists()  # no exchange without a token


def test_s025_26_one_exchange_before_the_run_then_the_run_goes_on(tmp_path: Path) -> None:
    got, out, outputs = _mint(tmp_path, "baseline", PATH=_fake_curl(tmp_path, 'echo \'{"value": "jwt"}\'', "200"))
    assert (got, outputs) == (0, {"ok": "true", "dir": f"{tmp_path}/evals-identity"})
    assert out == "::add-mask::jwt\n"
    calls = (tmp_path / "curl.log").read_text().splitlines()
    assert (
        calls[0] == "-sS --fail -H Authorization: Bearer rt https://gh.test/oidc?x=1&audience=https://api.anthropic.com"
    )
    assert "-X POST https://api.anthropic.com/v1/oauth/token" in calls[1] and len(calls) == 2
    assert json.loads((tmp_path / "body.json").read_text()) == {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": "jwt",
        "federation_rule_id": "fdrl_x",
        "organization_id": "org",
        "service_account_id": "svac_x",
    }
    assert (tmp_path / "summary").read_text() == ""


def test_s025_24_a_run_stopped_on_auth_compares_nothing() -> None:
    script = _script("Run the suite")
    assert ".partialReason" in script and "= auth_failed ]" in script
    assert 'auth_failed "claude plugin eval stopped with partialReason auth_failed"' in script
    assert NO_TOKEN.format(reason="$1") in script and 'echo "auth=failed"' in script
    assert "steps.run.outputs.auth != 'failed'" in str(_step("Compare against the default branch (D-37)")["if"])


def test_s025_25_no_api_key_and_the_job_may_request_an_oidc_token() -> None:
    assert "secrets.ANTHROPIC_API_KEY" not in TEXT and "secrets." not in TEXT
    assert JOB["permissions"]["id-token"] == "write"
    assert "id-token" not in DOC["permissions"]  # the job's, not the workflow's


def test_s025_26_the_rule_follows_the_event_and_the_ids_are_plain_env() -> None:
    env = DOC["env"]
    rule = f"${{{{ github.event_name == 'pull_request' && '{PR_RULE}' || '{MAIN_RULE}' }}}}"
    assert env["ANTHROPIC_FEDERATION_RULE_ID"] == rule
    assert env["ANTHROPIC_ORGANIZATION_ID"] == "e3767508-33b1-4a4e-82bb-dedd54566ab5"
    assert env["ANTHROPIC_SERVICE_ACCOUNT_ID"] == "svac_01QLwU4cCRmN9TW8ZW3NfggY"
    # each rule covers one workspace, so no step sets one
    assert all("ANTHROPIC_WORKSPACE_ID" not in str(e) for e in [env, *(s.get("env", {}) for s in STEPS)])


def test_s025_26_the_identity_token_stays_out_of_the_checkout_and_fresh() -> None:
    assert 'dir="$RUNNER_TEMP/evals-identity"' in _script(MINT)
    assert _env("Run the suite")["TOKEN_DIR"] == "${{ steps.token.outputs.dir }}"
    script = _script("Run the suite")
    assert 'token_file="$TOKEN_DIR/github-oidc.jwt"' in script
    # a fresh token lands before the first case and every 2 minutes while the run lasts
    assert script.index("fetch_token || auth_failed") < script.index('suite "$GITHUB_WORKSPACE"')
    assert "while sleep 120; do" in script and 'trap \'kill "$refresher"' in script


def test_s025_26_every_command_that_runs_the_checkouts_code_drops_the_oidc_request() -> None:
    for step in STEPS:
        run = str(step.get("run", ""))
        if "uv " in run:
            assert run.startswith(f"unset {' '.join(OIDC)}\n"), step.get("name")


# S-025-31, S-025-32: a run explains each case that did not pass, and keeps its traces (D-72)

EXPLAIN = "Explain the cases that did not pass (S-025-31, S-025-32)"


def test_s025_32_the_breakdown_runs_after_the_suite_and_before_the_upload() -> None:
    step = _step(EXPLAIN)
    assert step["if"] == "always() && steps.run.outcome != 'skipped'"
    # a failed breakdown never skips the steps after it: the baseline, its upload, the compare
    assert step["continue-on-error"] == "true"  # the file's YAML loader keeps scalars as text
    assert _index("Run the suite") < _index(EXPLAIN) < _index("Upload the result and the report")
    # the traces land in the head's directory, which the evals-result artifact uploads
    upload = _step("Upload the result and the report")
    assert upload["with"]["name"] == "evals-result"
    assert "${{ runner.temp }}/evals/head/" in upload["with"]["path"].split("\n")


def test_s025_32_the_eval_run_keeps_its_files_under_the_jobs_temp() -> None:
    # #954: with TMPDIR left at /tmp the runner's claude-eval-* directories were gone when the
    # explain step ran, so no trace and no gh log reached the artifact; the run's TMPDIR is a
    # directory under $RUNNER_TEMP, made before the run, and the explain step reads that one
    run = _script("Run the suite")
    assert 'mkdir -p "$RUNNER_TEMP/evals-tmp"' in run
    assert run.index('mkdir -p "$RUNNER_TEMP/evals-tmp"') < run.index("claude plugin eval")
    assert re.search(r'-u ANTHROPIC_AUTH_TOKEN \\\s+TMPDIR="\$RUNNER_TEMP/evals-tmp" \\\s+ANTHROPIC_', _command())
    explain = _script(EXPLAIN)
    assert 'find "$RUNNER_TEMP/evals-tmp" ' in explain
    assert "${TMPDIR" not in explain and "/tmp" not in explain


def test_s025_32_traces_and_gh_logs_are_copied_and_the_breakdown_reaches_the_summary(tmp_path: Path) -> None:
    # the runner's layout under the run's TMPDIR: <tmp>/claude-eval-*/out/trace.jsonl, and each
    # workspace's .eval/ beside it
    tree, temp, scratch, bin_dir = tmp_path / "tree", tmp_path / "temp", tmp_path / "scratch", tmp_path / "bin"
    kept = temp / "evals-tmp"
    for d in (tree / "evals" / "s" / "c", kept, scratch, bin_dir):
        d.mkdir(parents=True)
    secret = tmp_path / "evals-identity" / "github-oidc.jwt"
    secret.parent.mkdir()
    secret.write_text("a token\n")
    trace = kept / "claude-eval-a1" / "out" / "trace.jsonl"
    trace.parent.mkdir(parents=True)
    trace.write_text('{"type": "assistant"}\n')
    linked = kept / "claude-eval-a2" / "out" / "trace.jsonl"
    linked.parent.mkdir(parents=True)
    linked.symlink_to(secret)
    head = temp / "evals" / "head"
    head.mkdir(parents=True)
    runs = [{"error": None, "tracePath": str(trace)}, {"error": None, "tracePath": str(linked)}, {"error": "x"}]
    cases = [
        {"name": "c", "dir": "evals/s/c", "arms": {"with": runs}},
        {"name": "up", "dir": "evals/../up", "arms": {"with": [{"tracePath": str(trace)}]}},
    ]
    (head / "aggregate-result.json").write_text(json.dumps({"schemaVersion": 1, "partial": False, "cases": cases}))

    def workspace(top: Path, name: str, case_dir: str, log: str | None) -> Path:
        marker = top / name / "work" / ".eval" / "case"
        marker.parent.mkdir(parents=True)
        marker.write_text(case_dir + "\n")
        if log is not None:
            (marker.parent / "gh.jsonl").write_text(log)
        return marker.parent / "gh.jsonl"

    case_dir = f"{tree.resolve()}/evals/s/c"
    workspace(kept, "claude-eval-a1", case_dir, '{"kind": "miss", "args": ["pr", "checks", "41"]}\n')
    workspace(kept, "claude-eval-b1", "/elsewhere/evals/s/c", '{"kind": "read", "args": []}\n')  # another tree's
    workspace(kept, "claude-eval-a3", case_dir, None).symlink_to(secret)  # a link a session left
    workspace(scratch, "claude-eval-z1", case_dir, '{"kind": "read", "args": ["elsewhere"]}\n')  # not the run's
    (bin_dir / "uv").write_text(f'#!/bin/sh\necho "$*" >> {tmp_path / "uv.log"}\necho "### evals: stub"\n')
    (bin_dir / "uv").chmod(0o755)
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "RUNNER_TEMP": str(temp), "GITHUB_WORKSPACE": str(tree)}
    code, out, _ = _bash(EXPLAIN, tmp_path, TMPDIR=str(scratch), **env)
    assert (code, out) == (0, "")
    copied = sorted(p.relative_to(head / "traces").as_posix() for p in (head / "traces").rglob("*") if p.is_file())
    assert copied == ["s/c/gh-1.jsonl", "s/c/run-1.jsonl"]
    assert (head / "traces" / "s" / "c" / "gh-1.jsonl").read_text().startswith('{"kind": "miss"')
    assert "a token" not in "".join(p.read_text() for p in (head / "traces").rglob("*") if p.is_file())
    result = head / "aggregate-result.json"
    assert (tmp_path / "uv.log").read_text() == f"run shipmill evals explain --result {result} --traces {head}/traces\n"
    assert (tmp_path / "summary").read_text() == "\n### evals: stub\n"


def test_s025_32_a_run_with_no_result_explains_nothing(tmp_path: Path) -> None:
    temp = tmp_path / "temp"
    temp.mkdir()
    env = {"RUNNER_TEMP": str(temp), "GITHUB_WORKSPACE": str(tmp_path), "TMPDIR": str(tmp_path / "none")}
    code, out, _ = _bash(EXPLAIN, tmp_path, **env)
    assert (code, out, (tmp_path / "summary").read_text()) == (0, "", "")
