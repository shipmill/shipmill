"""Spec 070's "Released at once": the merge that completes an expedite outcome makes the stable
lane due (the rc lane, when stable promotes) without waiting for quiet time or a window, every
gate still applies, and a shipped outcome makes nothing due again; with no class label, every
plan and the walk's order are as before"""

import datetime as dt
import re
from pathlib import Path
from typing import Any

import pytest

from shipmill.errors import ReleaseError
from shipmill.findings import Finding
from shipmill.github import (
    Closing,
    IssueComment,
    Milestone,
    MilestoneIssues,
    OpenIssue,
    Outcome,
    ShippedPull,
    parse_expedite_outcomes,
)
from shipmill.planner import BREAKING, Decision, Event
from shipmill.walk import EXPEDITED, TIERS, order, tier_of

from .conftest import Repo, Repos, at_day
from .test_breaking_hold import EVERY_BATCH, HEAD, HEADINGS, PROMOTE, use_policy
from .test_lanes import plan, release

ROOT = Path(__file__).resolve().parents[1]
AGENTS = '\n[agents]\nprompt = "/t"\napp_id = 7\n'
STABLE = HEAD + HEADINGS + EVERY_BATCH  # stable from main once quiet for 30 minutes
MERGED = at_day(0, 8)  # #1 merges; the stable lane is quiet-due from 08:30
NOW = MERGED + dt.timedelta(minutes=10)  # main quiet for 10 minutes: no trigger of its own is due
ACCEPTED = frozenset({"opportunity", "planned", "expedite"})


def closing(number: int, merge: str | None, at: dt.datetime | None = MERGED, here: bool = True) -> Closing:
    """An issue closed at `at` by the pull request that landed as merge; open with at None"""
    return Closing(number, here, at, merge if at is not None else None)


def outcome(
    *subs: Closing,
    number: int = 40,
    labels: frozenset[str] = ACCEPTED,
    counted: frozenset[str] = frozenset({"expedite"}),
    issue: Closing | None = None,
) -> Outcome:
    """The expedite opportunity #40, open, its label a person's, with the sub-issues"""
    return Outcome(issue or closing(number, None, None), labels, counted, subs)


def _stable(repo: Repo, policy: str, heading: str) -> str:
    """The policy on main, then #1 merged at MERGED under heading; #1's merge commit"""
    repo.at(at_day(0, 6))
    use_policy(repo, policy, autonomy="act")
    repo.at(MERGED)
    return repo.merge(1, heading, "The expedited fix")


@pytest.fixture
def stable(tmp_path: Path, repos: Repos) -> tuple[Repo, str]:
    return repos.after(tmp_path, _stable, STABLE + AGENTS, "Fixed")


def _plan(repo: Repo, now: dt.datetime = NOW) -> Decision:
    return plan(repo, now, event=Event.PUSH)


# -- S-070-7: the stable lane is due at once -------------------------------------------------


def test_s070_7_the_merge_closing_the_last_open_sub_issue_makes_stable_due_before_quiet_time(
    stable: tuple[Repo, str],
) -> None:
    repo, merge = stable
    assert _plan(repo).action == "skip"  # quiet for 10 of 30 minutes, and no window
    repo.github.outcomes = [outcome(closing(41, "a" * 40, MERGED - dt.timedelta(days=1)), closing(42, merge))]
    decision = _plan(repo)
    assert (decision.action, str(decision.lane), str(decision.version)) == ("release", "stable", "1.0.1")
    assert decision.reason == "stable 1.0.1: 1 pending entries; expedite #40 complete"
    # the range's oldest commit, less an hour of slack, bounds the closed issues read
    assert repo.github.outcome_reads[-1] < MERGED


def test_s070_7_an_opportunity_with_no_sub_issue_is_complete_once_its_own_pull_request_merged(
    stable: tuple[Repo, str],
) -> None:
    repo, merge = stable
    repo.github.outcomes = [outcome(issue=closing(40, merge))]
    assert _plan(repo).reason == "stable 1.0.1: 1 pending entries; expedite #40 complete"


def test_s070_7_an_open_milestone_with_work_open_does_not_stop_the_expedite_trigger(
    tmp_path: Path, repos: Repos
) -> None:
    """A lane with milestone = true whose milestone has open issues that aren't holds is no
    gate: the outcome still makes it due, as quiet time would"""
    repo, merge = repos.after(tmp_path, _stable, STABLE + "milestone = true\n" + AGENTS, "Fixed")
    repo.github.milestones["1.0.1"] = Milestone(1, 1)
    _due(repo, merge)
    assert _plan(repo).reason == "stable 1.0.1: 1 pending entries; expedite #40 complete"


def test_s070_7_a_milestone_parked_on_holds_does_not_stop_the_expedite_trigger(tmp_path: Path, repos: Repos) -> None:
    """A milestone whose open issues all wait on a decision (spec 068) names its hold, but is no
    gate: quiet time releases over it, and so does an expedite outcome"""
    repo, merge = repos.after(tmp_path, _stable, STABLE + "milestone = true\n" + AGENTS, "Fixed")
    repo.github.milestones["1.0.1"] = Milestone(1, 1)
    parked = OpenIssue(7, "Pick a name", frozenset({"needs-decision"}))
    repo.github.milestone_lists["1.0.1"] = MilestoneIssues("o/demo", ((7, ""),), (parked,))
    assert "milestone" in _plan(repo).reason  # the hold is named while nothing is due
    _due(repo, merge)
    assert _plan(repo).reason == "stable 1.0.1: 1 pending entries; expedite #40 complete"


INCOMPLETE = {
    "a sub-issue still open": lambda merge: outcome(closing(41, merge), closing(42, None, None)),
    "the last to close was closed by hand": lambda merge: outcome(
        closing(41, merge), closing(42, None, MERGED + dt.timedelta(minutes=1))
    ),
    "its completing merge isn't in main": lambda merge: outcome(closing(41, "b" * 40)),
    "a sub-issue of another repository closed last": lambda merge: outcome(
        closing(41, merge), closing(42, merge, MERGED + dt.timedelta(minutes=1), here=False)
    ),
    "the expedite label the App added": lambda merge: outcome(closing(41, merge), counted=frozenset()),
    "both class labels a person added": lambda merge: outcome(
        closing(41, merge), counted=frozenset({"expedite", "fixed-date"})
    ),
    "not accepted": lambda merge: outcome(closing(41, merge), labels=frozenset({"opportunity", "expedite"})),
}


@pytest.mark.parametrize("make", INCOMPLETE.values(), ids=INCOMPLETE.keys())
def test_s070_7_an_outcome_not_completed_by_the_candidates_merge_makes_nothing_due(
    stable: tuple[Repo, str], make: Any
) -> None:
    repo, merge = stable
    repo.github.outcomes = [make(merge)]
    decision = _plan(repo)
    assert (decision.action, decision.reason) == ("skip", "stable: 1.0.1 is ready but no trigger is due")


def test_s070_7_quiet_time_and_windows_keep_their_reason_and_read_nothing_new(stable: tuple[Repo, str]) -> None:
    repo, merge = stable
    repo.github.outcomes = [outcome(closing(41, merge))]
    decision = _plan(repo, MERGED + dt.timedelta(minutes=31))
    assert decision.reason == "stable 1.0.1: 1 pending entries; main quiet for 31 min"
    assert repo.github.outcome_reads == []


# -- S-070-8: a promoting stable lane ----------------------------------------------------------


def _promote(repo: Repo) -> str:
    """rc1 of 1.1.0 cut on day 1's window; #2 merged at 09:00 after it. #2's merge commit"""
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + PROMOTE + AGENTS, autonomy="act")
    repo.at(at_day(0, 8))
    repo.merge(1, "Added", "Feature A")
    release(repo, plan(repo, at_day(1)))
    repo.at(at_day(1, 9))
    return repo.merge(2, "Fixed", "The expedited fix")


@pytest.fixture
def promoting(tmp_path: Path, repos: Repos) -> tuple[Repo, str]:
    return repos.after(tmp_path, _promote)


def test_s070_8_with_a_promoting_stable_lane_the_rc_lane_is_due_instead(promoting: tuple[Repo, str]) -> None:
    repo, merge = promoting
    now = at_day(1, 9) + dt.timedelta(minutes=10)
    before = plan(repo, now)
    assert before.action == "skip"
    assert before.reason.startswith("stable: 1.1.0 is ready but no trigger is due; ")
    repo.github.outcomes = [outcome(closing(41, merge, at_day(1, 9)))]
    decision = plan(repo, now)
    assert (decision.action, str(decision.lane), str(decision.version)) == ("release", "rc", "1.1.0rc2")
    assert decision.reason == "rc 1.1.0rc2: 2 pending entries; expedite #40 complete"


def test_s070_8_the_stable_lanes_plan_is_unchanged(promoting: tuple[Repo, str]) -> None:
    repo, merge = promoting
    quiet = at_day(1, 9) + dt.timedelta(minutes=40)
    without = plan(repo, quiet)
    repo.github.outcomes = [outcome(closing(41, merge, at_day(1, 9)))]
    reads = len(repo.github.outcome_reads)
    assert plan(repo, quiet) == without  # stable promotes rc1 on its own trigger
    assert without.reason.startswith("stable 1.1.0: promotes v1.1.0rc1")
    assert len(repo.github.outcome_reads) == reads  # stable's own trigger asks nothing of expedite


# -- S-070-9: every gate still applies ---------------------------------------------------------


def _due(repo: Repo, merge: str) -> None:
    repo.github.outcomes = [outcome(closing(41, merge))]


def test_s070_9_a_shipmill_hold_issue_turns_the_expedite_release_into_a_proposal(stable: tuple[Repo, str]) -> None:
    repo, merge = stable
    _due(repo, merge)
    repo.github.holds = ["#9 Stop the factory"]
    decision = _plan(repo)
    assert decision.action == "propose"
    assert [(p.lane.value, p.cause) for p in decision.proposals] == [("stable", "held by shipmill-hold #9")]


def test_s070_9_a_release_blocker_holds_the_lane(stable: tuple[Repo, str]) -> None:
    repo, merge = stable
    _due(repo, merge)
    repo.github.blockers = ["#8 Broken build"]
    decision = _plan(repo)
    assert (decision.action, decision.reason) == (
        "skip",
        "stable: 1.0.1 held, open 'release-blocker' issues: #8 Broken build",
    )


def test_s070_9_a_major_bump_is_proposed_not_released(tmp_path: Path, repos: Repos) -> None:
    repo, merge = repos.after(tmp_path, _stable, STABLE + AGENTS, "Breaking")
    _due(repo, merge)
    decision = _plan(repo)
    assert decision.action == "propose"
    assert [(p.lane.value, str(p.version), p.cause) for p in decision.proposals] == [("stable", "2.0.0", BREAKING)]


def test_s070_9_an_open_veto_window_holds_a_lane_in_veto_lanes(tmp_path: Path, repos: Repos) -> None:
    gates = '\n[gates]\nveto_lanes = ["stable"]\n'
    repo, merge = repos.after(tmp_path, _stable, STABLE + gates + AGENTS, "Fixed")
    _due(repo, merge)
    until = NOW + dt.timedelta(hours=1)
    marker = f"<!-- shipmill:decided zone=security until={until:%Y-%m-%dT%H:%M:%SZ} -->\nDecided"
    owner = IssueComment("amy", False, "OWNER", NOW - dt.timedelta(hours=1), marker)
    repo.github.shipped = [ShippedPull(1, merge, MERGED, (owner,), ())]
    decision = _plan(repo)
    assert (decision.action, decision.reason) == (
        "skip",
        "stable: 1.0.1 waits for veto windows: #1 security until 2026-10-05 09:10 UTC",
    )


def test_s070_9_ci_on_the_release_commit_still_gates_the_land() -> None:
    """The trigger only names the plan's reason: the release commit prepare pushes runs CI, and
    land runs only when that CI succeeded, whatever made the lane due"""
    release_yml = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    land_yml = (ROOT / ".github" / "workflows" / "land.yml").read_text(encoding="utf-8")
    assert "ref: ${{ needs.prepare.outputs.sha }}" in release_yml.split("  ci:", 1)[1].split("  land:", 1)[0]
    assert "ci-result: ${{ needs.ci.result }}" in release_yml.split("  land:", 1)[1]
    assert re.search(r"^  land:\n    if: inputs\.ci-result == 'success'$", land_yml, re.MULTILINE)


# -- S-070-10: an outcome shipped makes nothing due again --------------------------------------


def test_s070_10_once_a_release_holds_the_completing_merge_the_outcome_makes_nothing_due(
    stable: tuple[Repo, str],
) -> None:
    repo, merge = stable
    _due(repo, merge)
    release(repo, _plan(repo))  # v1.0.1 holds #1
    repo.at(NOW + dt.timedelta(minutes=5))
    repo.merge(2, "Fixed", "Another fix")
    decision = _plan(repo, NOW + dt.timedelta(minutes=10))
    assert (decision.action, decision.reason) == ("skip", "stable: 1.0.2 is ready but no trigger is due")


def test_s070_10_with_nothing_merged_since_the_release_nothing_is_read(stable: tuple[Repo, str]) -> None:
    repo, merge = stable
    _due(repo, merge)
    release(repo, _plan(repo))
    reads = len(repo.github.outcome_reads)
    assert _plan(repo, NOW + dt.timedelta(minutes=5)).action == "skip"
    assert len(repo.github.outcome_reads) == reads


# -- S-070-5: no class label, nothing changes --------------------------------------------------


def test_s070_5_without_agents_the_plan_reads_nothing_new_and_decides_as_before(tmp_path: Path, repos: Repos) -> None:
    repo, merge = repos.after(tmp_path, _stable, STABLE, "Fixed")
    repo.github.outcomes = [outcome(closing(41, merge))]
    repo.github.outcomes_error = "no read of expedite outcomes without [agents]"
    decision = _plan(repo)
    assert (decision.action, decision.reason) == ("skip", "stable: 1.0.1 is ready but no trigger is due")
    assert repo.github.outcome_reads == []


def test_s070_5_with_no_class_label_every_lanes_plan_is_as_before(stable: tuple[Repo, str]) -> None:
    repo, merge = stable
    before = [_plan(repo), _plan(repo, MERGED + dt.timedelta(minutes=31))]
    plain = outcome(closing(41, merge), labels=frozenset({"opportunity", "planned"}), counted=frozenset())
    repo.github.outcomes = [plain]
    assert [_plan(repo), _plan(repo, MERGED + dt.timedelta(minutes=31))] == before


def test_a_failed_expedite_read_fails_the_plan_rather_than_release(stable: tuple[Repo, str]) -> None:
    repo, _ = stable
    repo.github.outcomes_error = "HTTP 502"
    with pytest.raises(ReleaseError, match="HTTP 502"):
        _plan(repo)


def test_s070_5_with_no_expedite_row_the_walk_keeps_s046_12s_order() -> None:
    rows = [
        Finding("ISSUES", "o/r", "UNBLOCKED #2", True),
        Finding("PRS_OPEN", "o/r", "#7", True),
        Finding("LAND_DUE", "#30", "t: open", True),
        Finding("ISSUES", "o/r", "NEW #6", True),
        Finding("BOT_STALLED", "release.yml", "due", True),
        Finding("LAND_DUE", "#9", "t: open", True),
    ]

    def before(f: Finding) -> tuple[int, int, int, str, str]:  # S-046-12's key, with no expedite group
        tier = tier_of(f)
        kinds = TIERS.get(tier, ())
        place = kinds.index(f.kind) if f.kind in kinds else len(kinds)
        number = int(f.subject[1:]) if re.fullmatch(r"#\d+", f.subject) else 0
        return tier, place, number, f.subject, f.detail

    assert {3, 6} == EXPEDITED
    assert order(rows) == sorted(rows, key=before)
    assert order(list(reversed(rows))) == sorted(rows, key=before)


# -- the read ------------------------------------------------------------------------------------


def _issue(number: int, state: str = "OPEN", closer: Any = None, repo: str = "o/demo", **more: Any) -> dict[str, Any]:
    events = [{"createdAt": "2026-10-05T08:00:00Z", "closer": closer}] if state == "CLOSED" else []
    return {
        "number": number,
        "state": state,
        "repository": {"nameWithOwner": repo},
        "closes": {"nodes": events},
        **more,
    }


def _answer(*nodes: dict[str, Any], closed: tuple[dict[str, Any], ...] = (), more: bool = False) -> dict[str, Any]:
    return {
        "data": {
            "repository": {
                "nameWithOwner": "o/demo",
                "open": {"pageInfo": {"hasNextPage": more}, "nodes": list(nodes)},
                "closed": {"pageInfo": {"hasNextPage": False}, "nodes": list(closed)},
            }
        }
    }


PULL = {"__typename": "PullRequest", "merged": True, "mergeCommit": {"oid": "c" * 40}}


def _opportunity(number: int, actor: dict[str, str], *subs: dict[str, Any], **more: Any) -> dict[str, Any]:
    return _issue(
        number,
        labels={"totalCount": 3, "nodes": [{"name": n} for n in sorted(ACCEPTED)]},
        labelled={"nodes": [{"label": {"name": "expedite"}, "actor": actor}]},
        subIssues={"totalCount": len(subs), "nodes": list(subs)},
        **more,
    )


def test_s070_7_the_read_finds_the_merge_that_closed_the_last_sub_issue() -> None:
    person = {"__typename": "User", "login": "amy"}
    found = parse_expedite_outcomes(
        _answer(_opportunity(40, person, _issue(41, "CLOSED", PULL), _issue(42, "CLOSED", {"__typename": "Commit"})))
    )
    assert [o.number for o in found] == [40]
    [read] = found
    assert read.expedite and read.counted == {"expedite"}
    assert read.subs == (closing(41, "c" * 40, MERGED), closing(42, None, MERGED))
    app = parse_expedite_outcomes(_answer(_opportunity(40, {"__typename": "Bot", "login": "shipmill"})))
    assert not app[0].expedite  # the App's label counts as no label (S-070-1)


def test_s070_7_the_read_refuses_a_list_longer_than_it_reads() -> None:
    with pytest.raises(ReleaseError, match="more than 100 open issues labelled expedite"):
        parse_expedite_outcomes(_answer(more=True))
    many = _opportunity(40, {"__typename": "User", "login": "amy"})
    many["subIssues"]["totalCount"] = 101
    with pytest.raises(ReleaseError, match="#40 with more than 100 sub-issues"):
        parse_expedite_outcomes(_answer(many))
    with pytest.raises(ReleaseError, match="errors or no object"):
        parse_expedite_outcomes({"errors": [{"message": "Bad credentials"}]})


def test_s070_7_the_read_refuses_a_label_event_without_its_label() -> None:
    malformed = _opportunity(40, {"__typename": "User", "login": "amy"})
    malformed["labelled"]["nodes"][0]["label"] = "expedite"
    with pytest.raises(ReleaseError, match="#40 without its label events"):
        parse_expedite_outcomes(_answer(malformed))
