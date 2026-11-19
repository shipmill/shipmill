"""Spec 068's milestone rows: MILESTONE_RELEASED, an open milestone its release shipped
(S-068-7); MILESTONE_MISSING, no open milestone above the newest stable tag (S-068-8); and a
milestone whose open issues are each a hold reading MILESTONE_WAITING (S-068-10)"""

from pathlib import Path

import pytest

from shipmill.github import Milestone, MilestoneIssues, OpenIssue, OpenMilestone, parse_milestone_issues
from shipmill.status import MilestoneRow

from .conftest import Repo, Repos, at_day
from .test_milestone_status import OPEN, milestones, on_github, read, stable_released
from .test_milestones import plan_stable, rc_cut, with_app

CLOSE = "gh api -X PATCH repos/o/demo/milestones/3 -f state=closed"  # no app_id: plain gh (S-037-12)
CREATE = "gh api -X POST repos/o/demo/milestones -f title=1.1.1"
UPCOMING = OpenMilestone(4, "1.1.1", 0)  # the version stable_released's lane cuts next
RELEASED = MilestoneRow(
    "MILESTONE_RELEASED", "1.1.0", "v1.1.0 exists and the milestone has no open issues: close it", 3, None, CLOSE
)
MISSING = MilestoneRow(
    "MILESTONE_MISSING",
    "1.1.1",
    "no open milestone above v1.1.0: the stable lane cuts 1.1.1 next, and an accepted goal plan may name it (D-38);"
    " creating it is the maintainer's step (D-32)",
    None,
    "1.1.1",
    CREATE,
)


def test_s068_7_an_open_milestone_its_tagged_release_shipped_reads_released_with_the_close(
    repos: Repos, tmp_path: Path
) -> None:
    repo, _ = repos.after(tmp_path, stable_released)
    repo.github.open = [OpenMilestone(3, "1.1.0", 0), UPCOMING]
    assert read(repo, at_day(6)) == ([RELEASED], None)


def test_s068_7_no_released_row_with_open_issues_or_without_a_tag(repos: Repos, tmp_path: Path) -> None:
    repo, _ = repos.after(tmp_path, stable_released)
    repo.github.open = [OpenMilestone(3, "1.1.0", 2), UPCOMING]  # open issues: overtaken, not released
    rows, _ = read(repo, at_day(6))
    assert [r.state for r in rows] == ["MILESTONE_OVERTAKEN"]
    repo.github.open = [UPCOMING, OpenMilestone(5, "1.2.0", 0)]  # no tag v1.1.1 or v1.2.0
    assert read(repo, at_day(6)) == ([], None)


def test_s068_7_and_8_the_fixes_go_through_shipmill_gh_with_app_id_set(repos: Repos, tmp_path: Path) -> None:
    repo, _ = repos.after(tmp_path, stable_released)
    with_app(repo, 7)
    repo.github.open = [OpenMilestone(3, "1.1.0", 0)]
    rows, _ = read(repo, at_day(6))
    assert [r.fix for r in rows] == [f"shipmill {CLOSE}", f"shipmill {CREATE}"]


def test_s068_7_shipmill_milestones_prints_the_released_and_missing_rows(
    repos: Repos, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = repos.after(tmp_path, stable_released)
    repo.github.open = [OpenMilestone(3, "1.1.0", 0)]
    on_github(repo)
    assert milestones(repo, at_day(6), capsys) == (
        f"MILESTONE_RELEASED 1.1.0: {RELEASED.detail}\n  fix: {CLOSE}\n"
        f"MILESTONE_MISSING 1.1.1: {MISSING.detail}\n  fix: {CREATE}\n"
    )


def test_s068_8_no_open_milestone_above_the_newest_stable_tag_reads_missing_with_the_create(
    repos: Repos, tmp_path: Path
) -> None:
    repo, _ = repos.after(tmp_path, stable_released)
    assert read(repo, at_day(6)) == ([MISSING], None)
    # none of these is titled a stable version above v1.1.0, as the lane names one
    repo.github.open = [OpenMilestone(5, "Someday", 1), OpenMilestone(6, "1.2.0rc1", 0), OpenMilestone(7, "v1.2.0", 0)]
    assert read(repo, at_day(6)) == ([MISSING], None)


def test_s068_8_no_missing_row_once_a_milestone_above_the_newest_tag_is_open(repos: Repos, tmp_path: Path) -> None:
    repo, _ = repos.after(tmp_path, stable_released)
    for title in ("1.1.1", "1.2.0", "2.0.0"):
        repo.github.open = [OpenMilestone(4, title, 0)]
        assert read(repo, at_day(6)) == ([], None), title


def held(repo: Repo, *issues: OpenIssue) -> None:
    """Milestone 1.1.0 of rc_cut's candidate, open, with these open issues"""
    repo.github.milestones["1.1.0"] = Milestone(len(issues), 0)
    repo.github.milestone_lists["1.1.0"] = MilestoneIssues("o/demo", tuple((i.number, "") for i in issues), issues)
    repo.github.open = [OpenMilestone(3, "1.1.0", len(issues))]


PARKED = OpenIssue(11, "Park the release", frozenset({"shipmill-hold"}))
ASKED = OpenIssue(12, "Which way?", frozenset({"needs-decision", "bug"}))
REASONS = (
    "milestone 1.1.0: #11 holds it (shipmill-hold): Park the release;"
    " milestone 1.1.0: #12 waits on a decision: Which way?"
)


def test_s068_10_a_milestone_whose_open_issues_are_each_a_hold_reads_waiting_one_reason_per_issue(
    repos: Repos, tmp_path: Path
) -> None:
    repo, _ = repos.after(tmp_path, rc_cut)
    held(repo, PARKED, ASKED)
    assert read(repo, at_day(5)) == ([MilestoneRow("MILESTONE_WAITING", "1.1.0", REASONS)], None)
    assert repo.github.milestone_reads == ["1.1.0"]
    # shipmill plan names the same reasons for the lane
    assert f"stable: 1.1.0 is ready but no trigger is due; {REASONS}" in plan_stable(repo).reason


def test_s068_10_a_milestone_with_any_other_open_issue_reads_no_waiting_row(repos: Repos, tmp_path: Path) -> None:
    repo, _ = repos.after(tmp_path, rc_cut)
    held(repo, PARKED, ASKED, OpenIssue(13, "Build it", frozenset({"bug"})))
    assert read(repo, at_day(5)) == ([], None)
    assert "milestone" not in plan_stable(repo).reason
    held(repo, OpenIssue(13, "Build it", frozenset()))
    assert read(repo, at_day(5)) == ([], None)


def test_s068_10_the_milestone_read_takes_each_open_issues_title_and_labels() -> None:
    url = "https://github.com/o/demo/issues/"
    found = parse_milestone_issues(
        [
            {"number": 12, "body": "", "url": url + "12", "state": "OPEN", "title": "Which way?", "labels": [
                {"name": "needs-decision"}, {"name": "bug", "color": "d73a4a"}
            ]},
            {"number": 11, "body": "", "url": url + "11", "state": "OPEN", "title": "Park the release", "labels": [
                {"name": "shipmill-hold"}
            ]},
            {"number": 9, "body": "", "url": url + "9", "state": "CLOSED", "title": "Done", "labels": []},
        ],
        "1.1.0",
    )  # fmt: skip
    assert found.issues == ((9, ""), (11, ""), (12, ""))
    assert found.open == (PARKED, ASKED)


def test_s068_10_no_hold_read_for_a_milestone_with_no_open_issue(repos: Repos, tmp_path: Path) -> None:
    """The candidate's milestone open with no issue at all: no hold read, no row"""
    repo, _ = repos.after(tmp_path, rc_cut)
    repo.github.milestones["1.1.0"] = Milestone(0, 0)
    repo.github.open = [OPEN]
    assert read(repo, at_day(5)) == ([], None)
    assert repo.github.milestone_reads == []
