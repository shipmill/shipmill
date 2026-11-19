"""Spec 077's documents: rule-proposal.md, the weekly retro, needs-decision.md's taking up of a
rule-proposal issue, and shipmill-setup's labels, read as text, and the template checked with
retro.py's own proposal check"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
WATCH = ROOT / "skills" / "github-ship-watch"
RULE_PROPOSAL = WATCH / "references" / "rule-proposal.md"
WATCH_SKILL = WATCH / "SKILL.md"
NEEDS_DECISION = ROOT / "skills" / "github-issue-triage" / "references" / "needs-decision.md"
SETUP = ROOT / "skills" / "shipmill-setup"
SHA = "a" * 40


def load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def retro() -> ModuleType:
    scripts = str(WATCH / "scripts")
    sys.path.insert(0, scripts)  # retro imports metrics, as when run from its folder
    try:
        return load(WATCH / "scripts" / "retro.py", "retro_rule_proposal_docs")
    finally:
        sys.path.remove(scripts)


@pytest.fixture(scope="module")
def ss() -> ModuleType:
    return load(SETUP / "scripts" / "setup_state.py", "setup_state_rule_proposal_docs")


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(body: str, heading: str, level: int = 2) -> str:
    marks = "#" * level
    found = re.search(rf"^{marks} {re.escape(heading)}\n(.*?)(?=^#{{1,{level}}} |\Z)", body, re.MULTILINE | re.DOTALL)
    assert found is not None, heading
    return found.group(1)


def flat(body: str) -> str:
    """The prose with its line breaks and runs of spaces as single spaces"""
    return " ".join(body.split())


def template() -> str:
    """The body template, the one ````markdown block, right under The body's heading and prose"""
    doc = text(RULE_PROPOSAL)
    found = re.findall(r"^````markdown\n(.*?)^````$", doc, re.MULTILINE | re.DOTALL)
    assert len(found) == 1 and doc.index("## The body\n") < doc.index("````markdown") < doc.index("## Filing it\n")
    return str(found[0])


# -- S-077-10: the template, the places, and filing -------------------------------------------


def test_s077_10_the_template_has_the_six_sections_and_no_check(retro: ModuleType) -> None:
    body = template()
    headings = re.findall(r"^## (.+)$", body, re.MULTILINE)
    assert headings == ["Rule", "Raised in", "Place", "Enforced by", "Shown failing", "On the default branch"]
    assert body.startswith("<!-- shipmill:rule-proposal pulls=41,57 place=lint -->\n")
    assert "## Check" not in body
    # filled in, the template is a body retro.py proposal takes
    filled = body.replace("<the full 40-character SHA, a head #41 was reviewed on>", SHA)
    filled = filled.replace("<its non-zero exit code>", "1")
    assert retro.proposal_fault(filled) is None
    assert retro.proposal_title(filled) == "Rule: In apps/api the dev script is start:dev, not dev"
    # and the prose form names Why prose in their place
    doc = flat(text(RULE_PROPOSAL))
    assert "`place=prose`" in doc and "a `## Why prose` section" in doc
    assert "No section is named `## Check`" in doc


def test_s077_10_the_place_is_the_first_one_the_repos_ci_can_hold() -> None:
    place = flat(section(text(RULE_PROPOSAL), "The place"))
    assert "in this order: a lint rule, a type, an import contract, a test, then prose" in place
    assert "The place is the first one a tool the repo's CI already runs can hold" in place
    assert "Prose is the place only when no check can hold the finding" in place


def test_s077_10_only_a_body_proposal_exits_0_on_is_filed_as_the_app_with_both_labels() -> None:
    filing = flat(section(text(RULE_PROPOSAL), "Filing it"))
    assert "scripts/retro.py proposal <file> --repo <owner/repo>" in filing
    assert (
        "File only a body `retro.py proposal` exits 0 on, as the App, with the labels `rule-proposal` and"
        " `needs-decision`" in filing
    )
    assert "`shipmill gh issue create" in filing and "--label rule-proposal --label needs-decision" in filing
    assert "`DUPLICATE #N (<state>): <title>`" in filing and "`FULL: K proposals wait on an answer`" in filing


# -- S-077-11: shown failing in a throwaway worktree -----------------------------------------


def test_s077_11_the_check_runs_in_a_throwaway_worktree_at_a_trusted_head_and_pushes_nothing() -> None:
    shown = flat(section(text(RULE_PROPOSAL), "Shown failing"))
    assert "Pick a head a finding of the group was raised on" in shown
    assert (
        "Use only a head of a merged pull request, or of one opened by the App or an OWNER, MEMBER, or COLLABORATOR"
        in shown
    )
    assert "never run an outsider's unmerged code (D-16)" in shown
    assert "Make a throwaway worktree of the repo, detached at that head" in shown
    assert "A check that doesn't fail there is not proposed as that place" in shown
    assert "Remove the worktree" in shown and "with no branch, commit, or pull request pushed to the repo" in shown


# -- S-077-12: the weekly retro --------------------------------------------------------------


def test_s077_12_the_weekly_retro_proposes_recurring_findings_and_never_edits_the_repos_rules() -> None:
    retro_section = section(text(WATCH_SKILL), "Weekly retro")
    steps = {int(m.group(1)): flat(m.group(2)) for m in re.finditer(r"^(\d)\. (.*)$", retro_section, re.MULTILINE)}
    assert steps[1].startswith("Gather:")
    found = steps[2]
    assert found.startswith("Recurring findings") and "(references/rule-proposal.md)" in found
    assert "`scripts/retro.py findings <owner/repo>" in found
    assert "a group spanning two or more pull requests is a recurring finding" in found
    assert "Drop a group for one of three reasons: an earlier proposal in any state states the same rule" in found
    assert "a check the default branch already runs refuses it" in found
    assert "already says it where no check can hold it" in found
    assert "propose at most three per retro" in found
    assert "Step 3's change proposals no longer come from review findings" in steps[3]
    closing = next(p for p in retro_section.split("\n\n") if p.startswith("The retro writes only"))
    for never in ("`REVIEW.md`", "`CLAUDE.md`", "`AGENTS.md`", "the repo's checks", "its CI workflows"):
        assert never in flat(closing), never
    assert "never edits `REVIEW.md`" in flat(closing)


# -- S-077-13: the question and taking up the answer -----------------------------------------


def test_s077_13_rule_proposal_md_holds_the_question_with_zone_unknown() -> None:
    question = section(text(RULE_PROPOSAL), "The question")
    block = re.search(r"^```markdown\n(.*?)^```$", question, re.MULTILINE | re.DOTALL)
    assert block is not None
    lines = block.group(1).splitlines()
    assert lines[:2] == ["<!-- shipmill:needs-decision -->", "<!-- shipmill:zone unknown -->"]
    assert lines[2].startswith("@<login> Decision needed: should this repo hold the rule")
    assert lines[4].startswith("1. Accept (recommended): you add it") and "shipmill writes none of it" in lines[4]
    assert lines[5].startswith("2. Decline: shipmill closes this as not planned and never proposes this rule again")


def test_s077_13_needs_decision_md_takes_up_a_rule_proposal_issue() -> None:
    taking = flat(section(text(NEEDS_DECISION), "Taking up an answered item"))
    paragraph = taking[taking.index("On an issue labelled `rule-proposal`") :]
    assert "references/rule-proposal.md#taking-up-the-answer" in paragraph
    assert "An accept removes `needs-decision`, adds `role:maintainer`, and assigns the maintainer's users" in paragraph
    assert "posts no **implement** verdict" in paragraph
    assert (
        "A decline comments the reason as given and closes the issue as not planned, with the `rule-proposal`"
        " label kept" in paragraph
    )
    # the anchor it links is rule-proposal.md's own section, which says the same
    answer = flat(section(text(RULE_PROPOSAL), "Taking up the answer"))
    assert "remove `needs-decision`, label the issue `role:maintainer`, and assign the maintainer's users" in answer
    assert "Post no **implement** verdict" in answer and "The `rule-proposal` label stays" in answer


# -- S-077-14: setup creates the label -------------------------------------------------------


def test_s077_14_setup_lists_and_creates_the_rule_proposal_label(ss: ModuleType, tmp_path: Path) -> None:
    skill = flat(text(SETUP / "SKILL.md"))
    assert "`rule-proposal`, the weekly retro's proposed rule for a recurring finding, spec 077" in skill
    assert "and `rule-proposal` (the weekly retro's proposed rule for a recurring finding, spec 077)" in skill
    (tmp_path / ".github").mkdir()
    config = tmp_path / ".github" / "shipmill.toml"
    config.write_text('mode = "off"\n\n[agents]\nprompt = "/t"\n', encoding="utf-8")
    assert "rule-proposal" in ss.wanted_labels(tmp_path)
    config.write_text('mode = "off"\n', encoding="utf-8")
    assert "rule-proposal" not in ss.wanted_labels(tmp_path)  # without [agents] none is wanted
