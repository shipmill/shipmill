"""Spec 034, #637: github-ship-watch's Direction section, what a session does for each
DIRECTION_PENDING row: open the direction issue, ask its question, take up the answer"""

import importlib.util
import re
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "github-ship-watch" / "SKILL.md"
SPEC = ROOT / "docs" / "specs" / "034-direction-missing.md"
GUIDE = "https://github.com/shipmill/shipmill/blob/main/docs/direction.md"


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load("triage_state", ROOT / "skills" / "github-issue-triage" / "scripts" / "triage_state.py")


@pytest.fixture(scope="module")
def dm() -> ModuleType:
    return load("shipmill_decisions", ROOT / "skills" / "github-issue-triage" / "scripts" / "decisions.py")


@pytest.fixture(scope="module")
def rt() -> ModuleType:
    scripts = ROOT / "skills" / "github-ship-watch" / "scripts"
    sys.path.insert(0, str(scripts))  # retro imports metrics, as when run from its folder
    try:
        return load("retro", scripts / "retro.py")
    finally:
        sys.path.remove(str(scripts))


def raw_section() -> str:
    """The Direction section of the skill, as written, up to the next `## ` heading"""
    text = SKILL.read_text(encoding="utf-8")
    assert "\n## Direction\n" in text
    return text.split("\n## Direction\n", 1)[1].split("\n## ", 1)[0]


def section() -> str:
    """The Direction section with its line wrapping folded, so a statement reads as one line"""
    return " ".join(raw_section().split())


def step(number: int) -> str:
    """One numbered step of the section, folded"""
    body = section()
    start = body.index(f" {number}. **") if number > 1 else body.index("1. **")
    end = body.find(f" {number + 1}. **", start)
    return (body[start:] if end == -1 else body[start:end]).strip()


def question(text: str, after: str) -> str:
    """The markdown block that follows `after` (its words wrapped anywhere), dedented"""
    words = r"\s+".join(re.escape(word) for word in after.split())
    block = re.search(words + r".*?```markdown\n(.*?)\n\s*```", text, re.S)
    assert block is not None, after
    return textwrap.dedent(block.group(1))


# -- S-034-8 -----------------------------------------------------------------------------------


def test_s034_8_the_section_opens_the_issue_as_the_app(ts: ModuleType) -> None:
    opening = step(1)
    assert opening.startswith("1. **`open the direction question`**")
    assert "Open the issue as the App (hard rule 7) through `--body-file`" in opening
    assert "title `Write the product's direction (docs/product.md)`" in opening
    assert f"label `{ts.DIRECTION_LABEL}`" in opening
    assert (
        "`gh label create shipmill-direction --description \"shipmill's question for the product's direction\"`"
        in opening
    )
    assert f"the body's first line the marker `{ts.DIRECTION_MARKER}`" in opening
    assert GUIDE in opening
    assert (ROOT / "docs" / "direction.md").is_file()  # the guide the issue links


def test_s034_8_the_question_is_the_specs_word_for_word() -> None:
    asked = question(raw_section(), "The question, word for word:")
    assert asked == question(SPEC.read_text(encoding="utf-8"), "The question, word for word:")
    assert asked.splitlines()[0] == "<!-- shipmill:needs-decision -->"
    assert GUIDE in asked


def test_s034_8_the_question_carries_the_direction_zone_line(rt: ModuleType, dm: ModuleType) -> None:
    # #672: the retro counts asks per zone from the question's second line
    asked = question(raw_section(), "The question, word for word:")
    assert asked.splitlines()[1] == "<!-- shipmill:zone direction -->"
    assert "direction" in dm.ZONES
    assert rt.marker(asked) == ("asks", "direction", False)


def test_s034_8_the_question_goes_through_the_protocol_under_watch_only() -> None:
    body = section()
    assert 'under "watch" only (under "status", report the rows and stop)' in body
    asking = step(2)
    assert asking.startswith("2. **`ask the maintainer`**")
    assert "needs-decision protocol](../github-issue-triage/references/needs-decision.md)" in asking
    assert "a gate session posts the question on the issue as the App and adds the `needs-decision` label" in asking
    assert "the issue is in NEEDS_DECISION, which starts no session" in asking
    skill = " ".join(SKILL.read_text(encoding="utf-8").split())
    assert 'Under "status", report POSTMORTEM_DUE, UPGRADE_PENDING, and DIRECTION_PENDING and stop.' in skill


def test_s034_8_an_interactive_gate_session_asks_the_sections_one_at_a_time() -> None:
    asking = step(2)
    assert (
        "an interactive one (`Gate session:`) also asks in the session, one section at a time in the order below,"
        " as shipmill-setup's step 2 does" in asking
    )
    assert "posts it on the issue as the protocol's [Answered in the session]" in asking
    asked = question(raw_section(), "The question, word for word:")
    sections = [line.split(":", 1)[0] for line in asked.splitlines() if line.startswith("- ")]
    assert sections == ["- Mission", "- Users", "- Goals", "- Non-goals", "- Quality bar"]


# -- S-034-9 -----------------------------------------------------------------------------------


def test_s034_9_answer_2_or_a_decline_closes_the_issue_as_not_planned() -> None:
    taking = step(3)
    assert taking.startswith("3. **`answered; take up the answer`**")
    assert "told by the comment's `author_association`" in taking
    assert "Remove the `needs-decision` label, then:" in taking
    assert (
        "**2**, or a reply that declines in its own words: close the issue as not planned (`gh issue close <n>"
        ' --reason "not planned"`)' in taking
    )


def test_s034_9_an_empty_required_section_is_asked_again() -> None:
    assert (
        "A reply that leaves Users, Goals, or Quality bar empty, answers none of the options, or asks something"
        " back: ask again with the protocol, naming only the sections still owed; nothing is written meanwhile"
        in step(3)
    )


def test_s034_9_the_file_comes_from_the_reply_only_and_is_checked() -> None:
    writing = step(4)
    assert "Write `docs/product.md` in spec 024's fixed structure from the reply's words only" in writing
    assert "Never invent an item and never fill one in from the README or the code" in writing
    assert "Run `shipmill product check` until it exits 0" in writing


def test_s034_9_the_pull_request_opens_as_the_app_and_is_never_merged() -> None:
    writing = step(4)
    assert "on the branch `shipmill/direction`" in writing
    assert "open the pull request as the App (hard rule 7) through `--body-file`" in writing
    assert "holds `Closes #<issue>` and the line ``Direction from `@<login>` in #<issue>``" in writing
    assert "Direction from @" not in writing, "the login sits in a code span (D-61, #771)"
    assert "The watch never merges it" in writing
    assert "github-pr-triage never merges an edit of `docs/product.md` on its own judgment (S-024-11)" in writing


def test_s034_9_a_closed_direction_pull_request_closes_the_issue_as_not_planned() -> None:
    declined = step(5)
    assert declined.startswith("5. **`pull request #<m> closed unmerged, a decline: close #<n> as not planned`**")
    assert 'gh issue close <n> --reason "not planned"' in declined
    assert "the repo's own `shipmill/direction` branch whose state is CLOSED" in declined


def test_s034_9_each_pending_detail_the_script_emits_has_its_step() -> None:
    # every DIRECTION_PENDING detail watch_state.py writes names one step of the section
    script = (ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py").read_text(encoding="utf-8")
    emitted = ["open the direction question", "ask the maintainer", "answered; take up the answer"]
    assert all(f'"{detail}"' in script for detail in emitted)
    assert 'f"pull request #{pr} closed unmerged, a decline: close #{number} as not planned"' in script
    heads = [step(n).split("**", 2)[1] for n in (1, 2, 3, 5)]
    assert heads == [f"`{detail}`" for detail in emitted] + [
        "`pull request #<m> closed unmerged, a decline: close #<n> as not planned`"
    ]
