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


def _run(passed: bool, **extra: object) -> dict[str, object]:
    grader = {"name": "verdict", "passed": passed, "weight": 1, "scored": True}
    return {"error": None, "skippedPaidGraders": False, "graders": [grader], **extra}


def _case(path: str, runs: list[dict[str, object]], per_case: int = 3) -> dict[str, object]:
    return {"name": path.rsplit("/", 1)[-1], "dir": f"evals/{path}", "runsPerCase": per_case, "arms": {"with": runs}}


def _write(tmp_path: Path, name: str, cases: list[dict[str, object]], **top: object) -> Path:
    file = tmp_path / f"{name}.json"
    file.write_text(json.dumps({"schemaVersion": 1, "partial": False, "cases": cases, **top}), encoding="utf-8")
    return file


def _result(tmp_path: Path, name: str, cases: dict[str, tuple[int, int]]) -> Path:
    """A runner result, in the runner's format, whose cases pass the first `passed` of their `runs` runs"""
    return _write(
        tmp_path, name, [_case(p, [_run(n < passed) for n in range(runs)]) for p, (passed, runs) in cases.items()]
    )


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
    rates = ["base pass rate: 1.000 (20/20 runs)", f"head pass rate: {head_passed / 20:.3f} ({head_passed}/20 runs)"]
    assert capsys.readouterr().out.splitlines() == ([worse] if code else []) + rates  # the verdict, then both rates


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
    passes 1 of 3: one run had a scored grader fail, one ended on an API error"""
    assert _compare(BASE, BASE) == 0
    assert "base pass rate: 0.833 (10/12 runs)" in capsys.readouterr().out.splitlines()
    verdict = {"name": "verdict", "passed": True, "weight": 1, "scored": True}
    unscored = {"name": "note", "passed": False, "weight": 1, "scored": False}
    run = _run(True, graders=[verdict, unscored])
    file = _write(tmp_path, "one", [_case(PAD, [run])])
    assert _compare(file, file) == 0
    assert "head pass rate: 1.000 (1/1 runs)" in capsys.readouterr().out.splitlines()


def test_s025_9_a_real_runner_result_compares_against_itself(capsys: pytest.CaptureFixture[str]) -> None:
    """A result one `claude plugin eval` run wrote (shipmill/shipmill#443), whose runsPerCase
    says 3 though it ran one: the runs present are the runs made"""
    real = FIXTURES / "runner-result.json"
    assert _compare(real, real) == 0
    assert capsys.readouterr().out.splitlines() == [
        "base pass rate: 1.000 (1/1 runs)",
        "head pass rate: 1.000 (1/1 runs)",
    ]


@pytest.mark.parametrize(
    "failed",
    [
        _run(True, error="API error: overloaded", graders=[]),
        {"error": "API error: rate limited", "skippedPaidGraders": False},  # no grader results at all
        _run(True, aborted=True),
        _run(True, skippedPaidGraders=True),
    ],
    ids=["error", "error-without-graders", "aborted", "skipped-paid-graders"],
)
def test_s025_9_an_errored_aborted_or_half_graded_run_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], failed: dict[str, object]
) -> None:
    base = _result(tmp_path, "base", {PAD: (3, 3)})
    head = _write(tmp_path, "head", [_case(PAD, [_run(True), failed, failed])])
    assert _compare(base, head) == 1
    assert f"regressed {PAD}: 3/3 -> 1/3" in capsys.readouterr().out.splitlines()


def test_s025_9_cases_of_one_name_in_two_skills_stay_apart(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    one, two = "github-issue-triage/same", "github-pr-triage/same"
    base = _result(tmp_path, "base", {one: (3, 3), two: (3, 3)})
    head = _result(tmp_path, "head", {one: (3, 3), two: (0, 3)})
    assert _compare(base, head) == 1
    assert capsys.readouterr().out.splitlines()[0] == f"regressed {two}: 3/3 -> 0/3"


def test_s025_9_a_run_without_a_scored_grader_is_malformed(tmp_path: Path) -> None:
    run = _run(True, graders=[{"name": "note", "passed": True, "scored": False}])
    file = _write(tmp_path, "unscored", [_case(PAD, [run])])
    with pytest.raises(ReleaseError, match="unscored.json: github-issue-triage/pad: run 1: no scored grader"):
        _compare(file, file)


_CASE = '{"name": "b", "dir": "evals/a/b", "runsPerCase": 3, "arms": {"with": %s}}'
_TOP = '{"schemaVersion": 1, "partial": false, "cases": [%s]}'


@pytest.mark.parametrize(
    ("body", "fault"),
    [
        ("[]", "the result is a JSON object"),
        ("{", "not valid JSON"),
        ('{"partial": false, "cases": []}', "schemaVersion is 1"),
        ('{"schemaVersion": 2, "partial": false, "cases": []}', "schemaVersion is 1"),
        ('{"schemaVersion": 1, "partial": 0, "cases": []}', "partial is true or false"),
        ('{"schemaVersion": 1, "partial": false}', "cases is a list of cases"),
        (_TOP % "", "cases holds no case"),
        (_TOP % '{"dir": "evals/a/b"}', "name is a non-empty string"),
        (_TOP % '{"name": "b", "dir": "a/b"}', "dir is the case's directory under evals/"),
        (_TOP % '{"name": "b", "dir": "evals/../x"}', "dir is the case's directory under evals/"),
        (_TOP % '{"name": "b", "dir": "evals/a/b", "arms": {"with": []}}', "runsPerCase is a whole number"),
        (_TOP % '{"name": "b", "dir": "evals/a/b", "runsPerCase": 3, "runs": []}', "arms.with is a list"),
        (_TOP % (_CASE % "[]"), "at least one run"),
        (_TOP % (_CASE % '[{"error": null}]'), "graders is a list"),
        (_TOP % (_CASE % '[{"error": null, "aborted": "no", "graders": []}]'), "aborted is true or false"),
        (_TOP % (_CASE % '[{"error": null, "graders": [{"passed": true}]}]'), "name is a non-empty string"),
    ],
)
def test_s025_9_malformed_result_names_the_file_and_the_fault(tmp_path: Path, body: str, fault: str) -> None:
    file = tmp_path / "aggregate-result.json"
    file.write_text(body, encoding="utf-8")
    with pytest.raises(ReleaseError, match=f"aggregate-result.json: .*{fault}"):
        _compare(file, HEAD)


def test_s025_9_a_case_listed_twice_is_malformed(tmp_path: Path) -> None:
    file = _write(tmp_path, "twice", [_case(PAD, [_run(True)]), _case(PAD, [_run(True)])])
    with pytest.raises(
        ReleaseError, match="twice.json: case 'pad': dir 'evals/github-issue-triage/pad' is listed twice"
    ):
        _compare(file, file)


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


def test_s025_14_the_planned_runs_are_each_cases_runs_per_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The result names no planned run count; a case not reached yet still counts its runsPerCase"""
    head = _write(
        tmp_path,
        "head",
        [_case(PAD, [_run(True)], per_case=5), _case("a/b", [])],
        partial=True,
        partialReason="cost_ceiling",
    )
    assert _compare(BASE, head) == 1
    assert capsys.readouterr().out.splitlines() == ["evals: budget reached after 1 of 8 runs"]


def test_s025_14_a_changed_case_the_budget_left_unrun_still_names_the_budget(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """evals.yml passes --changed for every case the head lists; one stopped before its first run
    holds no runs, and the budget line, not a bad-input error, is what fails the gate"""
    head = _write(
        tmp_path,
        "head",
        [_case(PAD, [_run(True)], per_case=5), _case("a/b", [])],
        partial=True,
        partialReason="cost_ceiling",
    )
    assert _compare(BASE, head, "--changed", "a/b") == 1
    assert capsys.readouterr().out.splitlines() == ["evals: budget reached after 1 of 8 runs"]


@pytest.mark.parametrize("reason", [None, "interrupted"])
def test_s025_14_a_run_stopped_for_another_reason_is_never_compared(tmp_path: Path, reason: str | None) -> None:
    head = _write(tmp_path, "head", [_case(PAD, [_run(True)])], partial=True, partialReason=reason)
    with pytest.raises(
        ReleaseError, match=f"head.json: partial: the run stopped early \\({reason!r}\\), not at its budget"
    ):
        _compare(BASE, head)
