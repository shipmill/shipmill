"""product-intake's skill links an accepted plan's existing items as its sub-issues and posts
the filed line even when nothing new was filed (D-114, #1706): the skill text and plan.md's
filed line"""

import re
from pathlib import Path

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


def test_1706_the_skill_links_each_existing_item_under_the_plan() -> None:
    accepted = flat(between(read(SKILL), "**PLAN_ACCEPTED: file the work.**", "Filing starts no work"))
    link = between(accepted, "**Link the existing items (D-114).**", "When the Milestone")
    assert "Make each `existing` item of this repository a sub-issue of the plan, open or closed" in link
    assert "`chains.py link <owner/repo>#P --child <owner/repo>#<n> --no-text`" in link
    assert "The row's note names the ones still to link as `not linked: #n`" in link
    assert "so a resumed pass never links it twice" in link
    assert "An item the note names under `another parent:`" in link and "or one of another repository" in link
    assert "is not linked: name it in the filed line" in link
    assert "When the link exits 2, stop and report the plan with the error" in link
    assert "once they all close it reads PLAN_DONE" in link
    # the filed line is posted with nothing new filed, so triage's verdict moves off the answer
    assert "Comment the filed line on the plan, also when nothing new was filed" in accepted
    assert "the plan as their parent are all intake adds (D-38, D-114)" in accepted


def test_1706_the_state_table_reads_an_unlinked_existing_item_as_accepted() -> None:
    table = flat(between(read(SKILL), "| PLAN_DUE |", "\n\n"))
    accepted = between(table, "| PLAN_ACCEPTED |", "| PLAN_FILED |")
    assert "an `existing` item of this repository that isn't the plan's sub-issue" in accepted
    filed = between(table, "| PLAN_FILED |", "| PLAN_DONE |")
    assert "linked under the plan" in filed


def test_1706_the_filed_line_names_the_linked_and_unlinked_existing_items() -> None:
    section = between(read(PLAN), "## Intake's line on the plan once filed", "\n## ")
    (line,) = re.findall(r"```markdown\n(.*?)```", section, re.S)
    assert line.startswith("Triage: **plan**: accepted and filed: ")  # triage_state.py's goal_plan reads it
    assert "{; linked: W-1 #{n}}" in line
    assert "{; not linked: W-4 {owner/repo}#{m}, W-5 #{k} (another parent)}" in line
    rules = flat(section)
    assert "the filed part is `nothing new` (`accepted and filed: nothing new; linked: W-1 #{n}`)" in rules
    assert "`linked:` names each `existing` item of this repository made a sub-issue of the plan (D-114)" in rules
    assert "neither is linked" in rules
