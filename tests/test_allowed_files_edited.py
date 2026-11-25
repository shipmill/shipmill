"""Spec 085, #1570: a counting comment edited after the pull request opened holds it (S-085-13),
end to end through pr_gate.py with test_pr_gate.py's stand-in gh on PATH"""

from pathlib import Path
from typing import Any

import pytest

from .test_allowed_files import CI, allowing, gated, held, outside, ready, verdict
from .test_pr_gate import BOT, MAIN_READY, asked, at, comment, gate, headed, review, run_gate, thread

CHANGED = "  files: the allowance on #12 changed after this pull request opened"


def edited(c: dict[str, Any], when: str) -> dict[str, Any]:
    """The comment c as GraphQL lists it once edited at when"""
    return {**c, "lastEditedAt": when}


def test_s085_13_a_counting_comment_edited_after_the_pr_opened_holds_it(tmp_path: Path) -> None:
    """#1570's repro: the verdict allowed src/a.py; edited after the PR opened to add src/b.py, it
    doesn't widen the allowance, it holds the PR"""
    before = gated(tmp_path, ("src/b.py",), {12: thread(verdict("src/a.py"))})
    assert held(before) == [outside("src/b.py")]
    widened = edited(verdict("src/a.py", "src/b.py"), at(11))
    assert held(gated(tmp_path, ("src/b.py",), {12: thread(widened)})) == [CHANGED]
    # the held line doesn't depend on what the edit says: a PR within the old allowance is held too
    assert held(gated(tmp_path, ("src/a.py",), {12: thread(widened)})) == [CHANGED]


def test_s085_13_an_older_counting_comment_edited_after_the_pr_opened_holds_it_too(tmp_path: Path) -> None:
    older = edited(verdict("src/a.py", "src/b.py", when=at(8)), at(11))
    assert held(gated(tmp_path, ("src/a.py",), {12: thread(older, verdict("src/a.py"))})) == [CHANGED]


def test_s085_13_an_edited_counting_comment_without_a_files_line_holds_it(tmp_path: Path) -> None:
    """an edit could have dropped the `Files:` line, which declares no allowance: held all the same"""
    unblocked = edited(allowing("Triage: **implement**, unblocked.\n"), at(11))
    assert held(gated(tmp_path, ("src/a.py", CI), {12: thread(unblocked)})) == [CHANGED]


@pytest.mark.parametrize("when", [at(9, 30), None])
def test_s085_13_a_comment_edited_before_the_pr_opened_or_never_counts_as_before(
    tmp_path: Path, when: str | None
) -> None:
    allowed = edited(verdict("src/a.py", CI), when) if when else {**verdict("src/a.py", CI), "lastEditedAt": None}
    ready(gated(tmp_path, ("src/a.py", CI), {12: thread(allowed)}))
    narrow = edited(verdict("src/a.py"), when) if when else {**verdict("src/a.py"), "lastEditedAt": None}
    assert held(gated(tmp_path, ("src/a.py", CI), {12: thread(narrow)})) == [outside(CI)]


@pytest.mark.parametrize(
    "later",
    [
        pytest.param(verdict("src/a.py", CI, login="eve", association="CONTRIBUTOR"), id="a contributor"),
        pytest.param(verdict("src/a.py", CI, when=at(10, 30)), id="the app after the pr opened"),
        pytest.param(allowing(f"A note on `{CI}`", when=at(9, 30)), id="a note that doesn't count"),
    ],
)
def test_s085_13_an_edited_comment_that_doesnt_count_holds_nothing_new(tmp_path: Path, later: dict[str, Any]) -> None:
    issue = thread(verdict("src/a.py", when=at(8)), edited(later, at(11)))
    assert held(gated(tmp_path, ("src/a.py", CI), {12: issue})) == [outside(CI)]


def test_s085_13_a_malformed_last_edited_at_stops_the_gate(tmp_path: Path) -> None:
    proc = gated(tmp_path, ("src/a.py",), {12: thread(edited(verdict("src/a.py"), "yesterday"))})
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "pr_gate: a comment of #12's lastEditedAt is not a timestamp: 'yesterday'" in proc.stderr


def test_s085_13_the_maintainers_accepting_answer_lifts_the_hold_as_s085_9_does(tmp_path: Path) -> None:
    data = headed(body="Fixes #12", files=("src/b.py",))
    issue = thread(edited(verdict("src/a.py", "src/b.py"), at(11)))
    proc = run_gate(
        tmp_path,
        None,
        {7: data},
        "--bot-login",
        BOT,
        issues={12: issue},
        threads={7: thread(asked(), comment("1", at(12)))},
        permissions={"romamo": "admin"},
        reviews={7: [review(commit=data["headRefOid"])]},
    )
    assert (proc.returncode, proc.stdout) == (0, MAIN_READY), proc.stdout + proc.stderr


def test_s085_13_the_thread_read_asks_each_comments_last_edit() -> None:
    assert "authorAssociation body createdAt lastEditedAt" in gate.THREAD
