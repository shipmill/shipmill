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


def _explain(capsys: pytest.CaptureFixture[str], *args: str, repo: Path = FIXTURE) -> str:
    """explain's output; the suite the cases' max_turns and graders are read from is repo's"""
    assert main(["evals", "explain", "--repo", str(repo), *args]) == 0
    return capsys.readouterr().out


def _case(root: Path, case: str, max_turns: int = 30, graders: str | None = None) -> None:
    """A case of a suite under root, with its max_turns and, when given, case.yaml's graders"""
    folder = root / "evals" / case
    folder.mkdir(parents=True)
    (folder / "prompt.md").write_text(f"---\nname: c\nmax_turns: {max_turns}\n---\n\nDo it.\n", encoding="utf-8")
    if graders is not None:
        (folder / "case.yaml").write_text(f"name: c\ngraders:\n{graders}", encoding="utf-8")


def _result(root: Path, *runs: dict[str, object]) -> Path:
    case = {"name": "c", "dir": "evals/s/c", "runsPerCase": len(runs), "arms": {"with": list(runs)}}
    result = root / "aggregate-result.json"
    result.write_text(json.dumps({"schemaVersion": 1, "partial": False, "cases": [case]}), encoding="utf-8")
    return result


def _entry(out: str, case: str) -> str:
    """The case's entry, from its heading to the next one"""
    start = out.index(f"#### {case}: ")
    end = out.find("\n#### ", start + 1)
    return out[start : end if end != -1 else len(out)]


def test_s025_31_one_entry_per_case_that_did_not_pass_with_its_verdict(capsys: pytest.CaptureFixture[str]) -> None:
    out = _explain(capsys, "--result", str(RESULT), "--traces", str(TRACES))
    assert out.startswith("### evals: why 4 of 5 cases did not pass\n")
    assert "product-intake/steady" not in out  # it passed every run
    headings = [line for line in out.splitlines() if line.startswith("#### ")]
    assert headings == [
        "#### github-issue-triage/overloaded: harness, 2/3 runs passed",
        "#### github-pr-triage/fixture-drift: harness, 0/1 runs passed",
        "#### github-issue-resolve/wrong-verdict: agent, 1/3 runs passed",
        "#### github-issue-triage/stopped-early: harness, 0/2 runs passed",
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


def test_s025_31_a_session_that_stopped_early_with_no_gh_write_is_the_harness(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # #954: 4 and 3 of the case's 30 turns, its gh logs hold reads only, and its graders
    # read only .eval/gh.jsonl: the session stopped on something at the start
    entry = _entry(
        _explain(capsys, "--result", str(RESULT), "--traces", str(TRACES)), "github-issue-triage/stopped-early"
    )
    assert "- Run 1: **harness**, the session stopped early after 4 turns. 4 turns, 0.15 USD, 21 s\n" in entry
    assert "  - grader posts-the-verdict failed: pattern not found in file .eval/gh.jsonl\n" in entry
    assert "  - last message: I can't run uvx here: the tool call was denied, so I stop.\n" in entry
    assert "- Run 2: **harness**, the session stopped early after 3 turns. 3 turns, 0.14 USD, 19 s\n" in entry
    assert "  - trace: none in --traces for this run\n" in entry
    assert "- gh.jsonl: 0 misses in 2 logs\n" in entry


def _stopped(tmp_path: Path, turns: int, log: str, graders: str | None = None, trace: str | None = None) -> str:
    """The result of one failed run of a case of 30 turns, with its gh log and its trace"""
    _case(tmp_path, "s/c", 30, graders)
    traces = tmp_path / "traces" / "s" / "c"
    traces.mkdir(parents=True)
    (traces / "gh-1.jsonl").write_text(log, encoding="utf-8")
    if trace is not None:
        (traces / "run-1.jsonl").write_text(trace, encoding="utf-8")
    grader = {"name": "posts", "passed": False, "explanation": "pattern not found in file .eval/gh.jsonl"}
    return str(_result(tmp_path, {"error": None, "turns": turns, "graders": [grader]}))


@pytest.mark.parametrize(
    ("turns", "log", "verdict"),
    [
        (
            7,
            '{"kind": "read", "args": ["issue", "view", "1"]}\n',
            "**harness**, the session stopped early after 7 turns",
        ),
        # a quarter of 30 is 7.5: a run past it used its turns
        (8, '{"kind": "read", "args": ["issue", "view", "1"]}\n', "**agent**, the session ran and graders failed"),
        # a run that wrote to gh did its work, however few its turns
        (3, '{"kind": "write", "via": "shipmill", "args": ["issue", "comment", "1"]}\n', "**agent**, the session ran"),
    ],
)
def test_s025_31_a_run_that_used_its_turns_or_wrote_to_gh_is_the_agent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], turns: int, log: str, verdict: str
) -> None:
    result = _stopped(tmp_path, turns, log)
    out = _explain(capsys, "--result", result, "--traces", str(tmp_path / "traces"), repo=tmp_path)
    assert f"- Run 1: {verdict}" in out


def test_s025_31_an_early_stop_needs_the_gh_logs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # without --traces, or with no log of the case, a write can't be ruled out
    _case(tmp_path, "s/c")
    grader = {"name": "posts", "passed": False, "explanation": "pattern not found in file .eval/gh.jsonl"}
    result = _result(tmp_path, {"error": None, "turns": 3, "graders": [grader]})
    assert "- Run 1: **agent**, the session ran and graders failed" in _explain(
        capsys, "--result", str(result), repo=tmp_path
    )
    (tmp_path / "traces").mkdir()
    out = _explain(capsys, "--result", str(result), "--traces", str(tmp_path / "traces"), repo=tmp_path)
    assert "- Run 1: **agent**, the session ran and graders failed" in out


TOML_GRADER = """\
  - type: regex
    name: writes-the-config
    target:
      source: file
      path: .github/shipmill.toml
    pattern: 'home = '
"""
EDITS = (
    '{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Edit",'
    ' "input": {"file_path": "/w/.github/shipmill.toml", "old_string": "a", "new_string": "b"}}]}}\n'
)
SAYS = '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Stopping."}]}}\n'


@pytest.mark.parametrize(
    ("trace", "verdict"),
    [
        (SAYS, "**harness**, the session stopped early after 3 turns"),
        (EDITS + SAYS, "**agent**, the session ran and graders failed"),  # it wrote a grader's target
        (None, "**agent**, the session ran and graders failed"),  # no trace: a write can't be ruled out
    ],
)
def test_s025_31_an_early_stop_wrote_none_of_its_graders_targets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], trace: str | None, verdict: str
) -> None:
    result = _stopped(tmp_path, 3, "", graders=TOML_GRADER, trace=trace)
    out = _explain(capsys, "--result", result, "--traces", str(tmp_path / "traces"), repo=tmp_path)
    assert f"- Run 1: {verdict}" in out


@pytest.mark.parametrize(
    "target", ["{source file}", "{source: file, path: /etc/passwd}", "{source: file, path: ../x}", "a path"]
)
def test_s025_31_a_grader_target_it_cannot_read_is_bad_input(tmp_path: Path, target: str) -> None:
    _case(tmp_path, "s/c", graders=f"  - type: regex\n    name: g\n    target: {target}\n    pattern: x\n")
    result = _result(tmp_path, {"error": None, "turns": 3, "graders": [{"name": "g", "passed": False}]})
    with pytest.raises(ReleaseError, match=r"evals/s/c: case\.yaml: grader 1: .*target"):
        main(["evals", "explain", "--repo", str(tmp_path), "--result", str(result)])


def test_s025_31_a_failed_case_missing_from_the_suite_is_bad_input(tmp_path: Path) -> None:
    result = _result(tmp_path, {"error": None, "turns": 3, "graders": [{"name": "v", "passed": False}]})
    with pytest.raises(ReleaseError, match=r"evals/s/c: no case in the suite at "):
        main(["evals", "explain", "--repo", str(tmp_path), "--result", str(result)])


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
    _case(tmp_path, "s/c")
    result = _result(tmp_path, {"error": None, "aborted": True, "turns": 3, "graders": []})
    out = _explain(capsys, "--result", str(result), repo=tmp_path)
    assert "- Run 1: **agent**, it fell through every harness rule: aborted, with no error and no failed grader." in out
    assert "  - trace: the run names no tracePath\n" in out


def test_s025_31_a_pattern_the_grader_read_and_did_not_find_is_the_agent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # the runner's regex grader on a file it read: the session never wrote what it looks for
    grader = {"name": "posts-the-verdict", "passed": False, "explanation": "pattern not found in file .eval/gh.jsonl"}
    _case(tmp_path, "s/c")
    result = _result(tmp_path, {"error": None, "turns": 8, "graders": [grader]})
    out = _explain(capsys, "--result", str(result), repo=tmp_path)
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
