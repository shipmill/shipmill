"""Spec 025, D-72: `shipmill evals explain` says why each case of a run did not pass (#950)"""

import json
import re
import shutil
from pathlib import Path

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "evals" / "explain"
RESULT = FIXTURE / "aggregate-result.json"
TRACES = FIXTURE / "traces"


def _explain(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    assert main(["evals", "explain", *args]) == 0
    return capsys.readouterr().out


def _entry(out: str, case: str) -> str:
    """The case's entry, from its heading to the next one"""
    start = out.index(f"#### {case}: ")
    end = out.find("\n#### ", start + 1)
    return out[start : end if end != -1 else len(out)]


def test_s025_31_one_entry_per_case_that_did_not_pass_with_its_verdict(capsys: pytest.CaptureFixture[str]) -> None:
    out = _explain(capsys, "--result", str(RESULT), "--traces", str(TRACES))
    assert out.startswith("### evals: why 3 of 4 cases did not pass\n")
    assert "product-intake/steady" not in out  # it passed every run
    headings = [line for line in out.splitlines() if line.startswith("#### ")]
    assert headings == [
        "#### github-issue-triage/overloaded: harness, 2/3 runs passed",
        "#### github-pr-triage/fixture-drift: harness, 0/1 runs passed",
        "#### github-issue-resolve/wrong-verdict: agent, 1/3 runs passed",
    ]


def test_s025_31_an_api_error_is_the_harness(capsys: pytest.CaptureFixture[str]) -> None:
    entry = _entry(_explain(capsys, "--result", str(RESULT), "--traces", str(TRACES)), "github-issue-triage/overloaded")
    assert "- Run 1: **harness**, an API error. 0 turns, 0.00 USD, 2 s\n" in entry
    assert "  - error: API error: 529 overloaded_error\n" in entry
    assert "  - trace: none in --traces for this run\n" in entry  # a missing trace is a line, not a failure
    assert "Run 2" not in entry and "Run 3" not in entry  # passing runs are not listed


def test_s025_31_a_miss_in_gh_jsonl_is_the_harness(capsys: pytest.CaptureFixture[str]) -> None:
    entry = _entry(_explain(capsys, "--result", str(RESULT), "--traces", str(TRACES)), "github-pr-triage/fixture-drift")
    assert "- Run 1: **harness**, a gh read with no recording (a miss in .eval/gh.jsonl). 14 turns, 1.12 USD" in entry
    assert '  - grader no-miss failed: found "kind": "miss" in .eval/gh.jsonl\n' in entry
    assert "grader merged" not in entry  # a grader that passed is not listed
    assert "  - last message: The checks could not be read, so I merged on the rollup.\n" in entry
    assert "- gh.jsonl: 1 miss in 1 log, the first `gh pr checks 41 --json name,state`\n" in entry


def test_s025_31_a_session_that_ran_and_did_the_wrong_thing_is_the_agent(capsys: pytest.CaptureFixture[str]) -> None:
    entry = _entry(
        _explain(capsys, "--result", str(RESULT), "--traces", str(TRACES)), "github-issue-resolve/wrong-verdict"
    )
    assert "- Run 1: **agent**, the session ran and graders failed: verdict. 12 turns, 0.93 USD, 214 s\n" in entry
    assert "  - grader verdict failed: no match for Triage: \\*\\*feature\\*\\*\n" in entry
    assert "  - grader tone failed (not scored): judge votes: FAIL FAIL PASS\n" in entry
    # the last assistant text of the trace, on one line
    assert "  - last message: Triage: **implement**. The fix is small, so I implement it.\n" in entry
    assert "- Run 2: **agent**, the session ran and stopped: max turns reached. 5 turns, 0.31 USD, 77 s\n" in entry
    assert "  - error: max turns reached\n" in entry
    assert "- gh.jsonl: no log in --traces\n" in entry


def test_s025_31_without_traces_it_reads_each_runs_trace_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = json.loads(RESULT.read_text(encoding="utf-8"))
    trace = tmp_path / "c1" / "trace.jsonl"
    trace.parent.mkdir()
    shutil.copy(TRACES / "github-issue-resolve" / "wrong-verdict" / "run-1.jsonl", trace)
    runs = raw["cases"][2]["arms"]["with"]
    runs[0]["tracePath"] = str(trace)
    runs[1]["tracePath"] = str(tmp_path / "gone" / "trace.jsonl")
    result = tmp_path / "aggregate-result.json"
    result.write_text(json.dumps(raw), encoding="utf-8")
    entry = _entry(_explain(capsys, "--result", str(result)), "github-issue-resolve/wrong-verdict")
    assert "  - last message: Triage: **implement**. The fix is small, so I implement it.\n" in entry
    assert f"  - trace: {tmp_path / 'gone' / 'trace.jsonl'} is missing\n" in entry
    assert "gh.jsonl" not in entry  # only --traces holds the case's logs


def test_s025_31_a_case_it_cannot_place_reads_agent_with_the_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run: dict[str, object] = {"error": None, "aborted": True, "turns": 3, "graders": []}
    case = {"name": "c", "dir": "evals/s/c", "runsPerCase": 1, "arms": {"with": [run]}}
    result = tmp_path / "aggregate-result.json"
    result.write_text(json.dumps({"schemaVersion": 1, "partial": False, "cases": [case]}), encoding="utf-8")
    out = _explain(capsys, "--result", str(result))
    assert "- Run 1: **agent**, it fell through every harness rule: aborted, with no error and no failed grader." in out
    assert "  - trace: the run names no tracePath\n" in out


def test_s025_31_a_pattern_the_grader_read_and_did_not_find_is_the_agent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # the runner's regex grader on a file it read: the session never wrote what it looks for
    grader = {"name": "posts-the-verdict", "passed": False, "explanation": "pattern not found in file .eval/gh.jsonl"}
    run = {"error": None, "turns": 8, "graders": [grader]}
    case = {"name": "c", "dir": "evals/s/c", "runsPerCase": 1, "arms": {"with": [run]}}
    result = tmp_path / "aggregate-result.json"
    result.write_text(json.dumps({"schemaVersion": 1, "partial": False, "cases": [case]}), encoding="utf-8")
    out = _explain(capsys, "--result", str(result))
    assert "- Run 1: **agent**, the session ran and graders failed: posts-the-verdict." in out


def test_s025_31_every_case_passed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run = {"error": None, "graders": [{"name": "v", "passed": True}]}
    case = {"name": "c", "dir": "evals/s/c", "runsPerCase": 1, "arms": {"with": [run]}}
    result = tmp_path / "aggregate-result.json"
    result.write_text(json.dumps({"schemaVersion": 1, "partial": False, "cases": [case]}), encoding="utf-8")
    assert _explain(capsys, "--result", str(result)) == "### evals: every case passed (1 of 1)\n"


def test_s025_31_a_case_the_budget_stopped_before_is_named(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run = {"error": None, "graders": [{"name": "v", "passed": True}]}
    cases = [
        {"name": "c", "dir": "evals/s/c", "runsPerCase": 1, "arms": {"with": [run]}},
        {"name": "d", "dir": "evals/s/d", "runsPerCase": 1, "arms": {"with": []}},
    ]
    raw = {"schemaVersion": 1, "partial": True, "partialReason": "cost_ceiling", "cases": cases}
    result = tmp_path / "aggregate-result.json"
    result.write_text(json.dumps(raw), encoding="utf-8")
    out = _explain(capsys, "--result", str(result))
    assert out.splitlines()[-1] == "Not run, the run stopped first (cost_ceiling): s/d"


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("[]", "the result is a JSON object"),
        ('{"schemaVersion": 2, "partial": false, "cases": []}', "schemaVersion is 1"),
        ('{"schemaVersion": 1, "partial": false, "cases": [{"name": "c", "dir": "x"}]}', "dir is the case's directory"),
        (
            '{"schemaVersion": 1, "partial": false, "cases": [{"name": "c", "dir": "evals/s/c", "runsPerCase": 1,'
            ' "arms": {"with": [{"error": null, "turns": "many", "graders": []}]}}]}',
            "turns is a number",
        ),
    ],
)
def test_s025_31_a_malformed_result_is_bad_input_naming_the_file_and_the_fault(
    tmp_path: Path, text: str, named: str
) -> None:
    # ReleaseError: shipmill exits 2 with it
    result = tmp_path / "aggregate-result.json"
    result.write_text(text, encoding="utf-8")
    with pytest.raises(ReleaseError, match=f"aggregate-result.json: .*{re.escape(named)}"):
        main(["evals", "explain", "--result", str(result)])


def test_s025_31_a_missing_result_is_bad_input(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match=r"missing\.json: no such file"):
        main(["evals", "explain", "--result", str(tmp_path / "missing.json")])
