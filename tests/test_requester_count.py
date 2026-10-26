"""A stable promotion's reason counts the issues its rc fixed whose requester confirmed, and
the count never changes whether the lane is due (spec 021, S-021-8)"""

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from shipmill.errors import ReleaseError
from shipmill.github import (
    CLOSED_LIMIT,
    CloseReason,
    IssueClose,
    RequesterVotes,
    Voted,
    parse_closed,
    parse_requester_votes,
)
from shipmill.planner import Decision, Event, Planner
from shipmill.requesters import confirmed

from .conftest import Repo, Repos, at_day
from .test_lanes import release


def notice(tag: str, *thumbs: str, stage: str = "pre-release") -> Voted:
    return Voted(f"<!-- shipmill:available: {stage} {tag} -->", frozenset(thumbs))


def closed(number: int, fix: str, when: dt.datetime) -> IssueClose:
    return IssueClose(number, CloseReason.COMPLETED, when, (fix,), ())


def plan(repo: Repo, now: dt.datetime) -> Decision:
    repo.git.fetch("+refs/heads/main:refs/remotes/origin/main")
    repo.git.run("checkout", "-q", "--detach", "origin/main")
    return Planner(repo.git, repo.policy, repo.github, now).plan(Event.SCHEDULE)


def promote(repo: Repo) -> None:
    """rc1 holds the fix of #11, #12, and #16; #13 is fixed after it, #14 before 1.0.0, and #15
    is open. #11's requester confirmed rc1, #12's didn't (only someone else did), #16 is a bot's"""
    old = repo.git.sha("v1.0.0")
    repo.at(at_day(0))
    fix = repo.merge(1, "Added", "Feature A", "src/a.py", "A = 1\n")
    release(repo, plan(repo, at_day(1)))  # the rc window cuts rc1
    repo.at(at_day(1, 9))
    later = repo.merge(2, "Fixed", "Fix B, after the rc")
    gh = repo.github
    for number in (11, 12, 16):
        gh.closes[number] = closed(number, fix, at_day(0, 9))
    gh.closes[13] = closed(13, later, at_day(1, 9))
    gh.closes[14] = closed(14, old, at_day(0, 9))
    gh.closes[15] = IssueClose(15, None, None, (), ())
    gh.votes[11] = RequesterVotes(11, "alice", (notice("v1.1.0rc1", "alice", "bob"),))
    gh.votes[12] = RequesterVotes(12, "carol", (notice("v1.1.0rc1", "bob"),))
    gh.votes[16] = RequesterVotes(16, None, (notice("v1.1.0rc1", "bob"),))


@pytest.fixture
def promoting(repos: Repos, tmp_path: Path) -> Repo:
    return repos.after(tmp_path, promote)[0]


def test_s021_8_the_promotion_s_reason_counts_the_rc_s_confirmed_requesters(promoting: Repo) -> None:
    decision = plan(promoting, at_day(4))
    assert (decision.action, str(decision.version)) == ("release", "1.1.0")
    # rc1 was cut at day 0's time
    assert decision.reason.startswith(
        "stable 1.1.0: promotes v1.1.0rc1, cut 4 day(s) ago; 1 of 3 requesters confirmed;"
    )
    # only the issues rc1's base holds a fix for, past v1.0.0, had their votes read
    assert promoting.github.vote_reads == [(11, 12, 16)]
    # closed issues are read from the day before the range's oldest commit
    assert promoting.github.closed_reads == [(at_day(0) - dt.timedelta(days=1)).date()]


def test_s021_8_the_count_never_changes_whether_the_lane_is_due(promoting: Repo) -> None:
    def outcome(decision: Decision) -> tuple[object, ...]:
        return decision.action, decision.lane, decision.version, decision.base

    confirmed_one = plan(promoting, at_day(4))
    promoting.github.votes = {}
    none_confirmed = plan(promoting, at_day(4))
    promoting.github.votes_error = "HTTP 502"
    unread = plan(promoting, at_day(4))
    assert outcome(confirmed_one) == outcome(none_confirmed) == outcome(unread)
    assert "1 of 3 requesters confirmed" in confirmed_one.reason
    assert "0 of 3 requesters confirmed" in none_confirmed.reason
    assert "requesters not counted: gh api graphql failed: HTTP 502" in unread.reason


def test_s021_8_the_votes_are_read_only_once_the_lane_releases(promoting: Repo) -> None:
    policy = promoting.read(promoting.policy_file)
    stable = 'schedule = ["Mon 07:00 UTC"]'
    assert policy.count(stable) == 1
    # no milestone named 1.1.0: never due; main has been quiet for 3 days: due with 60 quiet minutes
    promoting.write(promoting.policy_file, policy.replace(stable, "milestone = true"))
    waiting = plan(promoting, at_day(4))
    # stable waits for its milestone, so the rc lane releases instead
    assert waiting.lane is not None and waiting.lane.value == "rc" and str(waiting.version) == "1.1.0rc2"
    assert promoting.github.vote_reads == [] and promoting.github.closed_reads == []
    promoting.github.votes = {}
    assert plan(promoting, at_day(4)) == waiting
    promoting.write(promoting.policy_file, policy.replace(stable, "quiet_minutes = 60"))
    due = plan(promoting, at_day(4))
    assert due.lane is not None and due.lane.value == "stable" and "0 of 3 requesters confirmed" in due.reason


def test_s021_8_a_confirmation_is_the_requester_s_thumbs_up_on_the_newest_pre_release_notice() -> None:
    rc1, rc2 = notice("v1.1.0rc1", "alice"), notice("v1.1.0rc2")
    assert confirmed(RequesterVotes(1, "alice", (rc1,)))
    assert not confirmed(RequesterVotes(1, "alice", (rc1, rc2)))  # the newest notice is unanswered
    assert confirmed(RequesterVotes(1, "alice", (rc1, notice("v1.1.0", "bob", stage="stable"))))
    assert not confirmed(RequesterVotes(1, "alice", (notice("v1.1.0rc1", "bob"),)))  # someone else's 👍
    assert not confirmed(RequesterVotes(1, None, (notice("v1.1.0rc1", "alice"),)))  # a bot's issue
    # a marker naming no pre-release tag is no notice, so it hides no answer
    forged = notice("anything")
    assert confirmed(RequesterVotes(1, "alice", (rc1, forged)))
    assert not confirmed(RequesterVotes(1, "alice", (Voted("Released in v1.1.0rc1.", frozenset({"alice"})),)))


def test_s021_8_an_answer_past_what_was_read_is_refused_not_counted_as_none() -> None:
    rc1 = notice("v1.1.0rc1", "alice")
    many = Voted(notice("v1.1.0rc1").first_line, frozenset({"bob"}), more=True)
    # the requester's 👍 among those read, or every 👍 read: the answer is known
    assert confirmed(RequesterVotes(1, "alice", (Voted(rc1.first_line, rc1.thumbs_up, more=True),), earlier=True))
    assert not confirmed(RequesterVotes(1, "alice", (notice("v1.1.0rc1", "bob"),), earlier=True))
    assert not confirmed(RequesterVotes(1, None, (), earlier=True))  # no requester: nothing to miss
    # the notice may sit before the newest comments read, or the 👍 past the first read
    with pytest.raises(ReleaseError, match="#1 has more than 100 comments"):
        confirmed(RequesterVotes(1, "alice", (), earlier=True))
    with pytest.raises(ReleaseError, match="#1's pre-release notice has more than 100"):
        confirmed(RequesterVotes(1, "alice", (many,)))


def test_s021_8_requester_votes_parse_github_s_answer() -> None:
    def comment(body: str, *users: object) -> dict[str, object]:
        return {"body": body, "reactions": {"totalCount": len(users), "nodes": [{"user": u} for u in users]}}

    empty = {"totalCount": 0, "nodes": []}
    found: dict[str, Any] = {
        "data": {
            "repository": {
                "i5": {
                    "number": 5,
                    "author": {"__typename": "User", "login": "alice"},
                    "comments": {
                        "totalCount": 1,
                        "nodes": [
                            comment(
                                "<!-- shipmill:available: pre-release v1.1.0rc1 -->\nReleased", {"login": "alice"}, None
                            )
                        ],
                    },
                },
                "i6": {"number": 6, "author": {"__typename": "Bot", "login": "renovate"}, "comments": empty},
                "i7": {"number": 7, "author": None, "comments": empty},
                # the watch's rule: GitHub names every deleted account ghost, so it is nobody's requester
                "i8": {"number": 8, "author": {"__typename": "User", "login": "ghost"}, "comments": empty},
            }
        }
    }
    votes = parse_requester_votes(found, [5, 6, 7, 8])
    assert votes == [
        RequesterVotes(5, "alice", (notice("v1.1.0rc1", "alice"),)),
        RequesterVotes(6, None, ()),
        RequesterVotes(7, None, ()),
        RequesterVotes(8, None, ()),
    ]
    # more comments or 👍s than were read are marked, so a missed answer is never counted as none
    i5 = found["data"]["repository"]["i5"]
    cut = {**i5, "comments": {"totalCount": 101, "nodes": [{**i5["comments"]["nodes"][0], "reactions": {
        "totalCount": 101, "nodes": [{"user": {"login": "bob"}}]}}]}}  # fmt: skip
    [truncated] = parse_requester_votes({"data": {"repository": {"i5": cut}}}, [5])
    assert truncated == RequesterVotes(
        5, "alice", (Voted(notice("v1.1.0rc1").first_line, frozenset({"bob"}), True),), True
    )
    with pytest.raises(ReleaseError, match="no issue #9"):
        parse_requester_votes(found, [9])
    with pytest.raises(ReleaseError, match="errors"):
        parse_requester_votes({"errors": [{"message": "boom"}]}, [5])
    with pytest.raises(ReleaseError, match="a reaction's user needs a login"):
        parse_requester_votes(
            {
                "data": {
                    "repository": {
                        "i5": {**found["data"]["repository"]["i5"], "comments": {"nodes": [comment("x", {"id": 1})]}}
                    }
                }
            },
            [5],
        )


def test_s021_8_closed_issues_parse_and_a_full_page_is_refused() -> None:
    assert parse_closed([{"number": 9}, {"number": 3}], dt.date(2026, 10, 1)) == [3, 9]
    with pytest.raises(ReleaseError, match="an issue needs a number"):
        parse_closed([{"number": "3"}], None)
    with pytest.raises(ReleaseError, match=f"{CLOSED_LIMIT} issues closed since 2026-10-01 or more"):
        parse_closed([{"number": n} for n in range(CLOSED_LIMIT)], dt.date(2026, 10, 1))
