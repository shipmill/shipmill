"""Spec 025: `.github/workflows/evals.yml` runs the suite and gates a pull request on it (D-37).

The workflow is read with the eval suite's own strict YAML reader, and its small shell steps
(choosing the run, refusing a fork, the API key) run here as bash with the env GitHub gives
them, so their exits and lines are proved, not only their text."""

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
FORK_LINE = "evals: a fork's pull request runs only by hand: gh workflow run evals.yml -f pr={pr}"


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
    output, summary = tmp_path / "output", tmp_path / "summary"
    output.write_text("")
    summary.write_text("")
    full = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary)}
    proc = subprocess.run(
        ["bash", "-e", "-c", _script(name)], env=full | env, capture_output=True, text=True, check=False
    )
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    return proc.returncode, proc.stdout, outputs


def _matches(pattern: str, path: str) -> bool:
    """GitHub's path filter glob: `**` crosses directories, `*` does not"""
    regex = re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.fullmatch(regex, path) is not None


# S-025-10: the triggers


def test_s025_10_runs_on_pull_request_schedule_and_dispatch_only() -> None:
    on = DOC["on"]
    assert isinstance(on, dict)
    assert sorted(on) == ["pull_request", "schedule", "workflow_dispatch"]
    pull = on["pull_request"]
    assert pull == {"paths": ["skills/**", ".claude-plugin/**", "evals/**", "src/shipmill/gate.py"]}


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
def test_s025_10_a_pull_request_runs_only_when_it_touches_the_agents(path: str, runs: bool) -> None:
    paths = DOC["on"]["pull_request"]["paths"]
    assert any(_matches(p, path) for p in paths) is runs


def test_s025_10_schedule_is_weekly() -> None:
    schedule = DOC["on"]["schedule"]
    assert isinstance(schedule, list) and len(schedule) == 1
    minute, hour, day, month, weekday = schedule[0]["cron"].split()
    assert (day, month) == ("*", "*")
    assert re.fullmatch(r"[0-6]", weekday) and minute.isdigit() and hour.isdigit()


def test_s025_10_dispatch_takes_a_pr_and_a_model() -> None:
    inputs = DOC["on"]["workflow_dispatch"]["inputs"]
    assert sorted(inputs) == ["model", "pr"]
    assert all(i["type"] == "string" and i["default"] == "" for i in inputs.values())


@pytest.mark.parametrize(
    ("env", "outputs"),
    [
        ({"EVENT": "pull_request", "PR_EVENT": "41"}, {"mode": "pr", "pr": "41", "ref": ""}),
        ({"EVENT": "schedule"}, {"mode": "baseline", "pr": "", "ref": ""}),
        ({"EVENT": "workflow_dispatch"}, {"mode": "baseline", "pr": "", "ref": ""}),
        ({"EVENT": "workflow_dispatch", "PR_INPUT": "7"}, {"mode": "pr", "pr": "7", "ref": "refs/pull/7/merge"}),
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
    for flag in ("--ablation none", "--no-publish", '--model "$MODEL"', "--runs 3", "-j 4", "--max-cost-usd 15"):
        assert re.search(rf"(?<!\S){re.escape(flag)}(?!\S)", command), flag
    assert "--trust-plugin" in command and "--scaffold" in command and "--json" in command


def test_s025_11_the_model_is_the_gate_sessions_written_once() -> None:
    pinned = DOC["env"]["EVALS_MODEL"]
    assert isinstance(pinned, str) and pinned.startswith("claude-")
    assert TEXT.count(pinned) == 1
    assert _env("Run the suite")["MODEL"] == "${{ steps.plan.outputs.model }}"
    assert "model=${MODEL_INPUT:-$EVALS_MODEL}" in _script("Choose what this run is")


def test_s025_11_the_stub_is_first_on_path_and_no_token_reaches_the_run() -> None:
    command = _command()
    assert 'env -u GH_TOKEN -u GITHUB_TOKEN PATH="$tree/evals/bin:$PATH"' in command
    env = _env("Run the suite")
    assert env["ANTHROPIC_API_KEY"] == "${{ secrets.ANTHROPIC_API_KEY }}"
    assert not {"GH_TOKEN", "GITHUB_TOKEN"} & set(env)
    assert all("github.token" not in str(v) and "GITHUB_TOKEN" not in str(v) for v in env.values())
    # only the baseline lookup holds a token; the checkout the cases clone keeps none
    holders = [s.get("name") for s in STEPS if re.search(r"github\.token|GITHUB_TOKEN|GH_TOKEN", str(s.get("env", "")))]
    assert holders == ["Find the default branch's baseline (S-025-12)"]
    checkout = next(s for s in STEPS if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] == "false"
    assert JOB["permissions"] == {"contents": "read", "actions": "read"}
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
    assert "{model: $model, commit: $commit, claude: $claude, exit: $code}" in _script("Run the suite")


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


# S-025-13: a fork's pull request


def test_s025_13_a_fork_fails_first_naming_the_dispatch_command(tmp_path: Path) -> None:
    fork = _step("Refuse a fork's pull request, which runs only by hand (D-16)")
    assert STEPS.index(fork) == 0
    assert fork["if"] == (
        "github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name != github.repository"
    )
    assert "continue-on-error" not in fork
    code, out, _ = _bash(str(fork["name"]), tmp_path, PR="57")
    assert code == 1
    assert out.splitlines() == ["::error::" + FORK_LINE.format(pr=57)]  # the check's annotation
    assert (tmp_path / "summary").read_text() == FORK_LINE.format(pr=57) + "\n"


def test_s025_13_after_a_fork_fails_no_case_runs() -> None:
    # a failed step skips every later step whose `if` lacks always() or failure()
    run = _step("Run the suite")
    assert "always()" not in str(run["if"]) and "failure()" not in str(run["if"])
    for step in STEPS:
        if "always()" in str(step.get("if", "")):
            assert "steps.run.outcome != 'skipped'" in str(step["if"]), step.get("name")


def test_s025_13_a_dispatched_run_checks_out_the_pull_request() -> None:
    checkout = next(s for s in STEPS if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ steps.plan.outputs.ref }}"
    assert _index("Choose what this run is") < STEPS.index(checkout)


# S-025-16: the gate turns on with the first suite


def test_s025_16_the_gate_is_read_before_the_run() -> None:
    gate = _script("Check the suite, and whether the gate is on (S-025-16)")
    assert "uv run shipmill evals check --gate" in gate
    assert 'echo "on=true"' in gate and 'echo "on=false"' in gate
    assert _index("Check the suite, and whether the gate is on (S-025-16)") < _index("Check the API key")
    assert _index("Check the API key") < _index("Run the suite")


def test_s025_16_while_the_gate_is_off_the_pull_request_job_reports_and_exits_0() -> None:
    run = _step("Run the suite")
    assert run["continue-on-error"] == "${{ steps.plan.outputs.mode == 'pr' && steps.gate.outputs.on != 'true' }}"
    compare = _script("Compare against the default branch (D-37)")
    # the comparison is written to the summary before the exit is chosen
    assert compare.index('tee -a "$GITHUB_STEP_SUMMARY"') < compare.index(
        'if [ "$GATE_ON" = true ]; then\n  exit "$code"'
    )
    assert compare.rstrip().endswith('so the pull request job exits 0"')


@pytest.mark.parametrize(
    ("mode", "gate", "code"),
    [
        ("pr", "false", 0),  # today: no key and a short suite never block a skill pull request
        ("pr", "true", 1),
        ("baseline", "false", 1),
        ("model", "false", 1),
    ],
)
def test_s025_16_a_missing_key_fails_unless_the_gate_is_off(tmp_path: Path, mode: str, gate: str, code: int) -> None:
    got, out, outputs = _bash("Check the API key", tmp_path, KEY_SET="false", MODE=mode, GATE_ON=gate)
    assert (got, outputs) == (code, {"set": "false"})
    level = "warning" if code == 0 else "error"
    assert out.startswith(f"::{level}::evals: the repository secret ANTHROPIC_API_KEY is not set, so no case ran")
    later = [s for s in STEPS[_index("Check the API key") + 1 :] if "uses" not in s]
    for step in later:  # with no key every later step is skipped
        assert "steps.key.outputs.set == 'true'" in str(step.get("if", "")) or "steps.run.outcome" in str(
            step.get("if", "")
        ), step.get("name")


def test_s025_16_with_the_key_the_run_goes_on(tmp_path: Path) -> None:
    assert _bash("Check the API key", tmp_path, KEY_SET="true", MODE="pr", GATE_ON="false") == (0, "", {"set": "true"})
