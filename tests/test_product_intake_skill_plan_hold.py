"""product-intake's skill re-checks a held plan once its hold is met (spec 098, #1729)"""

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTAKE = ROOT / "skills" / "product-intake"
SKILL = INTAKE / "SKILL.md"


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def between(text: str, start: str, end: str) -> str:
    head = text.index(start)
    tail = text.find(end, head + len(start))
    return text[head : tail if tail != -1 else len(text)]


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    spec = importlib.util.spec_from_file_location("intake_state_hold_skill", INTAKE / "scripts" / "intake_state.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_s098_14_product_intake_gives_the_hold_answer_and_never_acts_on_a_held_plan() -> None:
    text = flat(SKILL.read_text(encoding="utf-8"))
    rule = between(text, "9. **A plan changes only on the maintainer's answer", "## The script")
    assert "first line is `hold until <condition>`" in rule and "holds the plan, never edits it" in rule
    assert "the plan reads PLAN_HELD and no session acts on it" in rule
    assert "then it reads PLAN_HOLD_MET and a session only re-checks it" in rule
    relay = between(text, "**Answered in the session.**", "**PLAN_ACCEPTED")
    assert "`decline <reason>`, `hold until <condition>`, or the edit asked for" in relay
    assert "**PLAN_HOLD_MET: re-check the plan (spec 098).**" in text and "plan-recheck" in text


def test_s098_14_the_plans_triage_line_names_the_hold_answer() -> None:
    plan = (INTAKE / "references" / "plan.md").read_text(encoding="utf-8")
    line = between(plan, "Triage: **plan**.", "\n")
    assert "`accept` files" in line and "`decline` closes" in line and "read as an edit" in line
    assert "`hold until <a date, #N, or release>` holds the plan untouched until then" in line
    assert "implement" not in line  # triage_state.py reads the verdict from the triage comment


def test_s098_14_the_fleet_section_says_a_held_plan_is_no_plan_row() -> None:
    watch = (ROOT / "skills" / "github-ship-watch" / "SKILL.md").read_text(encoding="utf-8")
    row = flat(between(watch, "- `PLAN`: a goal plan waiting for its answer", "\n- `SPEC_TO_MERGE`"))
    assert "is no `PLAN` row until its condition is met" in row and "PLAN_HELD and PLAN_HOLD_MET are no row" in row
    assert "waiting since the later of its newest revision and the hold's `met_at`" in row


def test_s098_16_the_skill_lists_the_held_states() -> None:
    table = between(SKILL.read_text(encoding="utf-8"), "| PLAN_DUE |", "\n\n")
    assert "| PLAN_HELD |" in table and "Nothing: no session acts on a held plan" in table
    assert "| PLAN_HOLD_MET |" in table and "Re-check it (step 6)" in table


def test_s098_16_the_skill_gives_the_recheck_step(ist: ModuleType) -> None:
    step = flat(between(SKILL.read_text(encoding="utf-8"), "**PLAN_HOLD_MET: re-check the plan (spec 098).**", "\n## "))
    assert "Read each Work item of the plan's body against the default branch and the repository's issues" in step
    assert "reading trusted text only (D-16)" in step and "a claim in anyone else's comment proves nothing" in step
    assert "Post one comment on the plan through `shipmill gh` with `--body-file`, as the App" in step
    assert f"its first line the marker `{ist.RECHECK_MARKER}`" in step
    assert "list each item already done and each item gone stale, each with what shows it" in step
    assert "`Nothing in this plan is done or stale.`" in step
    assert "never edit the plan's body (spec 028), file nothing, and change no answer" in step
    assert "Under `observe`, post nothing" in step
