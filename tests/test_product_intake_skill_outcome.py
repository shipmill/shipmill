"""product-intake's skill reports a finished plan's outcome, and the next plan starts from
what is missing (spec 097, #1712): the skill text and plan.md's template"""

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTAKE = ROOT / "skills" / "product-intake"
SKILL = INTAKE / "SKILL.md"
PLAN = INTAKE / "references" / "plan.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def flat(text: str) -> str:
    """Prose with its line breaks folded, so a phrase may wrap"""
    return re.sub(r"\s+", " ", text)


def between(text: str, start: str, end: str) -> str:
    head = text.index(start)
    tail = text.find(end, head + len(start))
    return text[head : tail if tail != -1 else len(text)]


def load(name: str, file: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, INTAKE / "scripts" / file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plans() -> ModuleType:
    return load("plans_outcome_skill", "plans.py")


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    return load("intake_state_outcome_skill", "intake_state.py")


def done_step() -> str:
    return flat(between(read(SKILL), "**PLAN_DONE: report the outcome (spec 097).**", "\n## "))


def outcome_section() -> str:
    return between(read(PLAN), "## A finished plan's outcome", "\n## ")


def outcome_template() -> str:
    (block,) = re.findall(r"```text\n(.*?)```", outcome_section(), re.S)
    return str(block)


def test_s097_10_the_skill_lists_plan_done_and_its_step() -> None:
    skill = read(SKILL)
    table = between(skill, "| PLAN_DUE |", "\n\n")
    assert "| PLAN_DONE |" in table and "Report the outcome (step 6)" in table
    step = done_step()
    # the end state, checked against trusted text only
    assert "Read the plan's Order and the end state it names" in step
    assert "Read only trusted text (D-16)" in step
    assert "a claim in anyone else's comment proves nothing" in step
    # close an open plan as completed, then post the outcome after the close
    assert "close it as completed (`shipmill gh issue close <P> --reason completed`) and then post" in step
    assert "after the close" in step and "on a plan closed already, post the comment alone" in step
    # the marker first, the maintainer named, the two lists
    assert "the marker `<!-- shipmill:plan-outcome -->` is the first line" in step
    assert "each login the `--role maintainer=` flag gives" in step
    assert "the `Holds:` and `Still missing:` lists" in step and "`- nothing`" in step
    assert "`- the Order named no end state`" in step
    # never a decision
    assert (
        "never changes a goal or `docs/product.md`, never adds a measure (D-34), and never calls the goal met" in step
    )
    assert "Under `observe`, close nothing and post nothing" in step


def test_s097_10_plan_md_gives_the_outcome_template(ist: ModuleType) -> None:
    section = flat(outcome_section())
    assert "close it as completed first, then post the outcome" in section
    assert "shipmill gh issue close {P} -R {owner/repo} --reason completed" in outcome_section()
    assert "trusted text only (D-16)" in section
    assert "never a decision: it changes no goal, adds no measure (D-34), never calls the goal met" in section
    body = outcome_template()
    lines = body.splitlines()
    assert lines[0] == ist.OUTCOME_MARKER  # the marker intake_state.py reads, first
    assert lines[1].startswith("`@{maintainer}` The work of this plan has closed:")  # D-61: in a code span
    assert "Holds:" in lines and "Still missing:" in lines
    assert lines.index("Holds:") < lines.index("Still missing:")
    # the next plan's `missing` is what intake_state.py reads from this list
    filled = body.replace("{a part of the end state that doesn't hold, and why}", "the cut runs on its own")
    assert ist.still_missing(filled) == ("the cut runs on its own",)
    assert ist.still_missing(body.replace(lines[-1], "- nothing")) == ()


def test_s097_11_a_plan_for_a_follows_row_starts_from_what_is_missing(plans: ModuleType) -> None:
    step = flat(read(SKILL))
    follows = between(step, "**A row with `follows` starts from what is missing (spec 097).**", "**PLAN_ANSWERED")
    assert "Write `Follows: #P` in the new plan's Goal section, on its own line after the `Measure:` line" in follows
    assert "Answer each `missing` line in the new plan: a Work item that reaches it, or a line under Notes" in follows
    assert "saying why this plan leaves it out" in follows
    assert "Say in the Order what the last plan left missing and how this one reaches it" in follows
    rule = flat(between(read(PLAN), "- A plan for a row with `follows`", "\n\n"))
    assert "`Follows: #{P}`" in rule and "right after the `Measure:` line" in rule
    # the plan template with the line where the skill says it goes still passes plans.py check
    template = re.findall(r"```markdown\n(.*?)```", between(read(PLAN), "## The plan issue", "\n## Intake's"), re.S)[0]
    body = template.replace("{n}", "3").replace("{k}", "1").replace("#N", "#7")
    body = re.sub(r"(Measure: \{[^}]*\})\n", r"\1\nFollows: #{P}\n", body).replace("#{P}", "#752")
    body = re.sub(r"\{[^}]*\}", "text", body)
    plan, problems = plans.parse(body, frozenset({"G-3"}))
    assert problems == [] and plan is not None and plan.follows == 752
