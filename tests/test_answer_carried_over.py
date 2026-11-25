"""Spec 055, #1587 (D-108): an answer on a pull request carries over a rebase that only brought
main's changes, end to end through pr_gate.py with test_pr_gate.py's stand-in gh on PATH (S-055-20)"""

from pathlib import Path

import pytest

from .test_pr_gate import (
    APPROVED_SPEC,
    CHANGES_BEHAVIOUR,
    DIRECTION,
    PROTECTED_ASK,
    REVIEW,
    SPEC,
    asked,
    at,
    checkout,
    comment,
    committed,
    gate,
    git,
    headed,
    protected,
    thread,
)

SHARED = "src/shared.py"
BASE = "x = 1\ny = 2\n"
OURS = BASE + "z = 3\n"  # the pull request's change, at the answered head
MAINS = BASE + "w = 4\n"  # main's change since, in conflict with it
RESOLVED = BASE + "w = 4\nz = 3\n"  # the conflict resolved with main's line and the pull request's alone
CRITERION = "- S-054-2: the digest names each pull request\n"
OUR_SPEC = APPROVED_SPEC.replace("each release.\n", "each release, archived repos aside.\n")
MAIN_SPEC = APPROVED_SPEC.replace("each release\n", "each release\n" + CRITERION)


def rebased(
    tmp_path: Path, ours: dict[str, str], mains: dict[str, str], resolved: dict[str, str]
) -> tuple[Path, str, str]:
    """A checkout whose main holds the direction, a REVIEW.md protecting src/land.py, SHARED, and
    an approved spec; the pull request's commit of ours, the answered head; main's commit of
    mains after it; and the pull request rebased onto main by hand, its conflicts resolved as
    resolved says, the judged head"""
    work = checkout(tmp_path, {"docs/product.md": DIRECTION, "REVIEW.md": REVIEW, SHARED: BASE, SPEC: APPROVED_SPEC})
    for where in (work, tmp_path / "origin"):
        git(where, "config", "user.email", "t@example.com")
        git(where, "config", "user.name", "t")
    git(work, "switch", "-q", "-c", "feat", "origin/main")
    answered = committed(work, ours, "Change")
    committed(tmp_path / "origin", {**mains, "NOTES.txt": "moved on\n"}, "Base moves")
    git(work, "fetch", "-q", "origin")
    git(work, "switch", "-q", "-c", "rebased", "origin/main")
    head = committed(work, resolved, "Change")
    return work, answered, head


def judged(tmp_path: Path, work: Path, answered: str, head: str, files: tuple[str, ...]) -> tuple[int, list[str]]:
    data = headed(head, ((head, at(13)),), files=files)
    proc = protected(tmp_path, work, data, thread(asked(head=answered), comment("1", at(12))))
    assert proc.stdout.startswith(f"#7 {'READY' if proc.returncode == 0 else 'NEEDS_DECISION'} "), proc.stderr
    assert f" head={head} " in proc.stdout.splitlines()[0], proc.stdout
    return proc.returncode, proc.stdout.splitlines()[1:]


def carried(answered: str) -> str:
    return f"  accepted: answer carried over from {answered[:7]}: only main's changes since"


def differs(answered: str) -> str:
    return f"  needs-decision: answered at {answered[:7]}, and the change differs since"


def test_s055_20_a_conflict_only_rebase_carries_the_answer_over(tmp_path: Path) -> None:
    """#1502, #1506: the rebase resolved a conflict with main and changed nothing of the pull
    request's own; its patch differs (the context lines), so S-055-6 alone asked again"""
    work, answered, head = rebased(
        tmp_path,
        {"src/land.py": "tag = 1\n", SHARED: OURS},
        {SHARED: MAINS},
        {"src/land.py": "tag = 1\n", SHARED: RESOLVED},
    )
    assert judged(tmp_path, work, answered, head, ("src/land.py", SHARED)) == (0, [carried(answered)])


@pytest.mark.parametrize(
    "resolution",
    [
        pytest.param(BASE + "w = 4\nz = 30\n", id="the resolution also changes the code"),
        pytest.param(OURS, id="the resolution drops main's line"),
        pytest.param(BASE + "w = 4\nz = 3\nv = 5\n", id="a line of its own beside main's"),
    ],
)
def test_s055_20_a_rebase_whose_change_is_more_than_mains_asks_again(tmp_path: Path, resolution: str) -> None:
    work, answered, head = rebased(
        tmp_path,
        {"src/land.py": "tag = 1\n", SHARED: OURS},
        {SHARED: MAINS},
        {"src/land.py": "tag = 1\n", SHARED: resolution},
    )
    assert judged(tmp_path, work, answered, head, ("src/land.py", SHARED)) == (5, [PROTECTED_ASK, differs(answered)])


def test_s055_20_an_approved_spec_the_pr_edits_carries_over_when_same_approval_passes(tmp_path: Path) -> None:
    """the pull request edits the approved spec's Behaviour, main adds a criterion to it since,
    and the rebase keeps both where they were"""
    work, answered, head = rebased(
        tmp_path,
        {SPEC: OUR_SPEC},
        {SPEC: MAIN_SPEC},
        {SPEC: OUR_SPEC.replace("each release\n", "each release\n" + CRITERION)},
    )
    assert judged(tmp_path, work, answered, head, (SPEC,)) == (0, [carried(answered)])


def test_s055_20_an_approved_spec_that_fails_same_approval_asks_again(tmp_path: Path) -> None:
    """the rebase put main's criterion under Problem: the lines git diff adds and removes are
    main's, so only same-approval, which reads the pull request's own change by section, tells"""
    misplaced = OUR_SPEC.replace("in them.\n", "in them.\n" + CRITERION)
    work, answered, head = rebased(tmp_path, {SPEC: OUR_SPEC}, {SPEC: MAIN_SPEC}, {SPEC: misplaced})
    assert judged(tmp_path, work, answered, head, (SPEC,)) == (5, [CHANGES_BEHAVIOUR, differs(answered)])


def test_s055_20_a_head_git_cant_read_carries_nothing_over(tmp_path: Path) -> None:
    """fail closed: a git error reads as a difference, never as main's change alone"""
    work, answered, head = rebased(
        tmp_path,
        {"src/land.py": "tag = 1\n", SHARED: OURS},
        {SHARED: MAINS},
        {"src/land.py": "tag = 1\n", SHARED: RESOLVED},
    )
    missing = "0" * 40
    assert gate.main_change_only(str(work), "origin/main", answered, head, ()) is True
    assert gate.main_change_only(str(work), "origin/main", missing, head, ()) is False
    assert gate.main_change_only(str(work), "origin/nowhere", answered, head, ()) is False
