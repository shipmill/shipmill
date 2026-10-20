"""product-intake's skill files an accepted goal plan, and the spec gate takes its features
(spec 028, #517): the skill text, its template, and the commands it names"""

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
GATE = ROOT / "skills" / "github-issue-triage" / "references" / "spec-gate.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def flat(text: str) -> str:
    """Prose with its line breaks folded, so a phrase may wrap"""
    return re.sub(r"\s+", " ", text)


def between(text: str, start: str, end: str) -> str:
    head = text.index(start)
    tail = text.find(end, head + len(start))
    return text[head : tail if tail != -1 else len(text)]


def fenced(text: str, language: str = "markdown") -> list[str]:
    return re.findall(rf"```{language}\n(.*?)```", text, re.S)


@pytest.fixture(scope="module")
def plans() -> ModuleType:
    spec = importlib.util.spec_from_file_location("plans_skill", INTAKE / "scripts" / "plans.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def plan_step() -> str:
    return flat(between(read(SKILL), "### 6. Plan a goal", "\n## "))


def test_s028_15_the_skill_files_each_feature_and_fix_item_in_work_order() -> None:
    step = plan_step()
    accepted = between(step, "**PLAN_ACCEPTED: file the work.**", "Filing starts no work")
    assert "for each `feature` and `fix` item still `null`, in Work order" in accepted
    assert "`plans.py items <owner/repo>#P --bot-login '<slug>[bot]' --json`" in accepted
    assert "never files one twice" in accepted
    # the marker, the goal, and the plan's link
    assert "the plan-item marker `<!-- shipmill:plan-item #P W-n -->`" in accepted
    assert "`Serves: G-n`" in accepted
    # a sub-issue of the plan, without an edit to the plan's body
    assert "sub-issue of the plan" in accepted
    assert "shipmill gh api -X POST repos/<owner/repo>/issues/<P>/sub_issues -F sub_issue_id=<id>" in accepted
    assert "Not `chains.py link --child`" in accepted
    # (after W-k): a Depends on line and GitHub's relation, through chains.py link
    assert "a `Depends on owner/repo#M` line per `(after W-k)`" in accepted
    assert "`chains.py link <owner/repo>#<item> --blocked-by <owner/repo>#M`" in accepted
    assert "GitHub's relation" in accepted
    # the milestone the plan names (D-38), and none for `none`
    assert "creating the milestone first" in accepted and "D-38" in accepted
    assert "A plan naming `none` touches no milestone" in accepted
    # no implementer, no spec
    assert "Filing starts no work: dispatch no implementer and write no spec" in step


def test_s028_15_the_filed_item_template_carries_the_marker_plans_py_reads(plans: ModuleType) -> None:
    text = read(PLAN)
    item = between(text, "## A filed item", "\n## Intake's line")
    body = fenced(item)[0]
    lines = body.splitlines()
    assert lines[0] == "<!-- shipmill:plan-item #{plan} W-{n} -->"
    # the same form plans.py and intake_state.py read, once filled in
    filled = lines[0].replace("{plan}", "41").replace("{n}", "2")
    assert filled == plans.item_marker(41, "W-2")
    assert "Serves: G-{n}" in body and "#{plan}" in body
    assert "Depends on {owner/repo}#{the issue of W-k}" in body
    assert "One `Depends on` line per `(after W-k)`" in item


def test_s028_15_the_commands_the_skill_names_exist() -> None:
    plans_doc = read(INTAKE / "scripts" / "plans.py")
    assert "plans.py items <owner/repo>#N [--bot-login LOGIN] [--json]" in plans_doc
    assert "plans.py check FILE [--root DIR]" in plans_doc
    chains = read(ROOT / "skills" / "github-issue-triage" / "scripts" / "chains.py")
    assert "chains.py link <owner/repo#N> --blocked-by <owner/repo#M>" in chains
    intake = read(INTAKE / "scripts" / "intake_state.py")
    for flag in ("--plans", "--wip N", "--bot-login LOGIN"):
        assert flag in intake, flag
    # every plan state the skill's table lists is one the script prints, and the reverse
    skill = read(SKILL)
    table = between(skill, "| PLAN_DUE |", "\n\n")
    listed = re.findall(r"^\| (PLAN_[A-Z]+) \|", table, re.M)
    printed = re.findall(r'^    "(PLAN_[A-Z]+)",$', intake, re.M)
    assert listed and sorted(listed) == sorted(printed)


def test_s028_15_the_plan_template_passes_plans_py_check(plans: ModuleType) -> None:
    body = fenced(between(read(PLAN), "## The plan issue", "\n## Intake's triage"))[0]
    filled = body.replace("{n}", "3").replace("{k}", "1").replace("#N", "#7")
    filled = re.sub(r"\{[^}]*\}", "text", filled)
    plan, problems = plans.parse(filled, frozenset({"G-3"}))
    assert problems == [] and plan is not None
    assert [(i.id, i.kind, i.after) for i in plan.items] == [
        ("W-1", "existing", ()),
        ("W-2", "feature", ()),
        ("W-3", "fix", ("W-2",)),
    ]


def test_s028_16_the_spec_gate_lists_an_accepted_plan_s_feature_item() -> None:
    sources = flat(between(read(GATE), "## Where features come from", "\n## "))
    item = between(sources, "**A feature item of an accepted plan:**", " - **")
    assert "`<!-- shipmill:plan-item #P W-n -->`" in item
    assert "PLAN_ACCEPTED or PLAN_FILED" in item
    assert "chose the work, not its design" in item
    assert "it still needs its own spec, merged with `status: approved` before its build" in item
    # the source sits with the other chosen work, ahead of the opportunity hand-off
    assert sources.index("**A feature item of an accepted plan:**") < sources.index("Any other request")


def test_s028_17_the_skill_never_decides_a_plan_without_a_trusted_answer() -> None:
    skill = flat(read(SKILL))
    rule = between(skill, "9. **A plan changes only on the maintainer's answer", "## The script")
    assert "Never accept, decline, or edit a plan without a trusted answer" in rule
    assert "OWNER, MEMBER, or COLLABORATOR other than the `--bot-login`" in rule
    assert "A reaction, a label, an untrusted comment, or your own judgment is no answer" in rule
    assert "Never add a goal or edit `docs/product.md` for a plan" in rule
    answered = between(plan_step(), "**PLAN_ANSWERED: do what the answer says**", "**PLAN_ACCEPTED")
    assert "and only that (rule 9)" in answered
    assert "is reported, not done" in answered
    # every comment intake writes on a plan is a session's own, never read as an answer
    for block in fenced(read(PLAN)):
        if block.startswith(("<!-- shipmill:plan ", "<!-- shipmill:plan-item")):
            continue  # an issue body, not a comment
        assert block.startswith(("Triage:", "<!-- shipmill:plan-revised")), block
        assert "implement" not in block.lower(), block


def test_s028_17_observe_reports_a_due_plan_s_text_and_opens_nothing() -> None:
    skill = flat(read(SKILL))
    autonomy = between(skill, "| `observe` |", "| `propose`")
    assert "each PLAN_DUE goal with the plan's proposed text" in autonomy
    assert "no plan issue, no comment, no filed item" in autonomy
    due = between(plan_step(), "**PLAN_DUE: propose.**", "**PLAN_ANSWERED")
    assert "Under `observe`, open nothing and comment nothing" in due
    assert "put the goal, its trigger, and the plan's full proposed body in the report" in due
    assert "Under `propose`, open it as the plan issue" in due
    assert "under `observe` each due plan's proposed text" in between(skill, "## Report", "## Improve the skill")
