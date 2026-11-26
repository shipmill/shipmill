"""Spec 087, #1651: a role:maintainer item (or a human one) runs interactively. Its hand-off
names the command that opens an interactive session on it, and the gate hands it to no
headless session to work it: triage_state.py reads it only in a person's states, which a
session answers with a comment, never in a state a session builds or lands"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from .test_triage_human import SCRIPT, classify, handoff, person, said

ROOT = Path(__file__).resolve().parents[1]
COMMENTS = ROOT / "skills" / "github-issue-triage" / "references" / "comments.md"
SPEC = ROOT / "docs" / "specs" / "087-headless-sandbox.md"
COMMAND = 'claude "/shipmill:github-issue-resolve {owner/repo}#{N}"'
# A person's states: each is a comment, an assignment, or a close by a triage session, or no action
PERSON_STATES = frozenset(
    {"ASSIGN_DUE", "NO_ASSIGNEE", "HANDOFF_DUE", "WITH_PERSON", "VERIFY_DUE", "BLOCKED", "STALE_HANDOFF"}
)
MAINTAINER_LABELS = ("role:maintainer", "human", "Role:Maintainer", "HUMAN")


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    spec = importlib.util.spec_from_file_location("triage_state_s087", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_s087_28_the_hand_off_of_a_maintainer_item_names_the_interactive_command() -> None:
    comments = COMMENTS.read_text(encoding="utf-8")
    handoff_section = comments.split("**HANDOFF_DUE**", 1)[1].split("**VERIFY_DUE**", 1)[0]
    template = handoff_section.split("```markdown", 1)[1].split("```", 1)[0]
    assert f"`{COMMAND}`" in template
    # only for role:maintainer or human, and run in the repo's checkout
    condition = template.split(f"`{COMMAND}`", 1)[0].rsplit("{When", 1)[1]
    assert "role:maintainer" in condition and "human" in condition and "checkout" in condition
    # the prose says why, and that no headless session works it
    prose = handoff_section.split("```markdown", 1)[0]
    assert '`claude "/shipmill:github-issue-resolve <owner>/<repo>#<n>"`' in prose
    assert "never handed to a headless session" in prose
    # the spec this follows
    spec = " ".join(SPEC.read_text(encoding="utf-8").split())
    assert "the gate never hands to a headless session" in spec
    assert '`claude "/shipmill:github-issue-resolve <owner>/<repo>#<n>"`' in spec


@pytest.mark.parametrize("label", MAINTAINER_LABELS)
def test_s087_28_the_gate_hands_a_maintainer_item_to_no_session_that_works_it(ts: ModuleType, label: str) -> None:
    labels = (label,)
    verdict = said("Triage: implement. The fix is in gate.py.", "2026-09-01T10:00:00Z")
    pr = {"nodes": [{"willCloseTarget": True, "source": {"number": 8, "state": "OPEN"}}]}
    merged = {"nodes": [{"willCloseTarget": True, "source": {"number": 9, "state": "MERGED"}}]}
    untriaged = person(labels=labels)
    triaged = person([verdict], labels=labels)
    with_pr = person([verdict], labels=labels)
    with_pr["timelineItems"] = pr
    with_merged = person([verdict], labels=labels)
    with_merged["timelineItems"] = merged
    handed = person([handoff("2026-09-05T10:00:00Z")], labels=labels)
    nobody = person(people=(), labels=labels)
    roles = ts.parse_roles(["maintainer=maria"])
    reads = [
        classify(ts, untriaged),
        classify(ts, triaged),
        classify(ts, with_pr),
        classify(ts, with_merged),
        classify(ts, handed),
        classify(ts, nobody),
        ts.classify_open(nobody, "Triage:", "postponed", {}, None, ("o", "r"), "shipmill-gate[bot]", {}, roles=roles),
    ]
    states = [state for state, _ in reads]
    assert states == [
        "HANDOFF_DUE",
        "HANDOFF_DUE",
        "HANDOFF_DUE",
        "HANDOFF_DUE",
        "WITH_PERSON",
        "NO_ASSIGNEE",
        "ASSIGN_DUE",
    ]
    assert set(states) <= PERSON_STATES
    # none of the states a session builds, resumes, or lands
    for working in ("NEW", "UNBLOCKED", "NEEDS_PR", "IN_PROGRESS", "AGENT_DRAFT", "DONE_NOT_CLOSED"):
        assert working not in states
