"""Spec 059: a lane in [gates] veto_lanes waits for the veto window of each notify decision it
would ship, read from the merged pull requests in its range and the issues they close"""

import datetime as dt
import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.github import IssueComment, ShippedIssue, ShippedPull, parse_shipped_pulls
from shipmill.planner import Decision, Event
from shipmill.policy import Lane

from .conftest import Repo, Repos, at_day
from .test_breaking_hold import HEAD, HEADINGS, start, use_policy
from .test_lanes import plan, release

APP = 7
RC = '[lanes.rc]\nschedule = ["daily 07:00 UTC"]\ngithub_release = true\n'
PROMOTE = RC + '\n[lanes.stable]\npromote_from = "rc"\nquiet_minutes = 30\ngithub_release = true\n'
AGENTS = f'\n[agents]\nprompt = "/t"\napp_id = {APP}\n'
NOW = at_day(2)  # 2026-10-07 08:00 UTC: the rc window opened at 07:00


def _gates(*lanes: str) -> str:
    return f"\n[gates]\nveto_lanes = {json.dumps(list(lanes))}\n"


def _rc_after_a_tag(repo: Repo, veto_lanes: tuple[str, ...]) -> tuple[str, str]:
    """rc1 holds #1; #2 merged after it, so rc2 would ship #2 only. The two merge commits"""
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + RC + _gates(*veto_lanes) + AGENTS)
    first = repo.merge(1, "Added", "Feature A")
    release(repo, plan(repo, at_day(1)))
    repo.at(at_day(1, 9))
    second = repo.merge(2, "Fixed", "Fix B")
    return first, second


def comment(body: str, at: dt.datetime, author: str = "shipmill", association: str = "NONE") -> IssueComment:
    """A comment; the App's own (a Bot) by default"""
    return IssueComment(author, author == "shipmill", association, at, body)


def decided(until: dt.datetime, at: dt.datetime = NOW - dt.timedelta(hours=1), zone: str = "security") -> str:
    return f"<!-- shipmill:decided zone={zone} until={until:%Y-%m-%dT%H:%M:%SZ} -->\n@amy Decided without waiting: x"


def pull(number: int, merge: str, *comments: IssueComment, closes: tuple[ShippedIssue, ...] = ()) -> ShippedPull:
    return ShippedPull(number, merge, at_day(1, 9), tuple(comments), closes)


def app_marker(
    until: dt.datetime, at: dt.datetime = NOW - dt.timedelta(hours=1), zone: str = "security"
) -> IssueComment:
    return comment(decided(until, at, zone) + "\n\n<!-- shipmill:agent -->", at)


OPEN = NOW + dt.timedelta(hours=1)
WAITS = "rc: 1.1.0rc2 waits for veto windows: #2 security until 2026-10-07 09:00 UTC"


@pytest.fixture
def rc(tmp_path: Path, repos: Repos) -> tuple[Repo, str, str]:
    repo, (first, second) = repos.after(tmp_path, _rc_after_a_tag, ("rc",))
    repo.github.apps = {"shipmill": APP, "other-app": 9}
    repo.github.shipped_reads = []  # rc1's own plan read the last 168 hours
    return repo, first, second


def _plan(repo: Repo) -> Decision:
    return plan(repo, NOW, event=Event.SCHEDULE)


def test_s059_2_without_veto_lanes_the_plan_reads_nothing_new_and_decides_as_before(
    tmp_path: Path, repos: Repos
) -> None:
    repo, (_, second) = repos.after(tmp_path, _rc_after_a_tag, ())
    repo.github.shipped = [pull(2, second, app_marker(OPEN))]
    repo.github.shipped_error = "no read of pull requests, issues, or comments without veto_lanes"
    decision = _plan(repo)
    assert (decision.action, str(decision.version)) == ("release", "1.1.0rc2")
    assert decision.reason == "rc 1.1.0rc2: 2 pending entries; window 'daily 07:00 UTC' opened at 2026-10-07 07:00 UTC"
    assert repo.github.shipped_reads == []


def test_s059_3_an_open_window_on_a_shipped_pull_request_holds_the_lane_until_it_ends(
    rc: tuple[Repo, str, str],
) -> None:
    repo, _, second = rc
    repo.github.shipped = [pull(2, second, app_marker(OPEN))]
    decision = _plan(repo)
    assert (decision.action, decision.reason) == ("skip", WAITS)
    repo.github.shipped = [pull(2, second, app_marker(NOW - dt.timedelta(minutes=1)))]
    decision = _plan(repo)
    assert (decision.action, str(decision.version)) == ("release", "1.1.0rc2")


def test_s059_3_the_reason_lists_each_window_oldest_first(rc: tuple[Repo, str, str]) -> None:
    repo, _, second = rc
    later = app_marker(NOW + dt.timedelta(hours=2), zone="protected")
    repo.github.shipped = [pull(2, second, later, app_marker(OPEN))]
    assert _plan(repo).reason == f"{WAITS}, #2 protected until 2026-10-07 10:00 UTC"


def test_s059_4_a_marker_on_an_issue_a_shipped_pull_request_closes_holds_the_lane(
    rc: tuple[Repo, str, str],
) -> None:
    repo, first, second = rc
    issue = ShippedIssue(5, None, (app_marker(OPEN),))
    other = ShippedIssue(6, "o/lib", (app_marker(OPEN + dt.timedelta(hours=1)),))
    repo.github.shipped = [pull(2, second, closes=(issue, other))]
    assert _plan(repo).reason == (
        "rc: 1.1.0rc2 waits for veto windows: #5 security until 2026-10-07 09:00 UTC,"
        " o/lib#6 security until 2026-10-07 10:00 UTC"
    )
    # #1 merged before the lane's newest tag, v1.1.0rc1: its window, and its issue's, hold nothing
    repo.github.shipped = [pull(1, first, app_marker(OPEN), closes=(issue,)), pull(2, second)]
    decision = _plan(repo)
    assert (decision.action, str(decision.version)) == ("release", "1.1.0rc2")
    # the read starts an hour before the range's oldest commit, #2's merge at day 1 09:00
    assert repo.github.shipped_reads[-1] == at_day(1, 8)


UNTRUSTED = {
    "an outsider": comment(decided(OPEN), NOW - dt.timedelta(hours=1), "mallory", "CONTRIBUTOR"),
    "another App": IssueComment("other-app", True, "NONE", NOW - dt.timedelta(hours=1), decided(OPEN)),
    "not the first line": comment("Done.\n" + decided(OPEN), NOW - dt.timedelta(hours=1)),
}


@pytest.mark.parametrize("marker", UNTRUSTED.values(), ids=UNTRUSTED.keys())
def test_s059_5_an_untrusted_marker_or_one_not_on_the_first_line_holds_nothing(
    rc: tuple[Repo, str, str], marker: IssueComment
) -> None:
    repo, _, second = rc
    repo.github.shipped = [pull(2, second, marker)]
    assert _plan(repo).action == "release"


def test_s059_5_a_members_own_marker_holds_the_lane(rc: tuple[Repo, str, str]) -> None:
    repo, _, second = rc
    repo.github.shipped = [pull(2, second, comment(decided(OPEN), NOW - dt.timedelta(hours=1), "amy", "MEMBER"))]
    assert _plan(repo).reason == WAITS


PAST = NOW - dt.timedelta(hours=2)
MARKED = app_marker(PAST, NOW - dt.timedelta(hours=26))
VETO = comment("Veto: keep the old default", NOW - dt.timedelta(hours=25), "amy", "COLLABORATOR")
VETOED = "rc: 1.1.0rc2 waits for veto windows: #2 security vetoed, until the veto is handled"


def test_s059_6_an_unhandled_veto_holds_the_lane_after_its_window(rc: tuple[Repo, str, str]) -> None:
    repo, _, second = rc
    repo.github.shipped = [pull(2, second, MARKED, VETO)]
    assert _plan(repo).reason == VETOED


LEFT_TO_ITS_WINDOW = {
    "handled": (VETO, comment("<!-- shipmill:veto-handled zone=security -->\nReverted.", NOW - dt.timedelta(hours=3))),
    "a contributor's": (comment("veto", NOW - dt.timedelta(hours=25), "mallory", "CONTRIBUTOR"),),
    "an agent's": (comment("Veto\n\n<!-- shipmill:agent -->", NOW - dt.timedelta(hours=25), "amy", "COLLABORATOR"),),
    "before the marker": (comment("veto", NOW - dt.timedelta(hours=27), "amy", "COLLABORATOR"),),
    "not the first word": (comment("I would not veto this", NOW - dt.timedelta(hours=25), "amy", "OWNER"),),
}


@pytest.mark.parametrize("later", LEFT_TO_ITS_WINDOW.values(), ids=LEFT_TO_ITS_WINDOW.keys())
def test_s059_6_a_handled_untrusted_or_agents_veto_leaves_the_lane_to_its_window(
    rc: tuple[Repo, str, str], later: tuple[IssueComment, ...]
) -> None:
    repo, _, second = rc
    comments = sorted((MARKED, *later), key=lambda c: c.created_at)
    repo.github.shipped = [pull(2, second, *comments)]
    assert _plan(repo).action == "release"


def test_s059_7_a_persons_hand_start_releases_a_bots_or_an_unnamed_one_waits(rc: tuple[Repo, str, str]) -> None:
    repo, _, second = rc
    repo.github.shipped = [pull(2, second, app_marker(OPEN))]
    person = start(repo, NOW, "octocat", Lane.RC)
    assert (person.action, str(person.version), person.reason) == (
        "release",
        "1.1.0rc2",
        "rc 1.1.0rc2: 2 pending entries; started by hand",
    )
    assert repo.github.shipped_reads == []  # a person's hand start reads nothing
    for actor in ("shipmill[bot]", None):
        assert start(repo, NOW, actor, Lane.RC).reason == WAITS


def _rc_without_a_tag(repo: Repo) -> str:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + RC + _gates("rc") + AGENTS)
    return repo.merge(1, "Added", "Feature A")


def test_s059_8_a_lane_with_no_tag_reads_the_pull_requests_merged_in_the_last_168_hours(
    tmp_path: Path, repos: Repos
) -> None:
    repo, merge = repos.after(tmp_path, _rc_without_a_tag)
    repo.github.apps = {"shipmill": APP}
    now = at_day(1)
    old = repo.git.sha("v1.0.0")  # in the base, but merged more than 168 hours ago
    stale = ShippedPull(9, old, now - dt.timedelta(hours=169), (app_marker(now + dt.timedelta(hours=3), now),), ())
    repo.github.shipped = [stale]
    assert plan(repo, now).action == "release"
    assert repo.github.shipped_reads == [now - dt.timedelta(hours=168)]
    fresh = ShippedPull(1, merge, at_day(0, 6), (app_marker(now + dt.timedelta(hours=1), now),), ())
    repo.github.shipped = [stale, fresh]
    assert plan(repo, now).reason == "rc: 1.1.0rc1 waits for veto windows: #1 security until 2026-10-06 09:00 UTC"


def _promotion(repo: Repo) -> tuple[str, str]:
    """rc1 holds #1, #2 merged after it; stable would promote rc1"""
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + PROMOTE + _gates("stable") + AGENTS)
    first = repo.merge(1, "Added", "Feature A")
    release(repo, plan(repo, at_day(1)))
    repo.at(at_day(1) + dt.timedelta(minutes=10))
    second = repo.merge(2, "Fixed", "Fix B")
    return first, second


def test_s059_8_a_stable_promotion_reads_from_the_newest_stable_tag_to_the_rcs_base(
    tmp_path: Path, repos: Repos
) -> None:
    repo, (first, second) = repos.after(tmp_path, _promotion)
    repo.github.apps = {"shipmill": APP}
    now = at_day(1, 9)
    until = now + dt.timedelta(hours=1)
    repo.github.shipped = [pull(1, first, app_marker(until, now)), pull(2, second)]
    decision = plan(repo, now)
    assert decision.action == "skip"
    assert "stable: 1.1.0 waits for veto windows: #1 security until 2026-10-06 10:00 UTC" in decision.reason
    # #2 is past the rc's base: its window holds the next promotion, not this one
    repo.github.shipped = [pull(1, first), pull(2, second, app_marker(until, now))]
    decision = plan(repo, now)
    assert (decision.action, decision.lane, str(decision.version)) == ("release", Lane.STABLE, "1.1.0")


BAD_UNTIL = {
    "not a UTC time": "<!-- shipmill:decided zone=security until=2026-10-07T09:00:00+02:00 -->",
    "no time": "<!-- shipmill:decided zone=security until=tomorrow -->",
    "no such day": "<!-- shipmill:decided zone=security until=2026-10-32T09:00:00Z -->",
    "no zone": "<!-- shipmill:decided until=2026-10-07T09:00:00Z -->",
    "past 168 hours": "<!-- shipmill:decided zone=security until=2026-10-14T08:00:00Z -->",
}


@pytest.mark.parametrize("line", BAD_UNTIL.values(), ids=BAD_UNTIL.keys())
def test_s059_9_a_trusted_marker_with_a_bad_until_exits_2_naming_the_item(rc: tuple[Repo, str, str], line: str) -> None:
    repo, _, second = rc
    repo.github.shipped = [pull(2, second, comment(line, NOW - dt.timedelta(hours=1)))]
    with pytest.raises(ReleaseError, match="^#2: the decided marker of @shipmill's comment at 2026-10-07 07:00 UTC"):
        _plan(repo)
    argv = ["--repo", str(repo.root), "plan", "--event", "schedule", "--now", NOW.isoformat()]
    with pytest.raises(ReleaseError, match="^#2: "):
        main(argv, repo.github)  # run() prints it and exits 2


def test_s059_9_an_untrusted_marker_with_a_bad_until_is_not_read(rc: tuple[Repo, str, str]) -> None:
    repo, _, second = rc
    bad = comment("<!-- shipmill:decided zone=security until=never -->", NOW, "mallory", "NONE")
    repo.github.shipped = [pull(2, second, bad)]
    assert _plan(repo).action == "release"


def _page(nodes: list[object], more: bool = False) -> dict[str, object]:
    connection = {"pageInfo": {"hasNextPage": more, "endCursor": "c1" if more else None}, "nodes": nodes}
    return {"data": {"repository": {"nameWithOwner": "o/demo", "pullRequests": connection}}}


def _comments(*bodies: str, total: int | None = None) -> dict[str, object]:
    nodes = [
        {"createdAt": "2026-10-07T07:00:00Z", "body": b, "authorAssociation": "NONE", "author": None} for b in bodies
    ]
    return {"totalCount": len(nodes) if total is None else total, "nodes": nodes}


def _node(number: int, comments: dict[str, object], closes: Sequence[object]) -> dict[str, object]:
    return {
        "number": number,
        "updatedAt": "2026-10-07T07:30:00Z",
        "mergedAt": "2026-10-06T09:00:00Z",
        "mergeCommit": {"oid": "a" * 40},
        "comments": comments,
        "closingIssuesReferences": {"totalCount": len(closes), "nodes": closes},
    }


def test_s059_3_the_shipped_read_parses_the_pull_requests_and_the_issues_they_close() -> None:
    issues = [
        {"number": 5, "repository": {"nameWithOwner": "O/Demo"}, "comments": _comments("x")},
        {"number": 6, "repository": {"nameWithOwner": "o/lib"}, "comments": _comments()},
    ]
    page = parse_shipped_pulls(_page([_node(2, _comments("hi"), issues)], more=True))
    [shipped] = page.pulls
    assert (shipped.number, shipped.merge, shipped.merged_at) == (2, "a" * 40, at_day(1, 9))
    assert [c.author for c in shipped.comments] == ["ghost"]
    assert [i.name for i in shipped.closes] == ["#5", "o/lib#6"]
    assert (page.more, page.cursor, page.oldest) == (True, "c1", at_day(2, 7) + dt.timedelta(minutes=30))


def test_s059_3_the_shipped_read_refuses_more_comments_than_it_reads() -> None:
    # a decided marker past the comments read would release inside its window
    with pytest.raises(ReleaseError, match="#2 has 101 comments, over the 100"):
        parse_shipped_pulls(_page([_node(2, _comments("hi", total=101), [])]))


def _folded(*parts: str) -> str:
    """A doc with its line wrapping folded, so a statement reads as one line"""
    root = Path(__file__).resolve().parents[1]
    return " ".join(root.joinpath(*parts).read_text(encoding="utf-8").split())


def test_s059_12_the_docs_document_veto_lanes() -> None:
    lanes = _folded("docs", "release-lanes.md")
    assert '# veto_lanes = ["rc", "stable"]' in lanes  # beside blocker_lanes and freeze_lanes
    # what a release ships
    assert "**What a release ships**" in lanes
    assert "merge commit is in the candidate's base and not in the lane's newest tag" in lanes
    assert "the pull requests merged in the last 168 hours" in lanes
    assert "<!-- shipmill:decided zone=<id> until=<UTC time> -->" in lanes
    assert "<!-- shipmill:veto-handled -->" in lanes
    # the wait, with the plan's reason
    assert "**The wait.**" in lanes
    assert "rc: 0.8.0rc17 waits for veto windows: #196 security until 2026-11-10 14:00 UTC" in lanes
    assert "#196 security vetoed, until the veto is handled" in lanes
    # a person's hand start, and a bot's
    assert "**a person's hand start**" in lanes and "releases inside a window" in lanes
    assert "A hand start by a `<name>[bot]` login, or one that names no actor, waits" in lanes
    assert "`hotfix` can't be in `veto_lanes`" in lanes
    # the hourly tick
    assert "needs **the hourly tick**" in lanes
    assert "or `[gates] veto_lanes` names an enabled lane" in lanes
    needs = _folded("skills", "github-issue-triage", "references", "needs-decision.md")
    holds = "a lane in `[gates] veto_lanes` holds a release that would ship a `notify` decision until its window ends"
    assert holds in needs
