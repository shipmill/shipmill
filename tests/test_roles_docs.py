"""Spec 036, #643: the skills' docs describe roles, ASSIGN_DUE, the maintainer fallback, the
team mention, and filing a step with role:<name> assigned at once"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TRIAGE = ROOT / "skills" / "github-issue-triage"
TRIAGE_DOCS = (
    TRIAGE / "SKILL.md",
    TRIAGE / "references" / "triage-rubric.md",
    TRIAGE / "references" / "comments.md",
    TRIAGE / "references" / "spec-gate.md",
    TRIAGE / "references" / "needs-decision.md",
)


def folded(path: Path) -> str:
    """A file with its line wrapping folded, so a statement reads as one line"""
    return " ".join(path.read_text(encoding="utf-8").split())


def section(text: str, heading: str) -> str:
    """The body of a `## <heading>` section in a folded text, up to the next `## `"""
    assert f"## {heading} " in text, heading
    return text.split(f"## {heading} ", 1)[1].split(" ## ", 1)[0]


@pytest.mark.parametrize("path", TRIAGE_DOCS, ids=lambda p: p.name)
def test_s036_16_each_triage_doc_names_role_labels_and_the_maintainer(path: Path) -> None:
    text = folded(path)
    assert "role:<name>" in text, path.name
    assert "role:maintainer" in text, path.name


def test_s036_16_the_rubric_reads_assign_due_the_fallback_and_teams() -> None:
    person = section(folded(TRIAGE / "references" / "triage-rubric.md"), "A person's item")
    assert "| ASSIGN_DUE |" in person
    assert "`assign @a @b (role:infra)`" in person and "`assign` list" in person
    assert "gh issue edit <n> --add-assignee" in person
    assert "Read while a hold is still open too" in person
    # the maintainer fallback: the listed users, else the host's gh login; [] and undefined fall back
    assert "`[agents.roles] maintainer` lists, or with nobody listed the host's `gh` login" in person
    assert "A role set to `[]` resolves to the maintainer's fillers" in person
    assert "`role:<name> undefined`" in person and "union of their fillers" in person
    # teams: mentioned, never assigned, and the --json lists
    assert "GitHub can't assign a team" in person
    assert "`for @a @example-org/legal`" in person and "a `teams` list" in person
    # NO_ASSIGNEE no longer asks: it means the flags weren't given
    no_assignee = person.split("| NO_ASSIGNEE |", 1)[1].split(" | BLOCKED |", 1)[0]
    assert "without the `--role` flags" in no_assignee and "never asks who does a step" in no_assignee
    assert "Asks the maintainer who does it" not in person
    # human still reads, as role:maintainer
    assert "`human`" in person and "counts as `role:maintainer`" in person
    flags = section(folded(TRIAGE / "references" / "triage-rubric.md"), "Flags from `triage_state.py`")
    assert "| ASSIGN_DUE |" in flags


def test_s036_16_the_skill_names_assign_due_and_the_flags() -> None:
    skill = folded(TRIAGE / "SKILL.md")
    assert "ASSIGN_DUE" in skill and "`shipmill roles --flags`" in skill
    chains = section(skill, "Chains")
    assert "ASSIGN_DUE assigns the users its note names" in chains
    assert "falls back to the maintainer" in chains and "host's `gh` login" in chains
    assert "a team can't be assigned" in chains
    assert "assigned that role's users at once" in chains


def test_s036_16_the_hand_off_mentions_the_teams() -> None:
    comments = folded(TRIAGE / "references" / "comments.md")
    person = section(comments, "A person's item")
    assert "**ASSIGN_DUE** gets no comment" in person
    handoff = person.split("**HANDOFF_DUE**", 1)[1].split("**VERIFY_DUE**", 1)[0]
    assert "every team its roles resolve to" in handoff and "@{org/team}" in handoff
    assert "a team-only role's item mentions the team alone" in handoff
    no_assignee = comments.split("**NO_ASSIGNEE**", 1)[1].split("## A parent's close", 1)[0]
    assert "For NO_ASSIGNEE, ask who does the item" not in no_assignee
    assert "gets no comment and no question" in no_assignee and "so a session never asks" in no_assignee


def test_s036_16_a_step_is_filed_with_its_role_and_assigned_at_once() -> None:
    gate = folded(TRIAGE / "references" / "spec-gate.md")
    step = gate.split("**A step only a person can do**", 1)[1].split(" - **", 1)[0].split(" ## ", 1)[0]
    assert "First read the roles, `shipmill roles` through the CLI the skill pins" in step
    assert "with no role that clearly fits, `role:maintainer`" in step
    assert "Label the issue `role:<name>` and assign that role's users at once" in step
    assert "A role filled by teams only is labelled and left unassigned: the hand-off mentions the team" in step
    assert "Never ask who does it" in step and "never write the older `human` label" in step


def test_s036_16_needs_decision_is_never_asked_who_does_a_step() -> None:
    text = folded(TRIAGE / "references" / "needs-decision.md")
    assert "**Who does a step is not a question.**" in text
    rule = text.split("**Who does a step is not a question.**", 1)[1].split(" ## ", 1)[0]
    assert "falls back to the maintainer" in rule and "the host's `gh` login" in rule
    assert "ASSIGN_DUE" in rule and "never NO_ASSIGNEE" in rule
    assert "A team is mentioned in the hand-off, never assigned" in rule
    assert "Only an assignment GitHub refuses comes here" in rule
    never = text.split("**`never`:**", 1)[1]
    assert "label it `role:maintainer`" in never


def test_s036_16_setup_documents_agents_roles_and_its_labels() -> None:
    setup = folded(ROOT / "skills" / "shipmill-setup" / "SKILL.md")
    assert "**Roles (spec 036).**" in setup
    roles = setup.split("**Roles (spec 036).**", 1)[1].split(" **The product's direction", 1)[0]
    assert "[agents.roles] maintainer = [" in roles and '"@example-org/legal"' in roles
    assert "accounting = []" in roles
    assert "`[a-z0-9][a-z0-9-]{0,44}`" in roles and "`@<org>/<team-slug>`" in roles
    assert "the maintainer is the host's `gh` login" in roles
    assert "agent-filled roles aren't supported yet" in roles
    assert "`$CR roles`" in roles and "`--flags`" in roles and "`--json`" in roles
    assert "`setup_state.py --fix` creates `role:maintainer` and a `role:<name>` label" in roles
    # the checklist and the label bullet name the role labels next to needs-decision
    assert setup.count("`role:maintainer` and `role:<name>` for each role `[agents.roles]` defines") == 2


def test_s036_16_flow_and_install_call_it_a_role_s_item() -> None:
    flow = folded(ROOT / "docs" / "flow.md")
    assert "| ASSIGN_DUE | A role's item" in flow
    assert "a person's part is a role's item" in flow
    install = folded(ROOT / "docs" / "install.md")
    assert "a `role:<name>` label for each role `[agents.roles]` defines, a role's item" in install
