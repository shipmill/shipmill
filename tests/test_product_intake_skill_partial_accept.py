"""product-intake's skill files only a partially accepted plan's kept items, asks about an
unclear accept, and never proposes a dropped item again (spec 096, #1709): the skill text and
plan.md's templates"""

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


def step(start: str, end: str) -> str:
    return flat(between(read(SKILL), start, end))


def test_s096_10_the_skill_files_only_the_kept_items() -> None:
    accepted = step("**PLAN_ACCEPTED: file the work.**", "Filing starts no work")
    # the row's kept list decides, from the three accept forms
    assert "The row's `kept` and `dropped` (with `--json`) say what the accept chose" in accepted
    assert "`accept W-1, W-3` keeps those named" in accepted and "`accept except W-2` keeps all but those" in accepted
    assert "of the kept items, for each `feature` and `fix` item still `null`, in Work order" in accepted
    # a dropped item is never filed, linked, or milestoned
    assert (
        "A dropped item is never filed, never made a sub-issue of the plan, and never put in the milestone" in accepted
    )
    assert "a dropped `existing` item is left exactly as it is" in accepted
    assert "every kept `existing` item of this repository in it" in accepted
    # no Depends on line or relation for an after on a dropped item
    assert "An `(after W-k)` on a dropped W-k gets no `Depends on` line and no `--blocked-by` relation" in accepted
    assert "the item's other `after` items link as above" in accepted
    # the filed line names the cut
    assert "after a partial accept it names the dropped items" in accepted
    table = between(read(SKILL), "| PLAN_DUE |", "\n\n")
    assert "then `dropped: <ids>` after a partial accept" in table and "File the kept work (step 6)" in table


def test_s096_11_the_skill_asks_once_about_an_unclear_accept() -> None:
    answered = step("**PLAN_ANSWERED: do what the answer says**", "**PLAN_ACCEPTED")
    unclear = between(answered, "- `unclear accept: <rule>` (spec 096)", "**Answered in the session.**")
    assert "File nothing and revise nothing" in unclear
    assert "ask once through github-issue-triage's [needs-decision]" in unclear
    assert "quoting the answer's first line and the rule the note names" in unclear
    assert "with the two accept forms as options, and the `needs-decision` label" in unclear
    assert "PLAN_OPEN `unclear accept asked`" in unclear
    assert "Never pick the reading you think was meant" in unclear
    # a relay carries the new forms, read by the same grammar
    relay = between(answered, "**Answered in the session.**", "**PLAN_ACCEPTED")
    assert "`accept W-1, W-3`, `accept except W-2`" in relay
    assert "an unclear one as an unclear accept" in relay
    table = between(read(SKILL), "| PLAN_DUE |", "\n\n")
    assert "`unclear accept: <rule>`" in table and "`unclear accept asked`" in table


def test_s096_11_plan_due_never_proposes_a_dropped_item_unless_asked() -> None:
    due = step("**Dropped items stay dropped (spec 096).**", "**PLAN_ANSWERED")
    assert "a PLAN_DUE row's `dropped` lists each item an earlier plan for the goal dropped" in due
    assert "Never propose one of those items again for the goal, under any kind or wording" in due
    assert "name each under the new plan's Notes as left out (`W-2 of #752, dropped by the maintainer`)" in due
    assert "a `requested in #N` plan whose request names it, or an edit answer on the new plan" in due
    assert "A revision of the same plan follows the same rule" in due
    # it sits in step 6 with the PLAN_DUE step, before the answers
    skill = read(SKILL)
    assert (
        skill.index("**PLAN_DUE: propose.**")
        < skill.index("**Dropped items stay dropped")
        < skill.index("**PLAN_ANSWERED")
    )


def test_s096_12_plan_md_names_the_accept_forms_and_the_dropped_items() -> None:
    plan = read(PLAN)
    (triage,) = re.findall(
        r"```markdown\n(.*?)```", between(plan, "## Intake's triage line on the plan", "\n## "), re.S
    )
    assert "`accept` files every feature and fix item" in triage
    assert "`accept W-1, W-3` files only the items named and drops the rest" in triage
    assert "`accept except W-2` files all but the items named" in triage
    assert "a line starting with `decline` closes the plan" in triage and "anything else is read as an edit" in triage
    assert "The items most open to cutting" in triage
    filed_section = between(plan, "## Intake's line on the plan once filed", "\n## ")
    (filed,) = re.findall(r"```markdown\n(.*?)```", filed_section, re.S)
    assert filed.startswith("Triage: **plan**: accepted and filed: ")  # triage_state.py's goal_plan reads it
    assert "{; dropped: W-4, W-5}" in filed and "{; W-3 filed without its after W-4}" in filed
    assert "a full accept leaves the part out" in flat(filed_section)
    assert "implement" not in (triage + filed).lower()
