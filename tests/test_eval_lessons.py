"""Spec 025: a lesson becomes an eval case, and a red evals check is never unrelated (#439)"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = sorted(path.parent.name for path in (ROOT / "skills").glob("*/SKILL.md"))


def folded(path: Path) -> str:
    """A file with its line wrapping folded, so a statement reads as one line"""
    return " ".join(path.read_text(encoding="utf-8").split())


def section(text: str, heading: str) -> str:
    """The body of a `## <heading>` section in a folded text, up to the next `## `"""
    assert f"## {heading} " in text, heading
    return text.split(f"## {heading} ", 1)[1].split(" ## ", 1)[0]


def test_s025_15_the_postmortem_template_names_an_eval_case() -> None:
    body = section(folded(ROOT / "docs" / "postmortems" / "TEMPLATE.md"), "Eval case")
    assert "the case under `evals/` that would have caught the fault" in body
    assert "`none:` and why no agent's instructions were involved" in body


def test_s025_15_every_skill_is_checked() -> None:
    # a new skill joins the parametrized test below by having a SKILL.md
    assert len(SKILLS) >= 6
    assert {"github-issue-resolve", "shipmill-setup"} <= set(SKILLS)


@pytest.mark.parametrize("skill", SKILLS)
def test_s025_15_each_skill_adds_a_failing_eval_case_with_the_lesson(skill: str) -> None:
    body = section(folded(ROOT / "skills" / skill / "SKILL.md"), "Improve the skill")
    assert "When a lesson goes into the skill, add a case under `evals/` that fails without it" in body, skill
    assert "in the same pull request" in body, skill


def test_s025_17_a_red_evals_check_is_never_proven_unrelated() -> None:
    text = folded(ROOT / "skills" / "github-pr-triage" / "SKILL.md")
    rule_2 = text.split(" 2. **Red CI blocks the merge**", 1)[1].split(" 3. **", 1)[0]
    assert "A red `evals` check is never proven unrelated" in rule_2
    assert "it blocks the merge unless the maintainer accepts that run (D-37)" in rule_2


def test_s025_17_a_forks_evals_land_only_after_a_dispatched_green_run() -> None:
    text = folded(ROOT / "skills" / "github-pr-triage" / "references" / "ci-failures.md")
    assert "A red `evals` check is always caused by the PR" in text
    assert "`gh workflow run evals.yml -f pr=<N> -f sha=<head SHA>`, for the head SHA the maintainer read)" in text
    assert "the PR lands only after that run is green, and only while that SHA is still its head" in text


def test_s025_23_a_forks_dispatched_run_counts_only_while_its_sha_is_the_head() -> None:
    text = folded(ROOT / "skills" / "github-pr-triage" / "SKILL.md")
    rule_2 = text.split(" 2. **Red CI blocks the merge**", 1)[1].split(" 3. **", 1)[0]
    assert (
        "A fork's dispatched `evals` run counts only while the head SHA it recorded "
        "(its summary's `evals: measured <sha> of #<N>`) is the PR's current head"
    ) in rule_2
    assert "a push after the run needs a new dispatch naming the new SHA" in rule_2
    assert "`gh workflow run evals.yml -f pr=<N> -f sha=<head SHA>`" in rule_2
