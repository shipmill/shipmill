"""Spec 012, Skills, Relayed decisions, and Docs: the skills route every write through
`shipmill gh`, a relayed answer names who decided, and the setup docs document it"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRITING_SKILLS = (
    "github-issue-triage",
    "github-issue-resolve",
    "github-pr-triage",
    "github-ship-watch",
    "product-intake",
    "shipmill-setup",
)
RELAYED = "Decision by `@<login>`, relayed by <agent>"  # the login in a code span (D-61, #771)
BARE_RELAYED = "Decision by @<login>, relayed by <agent>"


def folded(*parts: str) -> str:
    """A doc with its line wrapping folded, so a statement reads as one line"""
    return " ".join(ROOT.joinpath(*parts).read_text(encoding="utf-8").split())


def test_s012_5_the_six_skills_are_every_skill_that_writes() -> None:
    assert {path.parent.name for path in (ROOT / "skills").glob("*/SKILL.md")} == set(WRITING_SKILLS)


@pytest.mark.parametrize("skill", WRITING_SKILLS)
def test_s012_5_each_skill_writes_through_shipmill_gh_in_every_session(skill: str) -> None:
    text = folded("skills", skill, "SKILL.md")
    assert text.count("**Write as the App when the repo has one") == 1, "said once, in one place"
    rule = text.split("**Write as the App when the repo has one", 1)[1][:900]  # the rule itself, not the rest
    for phrase in (
        "`[agents] app_id` set" if skill == "shipmill-setup" else "sets `[agents] app_id`",
        "every `gh` call that writes",
        "runs as `shipmill gh <the same arguments>`",
        "in every session, gated or started by hand",
        "Reads may keep plain `gh`",
        "A `shipmill gh` that exits 2 is a stop",
        "never retry the write with plain `gh`",
    ):
        assert phrase in rule, (skill, phrase)


@pytest.mark.parametrize("skill", [s for s in WRITING_SKILLS if s != "shipmill-setup"])
def test_s012_5_a_headless_session_gets_a_form_its_allowlist_allows(skill: str) -> None:
    # the headless gate allows Bash(uvx *) and no bare shipmill, so the rule names the uvx form,
    # pinned to the plugin's own release (spec 031)
    text = folded("skills", skill, "SKILL.md")
    version = json.loads(ROOT.joinpath(".claude-plugin", "plugin.json").read_text(encoding="utf-8"))["version"]
    assert f"`uvx shipmill=={version} gh ...`" in text
    assert "Bash(uvx *)" in text


@pytest.mark.parametrize("name", ["needs-decision.md", "comments.md"])
def test_s012_6_a_relayed_answer_names_who_decided(name: str) -> None:
    text = folded("skills", "github-issue-triage", "references", name)
    assert f"``{RELAYED}``" in text or f"```markdown {RELAYED} " in text
    assert "```markdown Decision by @" not in text, "the template writes the login in a code span"
    assert "(`Claude Code`)" in text
    assert "`shipmill gh` with `[agents] app_id` set" in text


def test_s012_6_the_relayed_line_is_the_answer_comments_first_line() -> None:
    ref = folded("skills", "github-issue-triage", "references", "needs-decision.md")
    answered = ref.split("## Answered in the session", 1)[1].split(" ## ", 1)[0]
    assert f"```markdown {RELAYED} Answered in the session:" in answered
    comments = folded("skills", "github-issue-triage", "references", "comments.md")
    assert "```markdown Decision by `@{login}`, relayed by {agent} {The option chosen" in comments


@pytest.mark.parametrize("name", ["needs-decision.md", "comments.md"])
def test_s012_6_an_older_bare_relay_line_still_reads_as_the_answer(name: str) -> None:
    text = folded("skills", "github-issue-triage", "references", name)
    assert "a reader" in text and "older line with the login bare" in text
    assert f"`{BARE_RELAYED}`" in text or "`Decision by @<login>`" in text


def test_s012_6_no_skill_keeps_its_own_copy_of_the_references() -> None:
    for name in ("needs-decision.md", "comments.md"):
        copies = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "skills").rglob(name))
        assert copies == [f"skills/github-issue-triage/references/{name}"]


@pytest.mark.parametrize("skill", WRITING_SKILLS)
def test_s037_12_each_skills_rule_names_the_refusal_without_app_id(skill: str) -> None:
    text = folded("skills", skill, "SKILL.md")
    rule = text.split("**Write as the App when the repo has one", 1)[1].split("Without the App, shipmill drafts", 1)[0]
    for phrase in (
        "Without `app_id`, `shipmill gh` refuses a write with exit 2",
        'unless the config sets `[agents] identity = "host"` (spec 037)',
        "that exit 2 is a stop too, never retried with plain `gh`",
        "passes `--as-host` only for a write a person approved in the chat",
        "never on its own judgment or in a headless session",
    ):
        assert phrase in rule, (skill, phrase)


@pytest.mark.parametrize(
    ("doc", "state", "write"),
    [
        (("skills", "github-issue-triage", "SKILL.md"), "**SUSPECT_CLOSE:**", "`shipmill gh issue comment"),
        (("skills", "github-issue-triage", "SKILL.md"), "**OFF_MILESTONE:**", "`shipmill gh issue edit"),
        (("skills", "github-ship-watch", "SKILL.md"), "| MILESTONE_OVERTAKEN |", "`shipmill gh api -X PATCH"),
    ],
)
def test_s037_12_the_rows_name_shipmill_gh_only_with_app_id_set(doc: tuple[str, ...], state: str, write: str) -> None:
    row = folded(*doc).split(state, 1)[1].split(" - **", 1)[0].split(" | ", 1)[0]
    after = row.split(write, 1)[1]
    assert after.split("`", 1)[1].startswith(" with `[agents] app_id` set, plain `gh` without it"), row


def test_s037_12_install_documents_the_refusal_identity_and_as_host() -> None:
    text = folded("docs", "install.md")
    for phrase in (
        "`shipmill gh` runs a read",
        "refuses a write: exit 2",
        'set `identity = "host"` in `[agents]`',
        "`shipmill gh --as-host <the same arguments>`",
        "only for a write a person approved in the chat",
    ):
        assert phrase in text, phrase


def test_s037_12_shipmill_help_describes_gh_without_app_id() -> None:
    done = subprocess.run([sys.executable, "-m", "shipmill", "--help"], capture_output=True, text=True, check=True)
    text = " ".join(done.stdout.split())
    assert "else as the host's gh login" not in text  # spec 012's step 3, superseded by spec 037
    assert 'a write exits 2 unless [agents] identity = "host" or a leading --as-host allows it (spec 037)' in text


def test_s037_12_release_lanes_lists_agents_identity() -> None:
    text = folded("docs", "release-lanes.md")
    assert "`[agents] identity`" in text
    assert 'identity = "host" # agent writes through shipmill gh' in text


@pytest.mark.parametrize("doc", [("docs", "install.md"), ("skills", "shipmill-setup", "SKILL.md")])
def test_s012_9_the_setup_docs_document_shipmill_gh(doc: tuple[str, ...]) -> None:
    text = folded(*doc)
    assert "`shipmill gh" in text or "`$CR gh" in text
    assert "runs `gh` as the App" in text or "shipmill gh issue comment" in text
    assert "`$XDG_CACHE_HOME/shipmill/<owner>/<repo>/app-token.json`" in text
    assert "(`~/.cache` when `XDG_CACHE_HOME` is unset)" in text
    assert "The App's identity covers the sessions" in text
    assert "you start yourself too" in text or "a person starts too" in text
    assert "exits 2" in text and "never runs" in text
