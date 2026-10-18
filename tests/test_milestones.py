"""Spec 022: a lane with milestone = true is due by its milestone once the specs behind the
milestone's issues are built and every build issue's fix is in the candidate's base"""

import datetime as dt

import pytest

from shipmill.errors import ReleaseError
from shipmill.github import (
    CloseReason,
    IssueClose,
    IssueComment,
    Milestone,
    MilestoneIssues,
    parse_issue_closes,
    parse_milestone_issues,
)
from shipmill.milestones import CLOSE_CONFIRMED, GoalError, parse_spec
from shipmill.planner import Decision, Event, Planner
from shipmill.policy import Lane

from .conftest import Repo, at_day
from .test_lanes import plan, release

CLOSED = at_day(2)
LATER = at_day(2, 9)


def land_on_main(repo: Repo, message: str, edit: dict[str, str]) -> None:
    """Commit files to main and push, as a merged pull request does; each value replaces
    the file, or with a leading "+" is appended to it"""
    repo.git.run("checkout", "-q", "main")
    repo.git.run("reset", "-q", "--hard", "origin/main")
    for path, text in edit.items():
        repo.write(path, repo.read(path) + text[1:] if text.startswith("+") else text)
    repo.git.run("add", "-A")
    repo.git.run("commit", "-q", "-m", message)
    repo.git.run("push", "-q", "origin", "main")


def milestone_policy(repo: Repo) -> None:
    """The stable lane promotes by its milestone only; no schedule makes it due"""
    repo.git.run("checkout", "-q", "main")
    text = repo.read(repo.policy_file)
    lines = 'min_soak_days = 3\nschedule = ["Mon 07:00 UTC"]\n'
    assert lines in text
    land_on_main(repo, "milestone", {repo.policy_file: text.replace(lines, "min_soak_days = 3\nmilestone = true\n")})


def spec(number: int, status: str, *issues: str) -> str:
    listed = "".join(f"- {i}: S-{number:03d}-1\n" for i in issues)
    return (
        f"# S-{number:03d}: Goal {number}\n\nstatus: {status}\n\n## Problem\n\nWhy.\n\n"
        f"## Acceptance criteria\n\n- S-{number:03d}-1: It works\n\n## Issues\n\n{listed}\n## Verification\n"
    )


def rc_cut(repo: Repo, specs: dict[str, str] | None = None) -> str:
    """Merge #1 (and the specs), cut 1.1.0rc1 from it, and return #1's merge commit"""
    milestone_policy(repo)
    if specs:
        land_on_main(repo, "Specs", {f"docs/specs/{name}": text for name, text in specs.items()})
    fix = repo.merge(1, "Added", "Feature A", "src/a.py", "A = 1\n")
    release(repo, plan(repo, at_day(1)))
    return fix


def plan_stable(repo: Repo) -> Decision:
    return plan(repo, at_day(5))


def with_app(repo: Repo, app_id: int) -> None:
    """Set [agents] app_id on main"""
    land_on_main(repo, "agents", {repo.policy_file: f'+\n[agents]\nprompt = "Triage {{repo}}"\napp_id = {app_id}\n'})


def closed(
    number: int, *fixes: str, reason: CloseReason = CloseReason.COMPLETED, comments: tuple[IssueComment, ...] = ()
) -> IssueClose:
    return IssueClose(number, reason, CLOSED, fixes, comments)


def comment(
    body: str, association: str = "OWNER", at: dt.datetime = LATER, author: str = "maintainer", bot: bool = False
) -> IssueComment:
    return IssueComment(author, bot, association, at, body)


def in_milestone(repo: Repo, *issues: tuple[int, str]) -> None:
    repo.github.milestones["1.1.0"] = Milestone(0, len(issues))
    repo.github.milestone_lists["1.1.0"] = MilestoneIssues("o/demo", tuple(issues))


def test_s022_1_a_milestone_with_open_issues_is_not_due(repo: Repo) -> None:
    rc_cut(repo, {"021-goal.md": spec(21, "built", "o/demo#11")})
    repo.github.milestones["1.1.0"] = Milestone(1, 1)
    decision = plan_stable(repo)
    assert "stable: 1.1.0 is ready but no trigger is due; rc:" in decision.reason
    assert "milestone" not in decision.reason
    assert repo.github.close_reads == []


def test_s022_2_a_spec_not_built_holds_the_milestone(repo: Repo) -> None:
    rc_cut(repo, {"021-goal.md": spec(21, "approved", "o/demo#11"), "023-other.md": spec(23, "draft", "#12")})
    in_milestone(repo, (11, "Build A"), (12, "Build B"))
    decision = plan_stable(repo)
    assert decision.lane is not Lane.STABLE
    assert (
        "stable: 1.1.0 is ready but no trigger is due; milestone 1.1.0: S-021 is approved, not built;"
        " milestone 1.1.0: S-023 is draft, not built"
    ) in decision.reason
    assert repo.github.close_reads == []  # nothing built: no build issue is read


def test_s022_2_the_spec_is_read_at_mains_head(repo: Repo) -> None:
    """A spec marked built only on a branch doesn't count"""
    rc_cut(repo, {"021-goal.md": spec(21, "approved", "#11")})
    repo.git.run("checkout", "-q", "-b", "wip", "origin/main")
    repo.write("docs/specs/021-goal.md", spec(21, "built", "#11"))
    repo.git.run("commit", "-q", "-am", "built on a branch")
    repo.git.run("push", "-q", "origin", "wip")
    in_milestone(repo, (11, "Build A"))
    repo.github.closes[11] = closed(11, repo.git.sha("HEAD"))
    assert "milestone 1.1.0: S-021 is approved, not built" in plan_stable(repo).reason


def test_s022_3_a_build_issue_closed_with_no_merged_pull_request_holds_it(repo: Repo) -> None:
    rc_cut(repo, {"021-goal.md": spec(21, "built", "o/demo#11")})
    in_milestone(repo, (11, "Build A"))
    repo.github.closes[11] = closed(11)
    decision = plan_stable(repo)
    assert decision.lane is not Lane.STABLE
    assert "milestone 1.1.0: S-021's #11 closed with no merged pull request" in decision.reason


@pytest.mark.parametrize(
    "marker",
    [
        comment(CLOSE_CONFIRMED + "\nDone by hand", "NONE"),  # an outsider's
        comment(CLOSE_CONFIRMED, "MEMBER", at=at_day(1)),  # before the last close
        comment("Done by hand\n" + CLOSE_CONFIRMED, "OWNER"),  # not the first line
        comment(CLOSE_CONFIRMED, "NONE", author="other-app", bot=True),  # another App
    ],
)
def test_s022_3_an_untrusted_or_stale_marker_confirms_nothing(repo: Repo, marker: IssueComment) -> None:
    rc_cut(repo, {"021-goal.md": spec(21, "built", "#11")})
    in_milestone(repo, (11, "Build A"))
    with_app(repo, 7)
    repo.github.apps = {"other-app": 8, "shipmill-demo": 7}
    repo.github.closes[11] = closed(11, comments=(marker,))
    assert "S-021's #11 closed with no merged pull request" in plan_stable(repo).reason


@pytest.mark.parametrize(
    "marker",
    [
        comment(CLOSE_CONFIRMED + "\nDone by hand", "COLLABORATOR"),
        comment("\n" + CLOSE_CONFIRMED, "NONE", author="shipmill-demo", bot=True),  # the [agents] App
    ],
)
def test_s022_3_a_trusted_close_confirmed_marker_stands_in_for_a_pull_request(repo: Repo, marker: IssueComment) -> None:
    rc_cut(repo, {"021-goal.md": spec(21, "built", "#11")})
    in_milestone(repo, (11, "Build A"))
    with_app(repo, 7)
    repo.github.apps = {"shipmill-demo": 7}
    repo.github.closes[11] = closed(11, comments=(marker,))
    decision = plan_stable(repo)
    assert (decision.lane, str(decision.version)) == (Lane.STABLE, "1.1.0"), decision.reason
    assert "milestone 1.1.0 built: S-021" in decision.reason


def test_s022_4_a_fix_merged_after_the_rc_holds_the_promotion(repo: Repo) -> None:
    rc_cut(repo, {"021-goal.md": spec(21, "built", "#11")})
    late = repo.merge(2, "Fixed", "Fix B, after the rc")
    in_milestone(repo, (11, "Build A"))
    repo.github.closes[11] = closed(11, late)
    decision = plan_stable(repo)
    assert decision.lane is not Lane.STABLE
    assert "milestone 1.1.0: S-021's #11 is not in v1.1.0rc1" in decision.reason


def test_s022_5_a_build_issue_closed_as_not_planned_holds_nothing(repo: Repo) -> None:
    fix = rc_cut(repo, {"021-goal.md": spec(21, "built", "#11", "#12")})
    in_milestone(repo, (11, "Build A"), (12, "Build B"))
    repo.github.closes[11] = closed(11, fix)
    repo.github.closes[12] = closed(12, reason=CloseReason.NOT_PLANNED)
    decision = plan_stable(repo)
    assert decision.lane is Lane.STABLE, decision.reason


def test_s022_6_built_specs_in_the_base_make_the_lane_due(repo: Repo) -> None:
    fix = rc_cut(
        repo,
        {
            "021-goal.md": spec(21, "built", "o/demo#11", "other/lib#40"),  # another repo's issue is ignored
            "023-other.md": spec(23, "built", "#12"),
            "024-unrelated.md": spec(24, "draft", "#30"),
        },
    )
    in_milestone(repo, (11, "Build A"), (12, "Build B"))
    repo.github.closes[11] = closed(11, fix)
    repo.github.closes[12] = closed(12, "0" * 40, fix)  # one fix GitHub knows, not in this clone
    decision = plan_stable(repo)
    assert (decision.action, decision.lane, str(decision.version)) == ("release", Lane.STABLE, "1.1.0")
    assert "milestone 1.1.0 built: S-021, S-023" in decision.reason
    assert repo.github.close_reads == [(11, 12)]  # one batched read


def test_s022_7_a_milestone_no_spec_names_is_due_as_today(repo: Repo) -> None:
    rc_cut(repo, {"024-unrelated.md": spec(24, "draft", "#30")})
    in_milestone(repo, (11, "Fix A"))
    decision = plan_stable(repo)
    assert decision.lane is Lane.STABLE
    assert "; milestone 1.1.0 has no open issues" in decision.reason
    assert repo.github.close_reads == []


def test_s022_7_without_specs_the_milestone_reads_nothing_more(repo: Repo) -> None:
    rc_cut(repo)
    repo.github.milestones["1.1.0"] = Milestone(0, 3)
    decision = plan_stable(repo)
    assert decision.lane is Lane.STABLE
    assert "; milestone 1.1.0 has no open issues" in decision.reason
    assert repo.github.milestone_reads == []


def test_s022_7_a_file_in_docs_specs_that_is_no_spec_changes_nothing(repo: Repo) -> None:
    """A repository may keep other notes in docs/specs; they are the spec checker's to report"""
    rc_cut(repo, {"api-notes.md": "# API notes\n", "021-goal.md": spec(21, "draft", "#30")})
    in_milestone(repo, (11, "Fix A"))
    decision = plan_stable(repo)
    assert decision.lane is Lane.STABLE, decision.reason
    assert "; milestone 1.1.0 has no open issues" in decision.reason


def test_s022_9_an_issue_linking_a_spec_holds_the_milestone(repo: Repo) -> None:
    rc_cut(repo, {"021-goal.md": spec(21, "approved", "#11")})
    in_milestone(repo, (5, "Feature\n\nSpec: https://github.com/o/demo/blob/main/docs/specs/021-goal.md\n"))
    decision = plan_stable(repo)
    assert decision.lane is not Lane.STABLE
    assert "milestone 1.1.0: S-021 is approved, not built" in decision.reason


def test_an_unreadable_goal_does_not_stop_the_rc_lane(repo: Repo) -> None:
    """A built spec naming an issue GitHub doesn't have fails the stable lane only"""
    rc_cut(repo, {"021-goal.md": spec(21, "built", "#99")})
    in_milestone(repo, (99, "Build"))
    repo.merge(2, "Fixed", "Fix B")
    decision = plan_stable(repo)
    assert decision.lane is Lane.RC
    assert "stable: not planned, gh api graphql failed: Could not resolve" in decision.reason


def test_a_failed_milestone_read_fails_the_plan_as_on_main(repo: Repo) -> None:
    """Only the goal's reading spares rc and dev; the milestone's own read fails the plan,
    so a GitHub outage never lets an rc release green in the stable lane's place"""
    rc_cut(repo, {"021-goal.md": spec(21, "built", "#11")})
    repo.merge(2, "Fixed", "Fix B")  # rc would release, were the error spared
    repo.github.milestone_error = "gh api repos/o/demo/milestones failed: HTTP 502"
    with pytest.raises(ReleaseError, match="HTTP 502") as raised:
        plan_stable(repo)
    assert not isinstance(raised.value, GoalError)


def test_a_spec_with_an_unknown_status_in_the_milestone_fails_its_lane(repo: Repo) -> None:
    rc_cut(repo, {"021-goal.md": spec(21, "done", "#11")})
    in_milestone(repo, (11, "Build"))
    with pytest.raises(ReleaseError, match=r"021-goal.md says status 'done'"):
        Planner(repo.git, repo.policy, repo.github, at_day(5)).plan(Event.SCHEDULE)


def test_parse_spec_reads_status_and_issues() -> None:
    found = parse_spec("021-goal.md", spec(21, "built", "o/demo#11", "#12", "other/lib#3"))
    assert found.status == "built"
    assert found.numbers("O/Demo") == [11, 12]


def test_parse_milestone_issues_is_strict() -> None:
    url = "https://github.com/o/demo/issues/"
    found = parse_milestone_issues([{"number": 3, "body": "b", "url": url + "3"}], "1.1.0")
    assert found == MilestoneIssues("o/demo", ((3, "b"),))
    with pytest.raises(ReleaseError, match="with the URL"):
        parse_milestone_issues([{"number": 4, "body": "b", "url": url + "3"}], "1.1.0")
    with pytest.raises(ReleaseError, match="needs a number"):
        parse_milestone_issues([{"number": 4, "body": None, "url": url + "4"}], "1.1.0")


def node(**fields: object) -> dict[str, object]:
    return {
        "number": 11,
        "state": "CLOSED",
        "stateReason": "COMPLETED",
        "timelineItems": {
            "nodes": [
                {
                    "createdAt": "2026-10-07T08:00:00Z",
                    "closer": {"__typename": "PullRequest", "merged": True, "mergeCommit": {"oid": "a" * 40}},
                }
            ]
        },
        "closedByPullRequestsReferences": {
            "nodes": [{"merged": False, "mergeCommit": None}, {"merged": True, "mergeCommit": {"oid": "b" * 40}}]
        },
        "comments": {
            "nodes": [
                {"createdAt": "2026-10-07T09:00:00Z", "body": "x", "authorAssociation": "NONE", "author": None},
                {
                    "createdAt": "2026-10-07T09:00:00Z",
                    "body": "y",
                    "authorAssociation": "NONE",
                    "author": {"__typename": "Bot", "login": "app"},
                },
            ]
        },
        **fields,
    }


def test_parse_issue_closes_reads_fixes_and_comments() -> None:
    (found,) = parse_issue_closes({"data": {"repository": {"i11": node()}}}, [11])
    assert found.reason is CloseReason.COMPLETED
    assert found.fixes == ("a" * 40, "b" * 40)
    assert [(c.author, c.bot) for c in found.comments] == [("ghost", False), ("app", True)]
    (still,) = parse_issue_closes({"data": {"repository": {"i11": node(state="OPEN", stateReason=None)}}}, [11])
    assert still.open


@pytest.mark.parametrize(
    "answer",
    [
        {"errors": [{"message": "Could not resolve"}], "data": None},
        {"data": {"repository": {}}},
        {"data": {"repository": {"i11": node(stateReason="SOMETHING")}}},
        {"data": {"repository": {"i11": node(closedByPullRequestsReferences={"nodes": [{"merged": True}]})}}},
    ],
)
def test_parse_issue_closes_refuses_a_misread(answer: object) -> None:
    with pytest.raises(ReleaseError):
        parse_issue_closes(answer, [11])
