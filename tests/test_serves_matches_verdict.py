"""#1767: an agent's pull request serves a goal its issues' triage verdicts name, end to end through
pr_gate.py with test_pr_gate.py's stand-in gh on PATH"""

from pathlib import Path
from typing import Any

import pytest

from .test_allowed_files import allowing
from .test_pr_gate import BOT, DIRECTION, MAIN_READY, PLAN, at, checkout, comment, pr, run_gate, thread

REFUSED = MAIN_READY.replace("READY", "REFUSED")


def triaged(first: str, when: str = at(9), **kw: Any) -> dict[str, Any]:
    """The App's triage verdict on the issue, its first line first, before the PR opened (10:00)"""
    return allowing(f"{first}\n\nThe reasoning.\n\n<!-- shipmill:agent -->\n", when, **kw)


def plan(serves: str, closes: str = "Part of #12") -> str:
    return PLAN.replace("Fixes #7", closes).replace("- Serves: G-3", f"- Serves: {serves}")


def gated(tmp_path: Path, body: str, issues: dict[int, dict[str, Any]], login: str = "app/shipmill-demo") -> Any:
    """The gate on #7, a green PR with a review on record, in a fresh folder under tmp_path each call"""
    here = tmp_path / f"run-{len(list(tmp_path.iterdir()))}"
    here.mkdir()
    work = checkout(here, {"docs/product.md": DIRECTION})
    return run_gate(here, work, {7: pr(body=body, login=login)}, "--bot-login", BOT, issues=issues)


def refused(proc: Any) -> list[str]:
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[0] == REFUSED.rstrip("\n"), proc.stdout
    return list(proc.stdout.splitlines()[1:])


def ready(proc: Any) -> None:
    assert (proc.returncode, proc.stdout) == (0, MAIN_READY), proc.stdout + proc.stderr


def test_a_plan_serving_the_quality_bar_is_refused_when_the_verdict_names_a_goal(tmp_path: Path) -> None:
    """#1767's repro: the verdict serves G-3, the plan says quality bar, and the gate read READY"""
    issue = thread(triaged("Triage: **implement**. Serves: G-3."))
    assert refused(gated(tmp_path, plan("quality bar"), {12: issue})) == [
        "  refused: `Serves:` names quality bar, but the triage verdict on #12 serves G-3: name one of its goals"
    ]


def test_a_plan_serving_another_goal_is_refused(tmp_path: Path) -> None:
    issue = thread(triaged("Triage: **feature**. Serves: G-3."))
    assert refused(gated(tmp_path, plan("G-1, Q-1"), {12: issue})) == [
        "  refused: `Serves:` names G-1, Q-1, but the triage verdict on #12 serves G-3: name one of its goals"
    ]


@pytest.mark.parametrize("serves", ["G-3", "G-1, G-3", "G-3, quality bar (Q-1)"])
def test_a_plan_naming_the_verdicts_goal_is_ready(tmp_path: Path, serves: str) -> None:
    ready(gated(tmp_path, plan(serves), {12: thread(triaged("Triage: **implement**. Serves: G-3."))}))


def test_a_verdict_naming_several_goals_takes_any_of_them(tmp_path: Path) -> None:
    issue = thread(triaged("Triage: **implement**. Serves: G-1, G-3."))
    ready(gated(tmp_path, plan("G-1"), {12: issue}))
    assert refused(gated(tmp_path, plan("Q-1"), {12: issue})) == [
        "  refused: `Serves:` names Q-1, but the triage verdict on #12 serves G-1, G-3: name one of its goals"
    ]


@pytest.mark.parametrize(
    "first",
    [
        pytest.param("Triage: **implement**. The fix is small.", id="a bug fix"),
        pytest.param("Triage: **opportunity**. Serves no goal: it goes to product intake.", id="serves no goal"),
        pytest.param("A note. Serves: G-3.", id="not a triage verdict"),
    ],
)
def test_a_verdict_naming_no_goal_accepts_the_quality_bar(tmp_path: Path, first: str) -> None:
    ready(gated(tmp_path, plan("quality bar"), {12: thread(triaged(first))}))


def test_a_verdict_goal_the_direction_no_longer_lists_counts_for_nothing(tmp_path: Path) -> None:
    """a goal met and dropped from the direction since the verdict (G-2 here) can't be named by a
    plan, which the direction check refuses for an unlisted id, so it can't be asked for either"""
    issue = thread(triaged("Triage: **implement**. Serves: G-2."))
    ready(gated(tmp_path, plan("quality bar"), {12: issue}))
    both = thread(triaged("Triage: **implement**. Serves: G-2, G-3."))
    assert refused(gated(tmp_path, plan("quality bar"), {12: both})) == [
        "  refused: `Serves:` names quality bar, but the triage verdict on #12 serves G-3: name one of its goals"
    ]


def test_a_goal_on_a_later_line_of_the_verdict_names_none(tmp_path: Path) -> None:
    """only the verdict line counts: a plan's `- Serves: G-1` under it is the implementer's draft"""
    issue = thread(allowing("Triage: **implement**. The fix is small.\n\n- Serves: G-1\n"))
    ready(gated(tmp_path, plan("quality bar"), {12: issue}))


def test_the_newest_trusted_verdict_before_the_pr_opened_counts(tmp_path: Path) -> None:
    """the allowance's newest-wins rule (spec 085, D-106): a later trusted verdict replaces the
    older; one by an outsider, or written after the pull request opened, counts for nothing"""
    older = triaged("Triage: **feature**. Serves: G-3.", when=at(8))
    newer = triaged("Triage: **implement**. Serves: G-1.")
    ready(gated(tmp_path, plan("G-1"), {12: thread(older, newer)}))
    assert refused(gated(tmp_path, plan("G-3"), {12: thread(older, newer)})) == [
        "  refused: `Serves:` names G-3, but the triage verdict on #12 serves G-1: name one of its goals"
    ]
    outsider = triaged("Triage: **implement**. Serves: G-1.", login="eve", association="CONTRIBUTOR")
    ready(gated(tmp_path, plan("G-3"), {12: thread(older, outsider)}))
    late = triaged("Triage: **implement**. Serves: G-1.", when=at(11))
    ready(gated(tmp_path, plan("G-3"), {12: thread(older, late)}))


def test_a_maintainers_verdict_counts_too(tmp_path: Path) -> None:
    issue = thread(comment("Triage: **implement**. Serves: G-3.", at(9)))
    assert refused(gated(tmp_path, plan("quality bar"), {12: issue}))[0].startswith("  refused: `Serves:` names")


def test_several_issues_each_need_one_of_their_goals(tmp_path: Path) -> None:
    issues = {
        12: thread(triaged("Triage: **implement**. Serves: G-3.")),
        13: thread(triaged("Triage: **implement**. Serves: G-1.")),
        14: thread(triaged("Triage: **implement**. The fix is small.")),
    }
    body = plan("G-3", "Part of #12\nPart of #13\nPart of #14")
    assert refused(gated(tmp_path, body, issues)) == [
        "  refused: `Serves:` names G-3, but the triage verdict on #13 serves G-1: name one of its goals"
    ]
    ready(gated(tmp_path, plan("G-1, G-3", "Part of #12\nPart of #13\nPart of #14"), issues))


def test_a_closed_issue_counts_as_a_part_of_one_does(tmp_path: Path) -> None:
    issue = thread(triaged("Triage: **implement**. Serves: G-3."))
    assert refused(gated(tmp_path, plan("quality bar", "Fixes #12"), {12: issue}))


def test_a_persons_pr_is_untouched(tmp_path: Path) -> None:
    issue = thread(triaged("Triage: **implement**. Serves: G-3."))
    ready(gated(tmp_path, "Part of #12\n\nNo plan.\n", {12: issue}, login="amy"))
