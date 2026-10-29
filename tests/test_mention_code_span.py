"""#771, D-61: a bare @login, which GitHub turns into an email, appears in shipmill's GitHub
text only in a needs-decision question, a person's hand-off, and a notify decision's decided
comment; everywhere else the login is in a code span, and the readers take both forms"""

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
COMMENTS = SKILLS / "github-issue-triage" / "references" / "comments.md"
NEEDS_DECISION = SKILLS / "github-issue-triage" / "references" / "needs-decision.md"
SPEC_GATE = SKILLS / "github-issue-triage" / "references" / "spec-gate.md"
TRIAGE = SKILLS / "github-issue-triage" / "scripts" / "triage_state.py"
WATCH = SKILLS / "github-ship-watch" / "SKILL.md"
PR_TRIAGE = SKILLS / "github-pr-triage" / "SKILL.md"
POSTING = ["github-issue-triage", "github-issue-resolve", "github-pr-triage", "github-ship-watch"]

# A login placeholder written bare, as GitHub would notify it: @{login}, @<login>, @{maintainer}...
BARE = re.compile(r"(?<!`)@(?:\{[^}\n]+\}|<[^>\n]+>)")
# The markers of the three comments a bare mention may lead (D-61)
MENTIONING = ("<!-- shipmill:needs-decision -->", "<!-- shipmill:handoff -->", "<!-- shipmill:decided")
# Templates an approved criterion still fixes in the bare form, left for the maintainer's call:
# S-012-6, the relayed answer's first line
PENDING = {"Decision by @{login}, relayed by {agent}", "Decision by @<login>, relayed by <agent>"}


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def blocks(text: str) -> list[list[str]]:
    """The lines of each fenced block of a markdown file, fences left out"""
    found: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if current is None:
                current = []
            else:
                found.append(current)
                current = None
        elif current is not None:
            current.append(line.strip())
    return found


def stray(block: list[str]) -> list[str]:
    """The lines of a template block holding a bare login placeholder D-61 doesn't allow: in a
    needs-decision question, a hand-off, or a decided comment, only the run of mentions that
    starts the line after the marker lines is allowed"""
    allowed = any(line.startswith(MENTIONING) for line in block)
    bad = []
    for line in block:
        if line in PENDING:
            continue
        rest = re.sub(r"^(?:@(?:\{[^}]+\}|<[^>]+>)[ ,]*)+", "", line) if allowed else line
        if BARE.search(rest):
            bad.append(line)
    return bad


def templates() -> list[tuple[Path, list[str]]]:
    return [(path, block) for path in sorted(SKILLS.glob("*/**/*.md")) for block in blocks(path.read_text("utf-8"))]


def test_771_no_template_writes_a_bare_login_outside_the_three_mentions() -> None:
    found = [f"{path.relative_to(ROOT)}: {line}" for path, block in templates() for line in stray(block)]
    assert found == []


def test_771_the_scan_finds_a_bare_login_where_it_isnt_allowed() -> None:
    assert stray(["Checked after @{login} closed this: `x` returned y."]) == [
        "Checked after @{login} closed this: `x` returned y."
    ]
    assert stray(["Checked after `@{login}` closed this."]) == []
    question = ["<!-- shipmill:needs-decision -->", "@{maintainer} Decision needed: @{login} reported this done"]
    assert stray(question) == [question[1]]
    assert stray(["<!-- shipmill:handoff -->", "@{assignee} @{org/team}, it's your turn"]) == []
    assert stray(["<!-- shipmill:decided zone=x -->", "@<login> Decided without waiting: y"]) == []


FORMER = {
    COMMENTS: [
        "Closed on @{login}'s report",
        "Checked after @{login} closed this",
        "Closed unchecked on @{login}'s answer",
        '@{login} answered "leave it open"',
        "it waits for @{maintainer}",
        "I hand it back to @{assignee}",
        "Decision needed: @{login} reported",
    ],
    WATCH: ["Accepted by @<login> in #<issue>"],
    SKILLS / "github-issue-triage" / "SKILL.md": ["Closed unchecked on @{login}'s answer"],
}
NOW = {
    COMMENTS: [
        "Closed on `@{login}`'s report",
        "Checked after `@{login}` closed this",
        "Closed unchecked on `@{login}`'s answer",
        '`@{login}` answered "leave it open"',
        "it waits for `@{maintainer}`",
        "I hand it back to `@{assignee}`",
        "Decision needed: `@{login}` reported",
    ],
    WATCH: ["Accepted by `@<login>` in #<issue>"],
    SKILLS / "github-issue-triage" / "SKILL.md": ["Closed unchecked on `@{login}`'s answer"],
}


@pytest.mark.parametrize("path", sorted(FORMER))
def test_771_the_records_name_the_login_in_a_code_span(path: Path) -> None:
    text = path.read_text("utf-8")
    assert [old for old in FORMER[path] if old in text] == []
    assert [new for new in NOW[path] if new not in text] == []


def test_771_the_three_mentions_stay_bare() -> None:
    needs = NEEDS_DECISION.read_text("utf-8")
    assert "@<login> Decision needed: <the question, one sentence>" in needs
    assert "@<login> Decided without waiting: <the decision, one sentence>" in needs
    comments = COMMENTS.read_text("utf-8")
    assert "<!-- shipmill:handoff -->\n@{assignee} @{assignee} @{org/team}, it's your turn" in comments


@pytest.mark.parametrize("skill", POSTING)
def test_771_each_skill_that_posts_states_the_rule_once(skill: str) -> None:
    text = (SKILLS / skill / "SKILL.md").read_text("utf-8")
    assert text.count("**Mentions (D-61).**") == 1
    rule = text[text.index("**Mentions (D-61).**") :].split("\n", 1)[0]
    assert "code span" in rule and "Decision needed" in rule and "HANDOFF_DUE" in rule and "Decided without" in rule


@pytest.mark.parametrize("path", [NEEDS_DECISION, SPEC_GATE, PR_TRIAGE])
def test_771_the_decision_by_readers_take_both_forms(path: Path) -> None:
    assert "Decision by `@<login>`" in path.read_text("utf-8")


# -- triage_state.py's check-waiting mention, both forms ------------------------------------


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load("triage_state_mention", TRIAGE)


def waiting_comment(body: str) -> dict[str, Any]:
    return {
        "body": f"<!-- shipmill:check-waiting -->\n{body}",
        "createdAt": "2026-10-20T10:00:00Z",
        "author": {"__typename": "Bot", "login": "shipmill-app"},
        "authorAssociation": "NONE",
    }


@pytest.mark.parametrize(
    "line",
    [
        '@maria answered "leave it open": they run the ## Check and close this by hand.',
        '`@maria` answered "leave it open": they run the ## Check and close this by hand.',
    ],
)
def test_771_check_waiting_reads_the_login_bare_or_in_a_code_span(ts: ModuleType, line: str) -> None:
    found = ts.check_waiting([waiting_comment(line)], "shipmill-app[bot]", None)
    assert found == ("maria", "2026-10-20T10:00:00Z")


def test_771_check_waiting_names_its_author_without_a_login(ts: ModuleType) -> None:
    found = ts.check_waiting([waiting_comment("they run the ## Check by hand.")], "shipmill-app[bot]", None)
    assert found == ("shipmill-app[bot]", "2026-10-20T10:00:00Z")
