"""Spec 090, The skills: comments.md's "Status comment" section, and the four skills that post a
session's progress with `--status` (S-090-8, S-090-9)"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
COMMENTS = SKILLS / "github-issue-triage" / "references" / "comments.md"


def section(text: str, heading: str) -> str:
    """The body of the `## heading` section, up to the next `## `"""
    found = re.search(rf"^## {re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert found is not None, heading
    return found["body"]


def test_s090_8_comments_md_has_a_status_comment_section_listing_what_stays_new() -> None:
    body = section(COMMENTS.read_text(encoding="utf-8"), "Status comment")
    assert "--status --body-file" in body and "<!-- shipmill:status -->" in body
    new, _, progress = body.partition("Everything else is progress")
    for kept in (
        "`Triage:` verdict",
        "hold sentences",
        "a hold line on a pull request",
        "needs-decision question",
        "decided comment",
        "relayed decision (`Decision by`)",
        "veto-handled comment",
        "hand-off",
        "still-waits",
        "check-waiting",
        "check-failed",
        "verified",
        "close-confirmed",
        "The final result",
        "done",
        "closed",
        "refused",
    ):
        assert kept in new, kept
    for step in ("The fix is in #{PR}", "replaced pull request", "plan changed after review", "rebased", "CI pending"):
        assert step in progress, step
    assert "A person's draft gets no status comment" in progress and "D-67" in progress


def test_s090_8_the_fix_is_in_and_the_follow_ups_post_with_status() -> None:
    text = COMMENTS.read_text(encoding="utf-8")
    implement = section(text, "Implement")
    before_fix = implement.partition("The fix is in #{PR}:")[0].rstrip().rsplit("\n", 3)[-3:]
    assert any("--status" in line for line in before_fix), before_fix
    follow = section(text, "Follow-ups")
    replaced = next(line for line in follow.splitlines() if "was replaced by" in line)
    changed = next(line for line in follow.splitlines() if "The plan changed after review" in line)
    assert "--status" in replaced and "--status" in changed


@pytest.mark.parametrize(
    "skill", ["github-issue-resolve", "github-issue-triage", "github-pr-triage", "github-ship-watch"]
)
def test_s090_9_each_skill_posts_its_progress_with_status_never_as_a_new_comment(skill: str) -> None:
    text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
    rule = next(p for p in text.split("\n") if "Progress goes in the status comment (spec 090)" in p)
    assert "--status --body-file" in rule
    assert "is never a new comment" in rule
