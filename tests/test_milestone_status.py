"""Spec 022: `shipmill status` reports MILESTONE_WAITING while a goal's milestone, its issues
closed, waits on its specs, and MILESTONE_OVERTAKEN once a stable tag took an open
milestone's version, naming the version the lane cuts next"""

import datetime as dt

import pytest

from shipmill.errors import ReleaseError
from shipmill.github import Milestone, OpenMilestone, parse_open_milestones
from shipmill.policy import Lane
from shipmill.status import Row, Verdict, read_milestones, report

from .conftest import Repo, at_day
from .test_lanes import plan, release
from .test_milestones import closed, in_milestone, land_on_main, milestone_policy, plan_stable, rc_cut, spec
from .test_status_picture import facts, lines


def read(repo: Repo, now: dt.datetime) -> tuple[list[Row], str | None]:
    """The status read, as `shipmill status` makes it after watch_state.py's fetch"""
    repo.git.fetch("+refs/heads/main:refs/remotes/origin/main")
    head = repo.git.sha("origin/main")
    return read_milestones("o/demo", repo.root, head, repo.github, now)


def test_s022_8_a_milestone_whose_goal_isnt_built_reads_waiting_with_its_reasons(repo: Repo) -> None:
    rc_cut(repo, {"021-goal.md": spec(21, "approved", "#11"), "023-other.md": spec(23, "built", "#12")})
    in_milestone(repo, (11, "Build A"), (12, "Build B"))
    repo.github.closes[12] = closed(12)
    rows, error = read(repo, at_day(5))
    reasons = (
        "milestone 1.1.0: S-021 is approved, not built; milestone 1.1.0: S-023's #12 closed with no merged pull request"
    )
    assert (rows, error) == ([Row("MILESTONE_WAITING", "1.1.0", reasons, False)], None)
    found = facts(*rows)
    assert f"  milestone      MILESTONE_WAITING {reasons}" in lines(found)
    assert report(found).verdict is Verdict.IDLE  # the build work is the factory's, not a reason


def test_s022_8_a_fix_after_the_rc_names_the_rc(repo: Repo) -> None:
    rc_cut(repo, {"021-goal.md": spec(21, "built", "#11")})
    late = repo.merge(2, "Fixed", "Fix B, after the rc")
    in_milestone(repo, (11, "Build A"))
    repo.github.closes[11] = closed(11, late)
    rows, _ = read(repo, at_day(5))
    assert rows == [Row("MILESTONE_WAITING", "1.1.0", "milestone 1.1.0: S-021's #11 is not in v1.1.0rc1", False)]


def test_s022_8_no_row_while_the_milestone_has_open_issues_or_its_goal_is_done(repo: Repo) -> None:
    fix = rc_cut(repo, {"021-goal.md": spec(21, "approved", "#11")})
    repo.github.milestones["1.1.0"] = Milestone(1, 1)  # the ordinary wait
    assert read(repo, at_day(5)) == ([], None)
    in_milestone(repo, (11, "Build A"))
    land_on_main(repo, "built", {"docs/specs/021-goal.md": spec(21, "built", "#11")})
    repo.github.closes[11] = closed(11, fix)
    assert read(repo, at_day(5)) == ([], None)
    assert plan_stable(repo).lane is Lane.STABLE  # done: the plan is due by it


def test_s022_8_no_row_and_nothing_read_without_a_milestone_or_a_milestone_lane(repo: Repo) -> None:
    rc_cut(repo, {"021-goal.md": spec(21, "approved", "#11")})
    assert read(repo, at_day(5)) == ([], None)  # no milestone named 1.1.0, none open
    assert repo.github.milestone_reads == []
    milestone_policy_off(repo)
    repo.github.milestone_error = "no read is made without a lane that sets milestone = true"
    in_milestone(repo, (11, "Build A"))
    repo.github.open = [OpenMilestone(3, "1.0.0", 1)]
    reads = repo.github.open_reads
    assert read(repo, at_day(5)) == ([], None)
    assert repo.github.open_reads == reads


def milestone_policy_off(repo: Repo) -> None:
    text = repo.read(repo.policy_file)
    land_on_main(repo, "no milestone", {repo.policy_file: text.replace("milestone = true\n", "")})


def test_a_goal_the_plan_cant_read_is_shown_not_dropped(repo: Repo) -> None:
    rc_cut(repo, {"021-goal.md": spec(21, "built", "#99")})
    in_milestone(repo, (99, "Build"))  # #99 isn't on GitHub
    rows, error = read(repo, at_day(5))
    assert rows == [] and error is not None and "Could not resolve" in error
    found = facts(milestone_error=error)
    assert any(line.startswith(f"  milestone      not read: {error}") for line in lines(found))


def stable_released(repo: Repo) -> None:
    """1.1.0 released on the stable lane's schedule, then the milestone lane set, with a fix
    pending on main"""
    repo.merge(1, "Added", "Feature A", "src/a.py", "A = 1\n")
    release(repo, plan(repo, at_day(1)))  # 1.1.0rc1
    release(repo, plan(repo, at_day(5)))  # 1.1.0, by the Monday window
    assert repo.git.ok("rev-parse", "-q", "--verify", "refs/tags/v1.1.0")
    milestone_policy(repo)
    repo.merge(2, "Fixed", "Fix B")


def test_s022_10_an_open_milestone_a_stable_tag_took_reads_overtaken_with_the_next_version(repo: Repo) -> None:
    stable_released(repo)
    repo.github.open = [OpenMilestone(3, "1.1.0", 1), OpenMilestone(4, "1.2.0", 1), OpenMilestone(5, "Someday", 1)]
    rows, error = read(repo, at_day(6))
    rename = "gh api -X PATCH repos/o/demo/milestones/3 -f title=1.1.1"
    assert (rows, error) == (
        [Row("MILESTONE_OVERTAKEN", "1.1.0", "v1.1.0 exists; the stable lane cuts 1.1.1 next", False, rename)],
        None,
    )
    found = report(facts(*rows))
    assert found.verdict is Verdict.WAITS
    text = lines(facts(*rows))
    assert "  milestone      MILESTONE_OVERTAKEN 1.1.0: v1.1.0 exists; the stable lane cuts 1.1.1 next" in text
    assert f"                 fix: {rename}" in text


def test_s022_10_the_next_version_is_the_lanes_candidate(repo: Repo) -> None:
    """With an rc to promote, the stable lane cuts that rc's version next"""
    stable_released(repo)
    repo.merge(3, "Added", "Feature C")
    release(repo, plan(repo, at_day(6)))  # 1.2.0rc1
    repo.github.open = [OpenMilestone(3, "1.1.0", 1)]
    rows, _ = read(repo, at_day(10))
    assert [r.detail for r in rows] == ["v1.1.0 exists; the stable lane cuts 1.2.0 next"]


def test_s022_10_no_row_while_no_stable_tag_took_an_open_milestone(repo: Repo) -> None:
    rc_cut(repo)
    repo.github.open = [OpenMilestone(3, "1.1.0", 1), OpenMilestone(4, "1.0.0rc1", 1), OpenMilestone(5, "v1.0.0", 1)]
    assert read(repo, at_day(2)) == ([], None)


def test_s022_10_a_milestone_its_own_release_shipped_is_not_overtaken(repo: Repo) -> None:
    """GitHub leaves a milestone open after its version ships: with no open issues, the tag
    shipped its goal rather than took it, so there is nothing to rename"""
    fix = rc_cut(repo, {"021-goal.md": spec(21, "built", "#11")})
    in_milestone(repo, (11, "Build A"))
    repo.github.closes[11] = closed(11, fix)
    release(repo, plan_stable(repo))  # 1.1.0, due by its milestone
    assert repo.git.ok("rev-parse", "-q", "--verify", "refs/tags/v1.1.0")
    repo.merge(2, "Fixed", "Fix B")
    repo.github.open = [OpenMilestone(3, "1.1.0", 0)]
    assert read(repo, at_day(6)) == ([], None)
    repo.github.open = [OpenMilestone(3, "1.1.0", 1)]  # an issue still open: taken before done
    rows, _ = read(repo, at_day(6))
    assert [r.state for r in rows] == ["MILESTONE_OVERTAKEN"]


def test_s022_10_a_milestone_never_changes_the_bump(repo: Repo) -> None:
    """The plan reads no open milestone, and an overtaken 1.1.0 and a closed 1.2.0 leave the
    fix pending a patch: the rc is 1.1.1rc1, and stable promotes it as 1.1.1"""
    stable_released(repo)
    repo.github.open = [OpenMilestone(3, "1.1.0", 1), OpenMilestone(4, "1.2.0", 1)]
    repo.github.milestones["1.2.0"] = Milestone(0, 2)
    rc = plan(repo, at_day(6))
    assert (rc.lane, str(rc.version)) == (Lane.RC, "1.1.1rc1"), rc.reason
    release(repo, rc)
    repo.github.milestones["1.1.1"] = Milestone(0, 1)
    stable = plan(repo, at_day(10))
    assert (stable.lane, str(stable.version)) == (Lane.STABLE, "1.1.1"), stable.reason
    assert repo.github.open_reads == 0


def test_parse_open_milestones_is_strict() -> None:
    found = parse_open_milestones(
        [
            {"number": 4, "title": "1.2.0", "state": "open", "open_issues": 2},
            {"number": 3, "title": "x", "state": "open", "open_issues": 0},
        ]
    )
    assert found == [OpenMilestone(3, "x", 0), OpenMilestone(4, "1.2.0", 2)]
    bad_answers: list[object] = [
        {},
        [{"number": "3", "title": "x", "state": "open", "open_issues": 0}],
        [{"number": 3, "title": "x", "state": "closed", "open_issues": 0}],
        [{"number": 3, "title": "x", "state": "open"}],
        [{"number": 3, "title": "x", "state": "open", "open_issues": True}],
    ]
    for bad in bad_answers:
        with pytest.raises(ReleaseError):
            parse_open_milestones(bad)
    with pytest.raises(ReleaseError, match="100 open milestones or more"):
        parse_open_milestones([{"number": n, "title": str(n), "state": "open"} for n in range(100)])
