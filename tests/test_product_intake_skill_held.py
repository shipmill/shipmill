"""product-intake's skill holds new outcomes at the [agents] outcomes limit (spec 101, #1733):
the skill text and opportunity.md's held comment"""

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTAKE = ROOT / "skills" / "product-intake"
SKILL = INTAKE / "SKILL.md"
OPPORTUNITY = INTAKE / "references" / "opportunity.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def flat(text: str) -> str:
    """Prose with its line breaks folded, so a phrase may wrap"""
    return re.sub(r"\s+", " ", text)


def between(text: str, start: str, end: str) -> str:
    head = text.index(start)
    tail = text.find(end, head + len(start))
    return text[head : tail if tail != -1 else len(text)]


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    spec = importlib.util.spec_from_file_location("intake_state_held_skill", INTAKE / "scripts" / "intake_state.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def held_comment() -> str:
    section = between(read(OPPORTUNITY), "## On a request held at the limit", "\n## ")
    (block,) = re.findall(r"```markdown\n(.*?)```", section, re.S)
    return str(block)


def test_s101_11_the_skill_lists_held_in_its_state_table() -> None:
    table = between(read(SKILL), "| NEW_FEEDBACK |", "\n\n")
    (row,) = [line for line in table.splitlines() if line.startswith("| HELD |")]
    assert "`held since <date>`" in row and "Nothing: it waits for room, oldest held first" in row


def test_s101_11_a_pass_at_the_limit_opens_no_new_opportunity_unless_asked_by_name() -> None:
    skill = flat(read(SKILL))
    rule = between(skill, "10. **A pass at the limit opens no new opportunity (spec 101).**", "## The script")
    assert "opens no new opportunity issue unless the maintainer asked for it by name" in rule
    step = between(skill, "**At the limit, hold the new outcome (spec 101).**", "### 4.")
    assert "At room 0, opens no opportunity: comment the held comment" in step
    assert "oldest held comment first" in step and "at most R in all" in step
    assert "gets its opportunity whatever the room" in step


def test_s101_11_the_report_names_the_room_and_the_held_outcomes() -> None:
    report = flat(between(read(SKILL), "## Report", "\n## "))
    assert "a line gives the room, `K of N in flight`" in report
    assert "each held outcome with its requests, oldest held first" in report


def test_s101_11_opportunity_md_holds_the_held_comment(ist: ModuleType) -> None:
    body = held_comment()
    assert body.splitlines()[0] == ist.HELD_MARKER  # the marker intake_state.py reads, first
    assert "Triage:" not in body
    assert "implement" not in body.lower()
    assert ist.verdict(body, "Triage:") is None  # triage's hand-off stays the request's verdict
    assert "`[agents] outcomes`" in body and "`propose`" in body
