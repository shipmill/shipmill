"""Spec 050, The docs: the needs-decision protocol, the spec gate, the triage rubric, and
docs/flow.md name the agent marker and what a record carrying it never is"""

from pathlib import Path

from shipmill.agent_marker import MARKER

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ("skills", "github-issue-triage", "references")
AGENT_MARKER = "[agent marker](#the-agent-marker)"


def folded(*parts: str) -> str:
    """A doc with its line wrapping folded, so a statement reads as one line"""
    return " ".join(ROOT.joinpath(*parts).read_text(encoding="utf-8").split())


def section(text: str, heading: str) -> str:
    return text.split(f"## {heading} ", 1)[1].split(" ## ", 1)[0]


def test_s050_14_needs_decision_names_the_marker_who_adds_it_and_that_a_session_never_touches_it() -> None:
    marker = section(folded(*REFERENCES, "needs-decision.md"), "The agent marker")
    assert f"`shipmill gh` ends every body it writes with the line `{MARKER}`" in marker
    assert "as the App and as the host's login alike" in marker
    assert "A session never writes the marker itself and never removes it" in marker
    assert "it is never a reply and never a veto" in marker
    assert "(a deleted account) is neither a reply nor a veto" in marker


def test_s050_14_both_rows_of_the_reply_table_and_the_veto_rule_name_the_marker() -> None:
    text = folded(*REFERENCES, "needs-decision.md")
    rows = [line for line in section(text, "While it waits").split(" | ") if line.startswith("A newer comment by")]
    assert len(rows) == 2
    assert all(row.endswith(f"without the marker and without the {AGENT_MARKER}") for row in rows), rows
    veto = section(text, "Taking up a veto")
    assert f"whose first word is `veto` in any case and which doesn't carry the {AGENT_MARKER}" in veto
    assert "a comment carrying the agent marker, a deleted account's comment" in veto


def test_s050_14_the_relay_line_is_written_in_both_modes_and_is_no_reply() -> None:
    answered = section(folded(*REFERENCES, "needs-decision.md"), "Answered in the session")
    assert (
        "Posted as the App (`shipmill gh` with `[agents] app_id` set) or as the host's login"
        ' (`shipmill gh` with `[agents] identity = "host"`), its first line names who decided' in answered
    )
    assert "```markdown Decision by `@<login>`, relayed by <agent> Answered in the session:" in answered
    assert "so the relay is no reply: removing the label in the next step is what moves the item" in answered


def test_s050_14_the_spec_gate_and_the_rubric_say_a_marked_issue_is_not_the_maintainers_filing() -> None:
    phrase = "is not the maintainer's filing, whatever its author association"
    gate = folded(*REFERENCES, "spec-gate.md").split("**An issue the maintainer filed**", 1)[1].split(" - **", 1)[0]
    assert f"An issue whose body carries the agent marker (`{MARKER}` on any line" in gate
    assert phrase in gate
    rubric = folded(*REFERENCES, "triage-rubric.md")
    feature = rubric.split("| **feature** |", 1)[1].split(" | ", 1)[0]
    assert f"one whose body carries the agent marker `{MARKER}` {phrase}" in feature
    capability = section(rubric, "A new capability: opportunity or feature")
    assert f"An issue whose body carries the agent marker (`{MARKER}` on any line" in capability
    assert f"{phrase}: an agent wrote it, so unless it is an accepted opportunity it goes to step 3" in capability


def test_s050_14_flow_names_the_rule_where_it_describes_decisions() -> None:
    decides = section(folded("docs", "flow.md"), "Who decides")
    assert "An agent's text is told from a person's by its marker, never by its author (spec 050, D-62)" in decides
    assert f"`shipmill gh` ends every body it writes with `{MARKER}`" in decides
