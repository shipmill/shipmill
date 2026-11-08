"""Spec 025, D-74 (#972): a lesson becomes a rule in code, not an eval case, and no evals check holds a pull request"""

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


def test_s025_15_the_postmortem_template_names_the_rule_in_code() -> None:
    # D-74 (#972): no more eval cases; the template asks for the check in code instead
    text = folded(ROOT / "docs" / "postmortems" / "TEMPLATE.md")
    assert "## Eval case" not in text
    body = section(text, "Rule in code")
    assert "The test, hook, or gate check that now holds what an agent got wrong" in body
    assert "`none:` and why no agent's instructions were involved" in body
    assert "The evals stopped (D-74), so no case goes under `evals/`" in body


def test_s025_15_every_skill_is_checked() -> None:
    # a new skill joins the parametrized test below by having a SKILL.md
    assert len(SKILLS) >= 6
    assert {"github-issue-resolve", "shipmill-setup"} <= set(SKILLS)


@pytest.mark.parametrize("skill", SKILLS)
def test_s025_15_each_skill_puts_a_rule_in_code_and_adds_no_eval_case(skill: str) -> None:
    # D-74 (#972): a rule that must hold goes into code, and no case goes under evals/
    body = section(folded(ROOT / "skills" / skill / "SKILL.md"), "Improve the skill")
    assert (
        "When a rule must hold, put it in code too (a script with its test, a hook, or the gate),"
        " since a skill's prose only makes it likely; the evals stopped (D-74), so add no case under `evals/`."
    ) in body, skill
    assert "fails without it" not in body, skill


def test_s025_17_since_d74_no_evals_check_is_waited_on_or_blocks() -> None:
    # the evals stopped (D-74, #972): D-37's gate is retired, so no evals run holds a PR
    text = folded(ROOT / "skills" / "github-pr-triage" / "SKILL.md")
    rule_2 = text.split(" 2. **Red CI blocks the merge**", 1)[1].split(" 3. **", 1)[0]
    assert (
        "The evals stopped (D-74): `evals.yml` runs only by hand and no pull request needs an `evals` check,"
        " so never wait on one or dispatch one" in rule_2
    )
    assert "D-37's gate is retired, so a run someone dispatched by hand blocks nothing" in rule_2
    assert "D-72" not in rule_2 and "must then be green" not in rule_2
    ci = folded(ROOT / "skills" / "github-pr-triage" / "references" / "ci-failures.md")
    assert "Since the evals stopped (D-74), no pull request gets an `evals` check, a fork's included" in ci
    assert "a run someone dispatched by hand blocks nothing" in ci
    assert "D-72" not in ci and "must then be green" not in ci


def test_s025_23_no_dispatched_run_is_pinned_to_a_head_any_more() -> None:
    # D-74 dropped S-025-23's rule: with no gate, a fork's dispatched run counts for nothing
    text = folded(ROOT / "skills" / "github-pr-triage" / "SKILL.md")
    rule_2 = text.split(" 2. **Red CI blocks the merge**", 1)[1].split(" 3. **", 1)[0]
    assert "evals: measured <sha> of #<N>" not in rule_2
    assert "gh workflow run evals.yml" not in rule_2
