"""Spec 025: `shipmill evals compare` gates a pull request's eval run against the default branch's"""

import json
from pathlib import Path

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "evals"
BASE = FIXTURES / "base.json"
HEAD = FIXTURES / "head.json"
PAD = "github-issue-triage/pad"  # a large steady case, so one case's move barely shifts the suite


def _result(tmp_path: Path, name: str, cases: dict[str, tuple[int, int]]) -> Path:
    """A runner result whose cases pass the first `passed` of their `runs` runs"""
    body = {
        "runs_planned": sum(runs for _, runs in cases.values()),
        "budget_reached": False,
        "cases": [
            {"path": path, "runs": [{"graders": [{"name": "verdict", "passed": n < passed}]} for n in range(runs)]}
            for path, (passed, runs) in cases.items()
        ],
    }
    file = tmp_path / f"{name}.json"
    file.write_text(json.dumps(body), encoding="utf-8")
    return file


def _compare(base: Path, head: Path, *extra: str) -> int:
    return main(["evals", "compare", "--base", str(base), "--head", str(head), *extra])


def test_s025_8_prints_each_moved_case_and_both_rates(capsys: pytest.CaptureFixture[str]) -> None:
    assert _compare(BASE, HEAD) == 1
    assert capsys.readouterr().out.splitlines() == [
        "regressed github-issue-triage/breaks: 3/3 -> 1/3",
        "new failing github-issue-resolve/added: 1/3",
        "improved github-pr-triage/heals: 1/3 -> 3/3",
        "removed github-pr-triage/dropped",
        "base pass rate: 0.778 (7/9 runs)",
        "head pass rate: 0.778 (7/9 runs)",
    ]


def test_s025_8_same_results_pass(capsys: pytest.CaptureFixture[str]) -> None:
    assert _compare(BASE, BASE) == 0
    assert capsys.readouterr().out.splitlines() == [
        "base pass rate: 0.833 (10/12 runs)",
        "head pass rate: 0.833 (10/12 runs)",
    ]


@pytest.mark.parametrize(("head_passed", "code"), [(19, 0), (18, 1)])
def test_s025_8_suite_drop_of_exactly_the_tolerance_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], head_passed: int, code: int
) -> None:
    base = _result(tmp_path, "base", {PAD: (20, 20)})
    head = _result(tmp_path, "head", {PAD: (head_passed, 20)})
    assert _compare(base, head) == code
    worse = "suite got worse: the head's pass rate is more than 0.05 below the base's"
    assert (worse in capsys.readouterr().out.splitlines()) is bool(code)


def test_s025_8_tolerance_flag_changes_the_suite_rule(tmp_path: Path) -> None:
    base = _result(tmp_path, "base", {PAD: (20, 20)})
    head = _result(tmp_path, "head", {PAD: (18, 20)})
    assert _compare(base, head, "--tolerance", "0.1") == 0


@pytest.mark.parametrize(
    ("base_passed", "head_passed", "code"),
    [(3, 1, 1), (3, 0, 1), (3, 2, 0), (2, 0, 0)],  # only a 3 of 3 case falling to at most 1 of 3 regresses
)
def test_s025_8_case_regresses_from_three_to_at_most_one(
    tmp_path: Path, base_passed: int, head_passed: int, code: int
) -> None:
    case = "github-pr-triage/case"
    base = _result(tmp_path, "base", {PAD: (60, 60), case: (base_passed, 3)})
    head = _result(tmp_path, "head", {PAD: (60, 60), case: (head_passed, 3)})
    assert _compare(base, head) == code


@pytest.mark.parametrize(("head_passed", "code"), [(2, 0), (1, 1), (0, 1)])
def test_s025_8_new_case_passes_two_of_three_on_its_own(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], head_passed: int, code: int
) -> None:
    case = "github-issue-resolve/new"
    base = _result(tmp_path, "base", {PAD: (60, 60)})
    head = _result(tmp_path, "head", {PAD: (60, 60), case: (head_passed, 3)})
    assert _compare(base, head) == code
    lines = capsys.readouterr().out.splitlines()
    assert (f"new failing {case}: {head_passed}/3" in lines) is bool(code)
    assert "head pass rate: 1.000 (60/60 runs)" in lines  # a new case is judged against itself only


def test_s025_8_changed_case_is_judged_against_itself(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    case = "github-pr-triage/case"
    base = _result(tmp_path, "base", {PAD: (60, 60), case: (0, 3)})
    head = _result(tmp_path, "head", {PAD: (60, 60), case: (2, 3)})
    assert _compare(base, head, "--changed", case) == 0
    assert f"improved {case}" not in capsys.readouterr().out
    head = _result(tmp_path, "head", {PAD: (60, 60), case: (1, 3)})
    assert _compare(base, head, "--changed", case) == 1
    assert f"new failing {case}: 1/3" in capsys.readouterr().out.splitlines()


def test_s025_8_removed_case_never_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    case = "github-pr-triage/gone"
    base = _result(tmp_path, "base", {PAD: (60, 60), case: (0, 3)})
    head = _result(tmp_path, "head", {PAD: (60, 60)})
    assert _compare(base, head) == 0
    assert capsys.readouterr().out.splitlines()[0] == f"removed {case}"


def test_s025_8_changed_names_a_case_the_head_holds(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="--changed github-pr-triage/nowhere: .*holds no such case"):
        _compare(BASE, HEAD, "--changed", "github-pr-triage/nowhere")


@pytest.mark.parametrize("flag", [["--tolerance", "1.5"], ["--tolerance", "-0.1"], ["--changed", "../escape"]])
def test_s025_8_malformed_flags_exit_2(flag: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        _compare(BASE, HEAD, *flag)
    assert exc.value.code == 2


def test_s025_9_a_run_passes_only_when_every_scored_grader_passed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """base.json's steady case passes 3 of 3 despite a failing unscored grader; its heals case
    passes 1 of 3, each failing run having one scored grader pass and the other fail"""
    assert _compare(BASE, BASE) == 0
    assert "base pass rate: 0.833 (10/12 runs)" in capsys.readouterr().out.splitlines()
    run = {"graders": [{"name": "verdict", "passed": True}, {"name": "note", "passed": True, "scored": False}]}
    body = {"runs_planned": 1, "budget_reached": False, "cases": [{"path": PAD, "runs": [run]}]}
    file = tmp_path / "one.json"
    file.write_text(json.dumps(body), encoding="utf-8")
    assert _compare(file, file) == 0
    assert "head pass rate: 1.000 (1/1 runs)" in capsys.readouterr().out.splitlines()


def test_s025_9_a_run_without_a_scored_grader_is_malformed(tmp_path: Path) -> None:
    run = {"graders": [{"name": "note", "passed": True, "scored": False}]}
    body = {"runs_planned": 1, "budget_reached": False, "cases": [{"path": PAD, "runs": [run]}]}
    file = tmp_path / "unscored.json"
    file.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ReleaseError, match="unscored.json: github-issue-triage/pad: run 1: no scored grader"):
        _compare(file, file)


@pytest.mark.parametrize(
    ("body", "fault"),
    [
        ("[]", "the result is a JSON object"),
        ("{", "not valid JSON"),
        ('{"budget_reached": false, "cases": []}', "runs_planned is a whole number from 1"),
        ('{"runs_planned": 3, "budget_reached": 0, "cases": []}', "budget_reached is true or false"),
        ('{"runs_planned": 3, "budget_reached": false}', "cases is a list of cases"),
        ('{"runs_planned": 3, "budget_reached": false, "cases": [{"path": "../x", "runs": []}]}', "path is relative"),
        ('{"runs_planned": 3, "budget_reached": false, "cases": [{"path": "a/b", "runs": []}]}', "at least one run"),
        ('{"runs_planned": 3, "budget_reached": false, "cases": [{"path": "a/b", "runs": [{}]}]}', "graders is a list"),
        (
            '{"runs_planned": 3, "budget_reached": false, "cases": [{"path": "a/b", "runs": '
            '[{"graders": [{"passed": true}]}]}]}',
            "name is a non-empty string",
        ),
        (
            '{"runs_planned": 3, "budget_reached": false, "cases": [{"path": "a/b", "runs": '
            '[{"graders": [{"name": "v", "passed": true}]}]}]}',
            "holds 1 of 3 planned runs, yet budget_reached is false",
        ),
    ],
)
def test_s025_9_malformed_result_names_the_file_and_the_fault(tmp_path: Path, body: str, fault: str) -> None:
    file = tmp_path / "aggregate-result.json"
    file.write_text(body, encoding="utf-8")
    with pytest.raises(ReleaseError, match=f"aggregate-result.json: .*{fault}"):
        _compare(file, HEAD)


def test_s025_9_missing_or_malformed_fixture_exits_2(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match=r"missing\.json: no such file"):
        _compare(BASE, tmp_path / "missing.json")
    with pytest.raises(ReleaseError, match=r"malformed\.json: .*passed is true or false; got 'yes'"):
        _compare(BASE, FIXTURES / "malformed.json")


def test_s025_14_budget_reached_fails_and_compares_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert _compare(BASE, FIXTURES / "head-budget.json") == 1
    assert capsys.readouterr().out.splitlines() == ["evals: budget reached after 5 of 12 runs"]


def test_s025_14_a_base_stopped_at_its_budget_is_never_compared(capsys: pytest.CaptureFixture[str]) -> None:
    assert _compare(FIXTURES / "head-budget.json", BASE) == 1
    assert capsys.readouterr().out.splitlines() == ["evals: budget reached after 5 of 12 runs"]
