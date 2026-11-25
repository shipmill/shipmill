"""Spec 085: the skills write and keep to an issue's allowed files (S-085-11, S-085-12), text
checks over the files that say so"""

import re

from shipmill.bundle import skills_dir

TRIAGE = skills_dir() / "github-issue-triage" / "references"
RESOLVE = skills_dir() / "github-issue-resolve" / "SKILL.md"
LANDING = skills_dir() / "github-pr-triage" / "references" / "landing.md"
PR_GATE = skills_dir() / "github-pr-triage" / "scripts" / "pr_gate.py"


def section(text: str, heading: str) -> str:
    """The text under a `## ` heading, up to the next one"""
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def test_s085_11_the_implement_template_has_a_files_line_with_paths_in_backticks() -> None:
    implement = section((TRIAGE / "comments.md").read_text(encoding="utf-8"), "Implement")
    template = implement.split("```markdown\n", 1)[1].split("\n```", 1)[0]
    [line] = [line for line in template.splitlines() if line.startswith("- Files:")]
    assert re.fullmatch(r"- Files: `[^`]+`(, `[^`]+`)*", line), line
    assert template.index("The plan:") < template.index(line)


def test_s085_11_the_implement_template_says_a_build_issue_lists_its_spec_file() -> None:
    implement = section((TRIAGE / "comments.md").read_text(encoding="utf-8"), "Implement")
    assert "A spec's build issue lists its spec file, `docs/specs/NNN-<slug>.md`" in implement


def test_s085_11_a_proposed_plan_writes_its_files_paths_in_backticks() -> None:
    text = (TRIAGE / "autonomy.md").read_text(encoding="utf-8")
    [line] = [line for line in text.splitlines() if 'fix = "propose":' in line]
    assert "Its `Files:` line writes each path in backticks" in line
    assert "``Files: `src/shipmill/gate.py`, `tests/test_gate*.py` ``" in line


def test_s085_12_the_implementer_brief_passes_the_allowed_files_and_a_file_outside_is_a_decision() -> None:
    brief = (TRIAGE / "implementer-brief.md").read_text(encoding="utf-8")
    [line] = [line for line in brief.splitlines() if "Allowed files (spec 085)" in line]
    assert "the paths of the verdict's `Files:` line" in line
    assert 'A file outside them is a "decision for you": stop and report it, don\'t push it' in line


def test_s085_12_resolves_phase_4_keeps_the_plans_files_line_within_the_allowed_files() -> None:
    text = RESOLVE.read_text(encoding="utf-8")
    phase = text[text.index("\n## Phase 4: Implement\n") : text.index("\n## Phase 5:")]
    assert "- Files: {the files you expect to change, within the issue's allowed files}" in phase
    assert "the plan's `Files:` line stays within them" in phase


def test_s085_12_landing_asks_a_files_hold_with_the_needs_decision_question() -> None:
    text = LANDING.read_text(encoding="utf-8")
    [line] = [line for line in text.splitlines() if line.startswith("- **A `files:` hold**")]
    assert "Ask it with the needs-decision question on the pull request, naming each file outside" in line
    assert "never on a new verdict on the issue" in line


def test_s085_12_pr_gates_docstring_names_the_files_lines_and_exit_5() -> None:
    doc = PR_GATE.read_text(encoding="utf-8").split('"""', 2)[1]
    flat = " ".join(doc.split())  # its lines wrap anywhere, the lines' two leading spaces read as one
    assert "A path none covers reads NEEDS_DECISION, exit 5, ` files: <path> is outside what #A allows`" in flat
    assert "` files: and <k> more outside the allowed files`" in flat
    assert "` files: #N's allowed files can't be read: <why>`" in flat
