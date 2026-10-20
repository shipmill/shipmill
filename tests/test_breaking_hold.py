"""A breaking change waits for the maintainer (spec 029): a trigger never releases a stable
candidate whose pending entries sit under a `major` heading, it proposes it; a person starting
the stable lane by hand releases it. And stable promotes an rc of any age once a trigger is due"""

import datetime as dt
import json

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.github import PROPOSAL_LABEL
from shipmill.planner import BREAKING, Actor, Decision, Event, Planner, Proposal
from shipmill.policy import Lane
from shipmill.propose import Outcome, close_released, propose
from shipmill.version import Version

from .conftest import Repo, at_day
from .test_fragments import add_fragment, use_fragments
from .test_lanes import _tag_on_main, plan, release

HEAD = """\
name = "demo"
mode = "release"
branch = "main"
version_files = "pyproject"

[changelog]
style = "keep-a-changelog"

"""

HEADINGS = """\
[bump]
from = "headings"
major = ["Breaking"]
minor = ["Added", "Changed"]
patch = ["Fixed"]

"""

PATHS = """\
[bump]
from = "paths"
minor_paths = ["src/**"]

"""

EVERY_BATCH = """\
[lanes.stable]
quiet_minutes = 30
github_release = true
"""

PROMOTE = """\
[lanes.rc]
schedule = ["daily 07:00 UTC"]
github_release = true

[lanes.stable]
promote_from = "rc"
quiet_minutes = 30
github_release = true
"""


def start(repo: Repo, now: dt.datetime, actor: str | None, lane: Lane | None = Lane.STABLE) -> Decision:
    """Plan a workflow_dispatch run started by actor, as `shipmill plan --actor` does"""
    repo.at(now)
    repo.git.fetch("+refs/heads/main:refs/remotes/origin/main")
    repo.git.run("checkout", "-q", "--detach", "origin/main")
    planner = Planner(repo.git, repo.policy, repo.github, now)
    return planner.plan(Event.MANUAL, lane, actor=Actor(actor) if actor else None)


def use_policy(repo: Repo, text: str, autonomy: str = "") -> None:
    """Commit the policy on main, so a merge's reset keeps it"""
    repo.git.run("checkout", "-q", "main")
    repo.git.run("reset", "-q", "--hard", "origin/main")
    repo.write(repo.policy_file, text + (f'\n[autonomy]\nrelease = "{autonomy}"\n' if autonomy else ""))
    repo.git.run("commit", "-q", "-am", "Policy")
    repo.git.run("push", "-q", "origin", "main")


def retag(repo: Repo, version: str) -> None:
    """Make version the last stable release in place of the fixture's 1.0.0"""
    repo.git.run("tag", "-d", "v1.0.0")
    repo.git.run("push", "-q", "origin", ":refs/tags/v1.0.0")
    repo.git.run("tag", "-a", f"v{version}", "-m", version, "main")
    repo.git.run("push", "-q", "origin", f"v{version}")


def test_s029_1_a_breaking_change_on_main_is_proposed_not_released(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + EVERY_BATCH, autonomy="act")
    retag(repo, "1.4.0")
    repo.merge(1, "Breaking", "Drop the old API")
    head = repo.git.sha()
    decision = plan(repo, at_day(0, 7), event=Event.PUSH)
    assert decision.action == "propose", decision.reason
    assert decision.lane is None and decision.version is None
    assert decision.proposals == (Proposal(Lane.STABLE, Version.parse("2.0.0"), head, BREAKING),)
    assert BREAKING == "a breaking change waits for the maintainer's decision"
    assert decision.reason.startswith(f"stable: 2.0.0 is due, proposed instead of released: {BREAKING}")


def test_s029_1_before_1_0_a_breaking_change_moves_the_minor_and_still_waits(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + EVERY_BATCH)  # no [autonomy]: release acts
    retag(repo, "0.4.2")
    repo.merge(1, "Breaking", "Drop the old API")
    decision = plan(repo, at_day(0, 7), event=Event.SCHEDULE)
    assert decision.action == "propose", decision.reason
    assert [(p.lane, str(p.version), p.cause) for p in decision.proposals] == [(Lane.STABLE, "0.5.0", BREAKING)]


def test_s029_1_a_breaking_fragment_waits_too(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + EVERY_BATCH)
    use_fragments(repo)
    add_fragment(repo, "1-drop.md", "### Breaking\n\n- Drop the old API (#1)\n")
    decision = plan(repo, at_day(0, 7))
    assert [(str(p.version), p.cause) for p in decision.proposals] == [("2.0.0", BREAKING)], decision.reason


def test_s029_1_a_hand_start_releases_the_breaking_change_and_lane_policy_proposes(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + EVERY_BATCH)
    repo.merge(1, "Breaking", "Drop the old API")
    # lane=policy plans as a scheduled run does (D-1)
    assert plan(repo, at_day(0, 7), event=Event.MANUAL).action == "propose"
    started = start(repo, at_day(0, 7), "octocat")
    assert (started.action, started.lane, str(started.version)) == ("release", Lane.STABLE, "2.0.0")
    assert started.reason == "stable 2.0.0: 1 pending entries; breaking, started by @octocat"


def test_s029_1_observe_stays_observe_and_the_hold_names_itself(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + EVERY_BATCH, autonomy="observe")
    repo.merge(1, "Breaking", "Drop the old API")
    observed = plan(repo, at_day(0, 7))
    assert observed.action == "skip"
    assert "stable: 2.0.0 is due (main quiet for 60 min), but release autonomy is observe" in observed.reason
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + EVERY_BATCH, autonomy="propose")
    assert [p.cause for p in plan(repo, at_day(0, 7)).proposals] == [BREAKING]
    # the hold stops the hand start that would release it, so the proposal names the hold (D-8)
    repo.github.holds = ["#7 Incident"]
    assert [p.cause for p in plan(repo, at_day(0, 7)).proposals] == ["held by shipmill-hold #7"]


LEGACY_BREAKING_RC = """\
# Changelog

## [Unreleased]

## [2.0.0rc1] - 2026-10-03

### Breaking

- Drop the old API (#1)

## [1.0.0] - 2026-09-01

### Added

- The first release

[Unreleased]: https://github.com/o/demo/compare/v2.0.0rc1...HEAD
[2.0.0rc1]: https://github.com/o/demo/compare/v1.0.0...v2.0.0rc1
[1.0.0]: https://github.com/o/demo/releases/tag/v1.0.0
"""


def test_s029_1_a_breaking_entry_in_an_rc_section_the_stable_release_folds_waits_too(repo: Repo) -> None:
    # main's head stable release folds the version's rc sections (D-25), so their entries are its own
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + EVERY_BATCH)
    _tag_on_main(repo, LEGACY_BREAKING_RC, "v2.0.0rc1")
    repo.merge(2, "Fixed", "Fix B")
    decision = plan(repo, at_day(0, 7))
    assert [(str(p.version), p.cause) for p in decision.proposals] == [("2.0.0", BREAKING)], decision.reason
    started = start(repo, at_day(0, 7), "octocat")
    assert (started.action, str(started.version)) == ("release", "2.0.0")


def test_s029_2_a_promotion_whose_rc_base_is_breaking_is_proposed(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + PROMOTE)
    repo.merge(1, "Breaking", "Drop the old API")
    rc = plan(repo, at_day(1))
    assert (rc.lane, str(rc.version)) == (Lane.RC, "2.0.0rc1")  # the rc lane isn't held
    release(repo, rc)
    rc_base = repo.git.remote_branch("main")
    decision = plan(repo, at_day(1, 9))
    assert decision.action == "propose", decision.reason
    assert decision.proposals == (Proposal(Lane.STABLE, Version.parse("2.0.0"), str(rc_base), BREAKING),)
    started = start(repo, at_day(1, 9), "octocat")
    assert (started.action, str(started.version), started.base) == ("release", "2.0.0", rc_base)


def test_s029_2_a_breaking_entry_after_the_rc_does_not_hold_its_promotion(repo: Repo) -> None:
    # the promotion's entries are read at the rc's base (D-25): the breaking one goes in the next
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + PROMOTE)
    repo.merge(1, "Added", "Feature A")
    release(repo, plan(repo, at_day(1)))
    repo.at(at_day(1, 8) + dt.timedelta(minutes=10))
    repo.merge(2, "Breaking", "Drop the old API")
    decision = plan(repo, at_day(1, 9))
    assert (decision.action, decision.lane, str(decision.version)) == ("release", Lane.STABLE, "1.1.0")


def test_s029_3_a_candidate_with_no_major_entry_releases_on_its_trigger(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + EVERY_BATCH, autonomy="act")
    repo.merge(1, "Added", "Feature A")
    repo.merge(2, "Fixed", "Fix B")
    decision = plan(repo, at_day(0, 7), event=Event.PUSH)
    assert (decision.action, decision.lane, str(decision.version)) == ("release", Lane.STABLE, "1.1.0")
    assert decision.reason == "stable 1.1.0: 2 pending entries; main quiet for 60 min"


def test_s029_3_bump_from_paths_is_never_breaking(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + PATHS + EVERY_BATCH)
    repo.merge(1, "Breaking", "Drop the old API", "src/app.py", "VALUE = 2\n")
    decision = plan(repo, at_day(0, 7))
    assert (decision.action, decision.lane, str(decision.version)) == ("release", Lane.STABLE, "1.1.0")


def test_s029_10_promote_from_rc_without_a_soak_promotes_an_rc_of_any_age(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + PROMOTE)
    repo.merge(1, "Added", "Feature A")
    release(repo, plan(repo, at_day(1)))
    rc_base = repo.git.remote_branch("main")
    # an hour after the rc, main quiet: stable promotes it
    decision = plan(repo, at_day(1, 9))
    assert (decision.action, decision.lane, str(decision.version), decision.base) == (
        "release",
        Lane.STABLE,
        "1.1.0",
        rc_base,
    )
    assert "promotes v1.1.0rc1" in decision.reason and "main quiet for" in decision.reason


def test_s029_10_a_promotion_still_defers_when_the_ci_workflows_changed(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + PROMOTE)
    repo.merge(1, "Added", "Feature A")
    release(repo, plan(repo, at_day(1)))
    repo.at(at_day(1, 8) + dt.timedelta(minutes=10))
    repo.merge(2, "Fixed", "Faster CI", ".github/workflows/ci.yml", "name: ci\n")
    decision = plan(repo, at_day(1, 9))
    assert decision.lane is not Lane.STABLE
    assert "stable: the CI workflows (.github/workflows/) changed since v1.1.0rc1" in decision.reason


# -- the proposal beside a pre-release, its issue, and the hand start (#462) --------------------

RC_AND_STABLE = """\
[lanes.rc]
schedule = ["daily 07:00 UTC"]
github_release = true

[lanes.stable]
quiet_minutes = 30
github_release = true
"""


def test_s029_4_an_rc_release_proposes_the_breaking_stable_candidate_in_the_same_run(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + RC_AND_STABLE)
    repo.merge(1, "Breaking", "Drop the old API")
    head = repo.git.sha()
    decision = plan(repo, at_day(0, 8))
    assert (decision.action, decision.lane, str(decision.version)) == ("release", Lane.RC, "2.0.0rc1")
    assert decision.proposals == (Proposal(Lane.STABLE, Version.parse("2.0.0"), head, BREAKING),)
    assert f"stable: 2.0.0 is due, proposed instead of released: {BREAKING}" in decision.reason
    assert decision.reason.startswith("rc 2.0.0rc1: 1 pending entries; window 'daily 07:00 UTC' opened")
    assert json.loads(decision.outputs()["proposals"]) == [p.as_dict() for p in decision.proposals]
    [first] = propose(repo.git, repo.policy, repo.github, decision.proposals)
    assert first.outcome is Outcome.OPENED
    release(repo, decision)
    # the next day's rc moves the proposal along with main, in place
    repo.at(at_day(1, 6))
    repo.merge(2, "Fixed", "Fix B")
    later = plan(repo, at_day(1, 8))
    assert (later.action, str(later.version)) == ("release", "2.0.0rc2")
    [again] = propose(repo.git, repo.policy, repo.github, later.proposals)
    assert (again.issue, again.outcome) == (first.issue, Outcome.UPDATED)
    assert "- Fix B (#2)" in repo.github.issues[first.issue].body and len(repo.github.issues) == 1


def test_s029_4_a_release_carries_no_proposal_when_stable_is_not_breaking(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + RC_AND_STABLE)
    repo.merge(1, "Added", "Feature A")
    decision = plan(repo, at_day(0, 8))
    assert (decision.action, decision.lane) == ("release", Lane.STABLE)
    assert decision.proposals == () and decision.outputs()["proposals"] == ""


def test_s029_5_the_breaking_proposal_issue_lists_the_breaking_entries_first(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + EVERY_BATCH)
    repo.merge(1, "Breaking", "Drop the old API")
    repo.merge(2, "Added", "Feature A")  # merge writes it above the Breaking section
    [done] = propose(repo.git, repo.policy, repo.github, plan(repo, at_day(0, 7)).proposals)
    issue = repo.github.issues[done.issue]
    assert issue.title == "Ready to release v2.0.0 on stable"
    assert repo.github.labels[done.issue] == (PROPOSAL_LABEL,)
    assert f"but {BREAKING}." in issue.body
    assert "it waits for the maintainer's decision" in issue.body
    assert issue.body.index("#### Breaking\n\n- Drop the old API (#1)") < issue.body.index("#### Added\n\n- Feature A")
    assert "gh workflow run release.yml -f lane=stable -f dry-run=false" in issue.body
    assert "start the lane by hand as a person" in issue.body


def test_s029_6_a_person_releases_the_breaking_candidate_a_bot_does_not(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + EVERY_BATCH)
    repo.merge(1, "Breaking", "Drop the old API")
    person = start(repo, at_day(0, 7), "octocat")
    assert (person.action, person.lane, str(person.version)) == ("release", Lane.STABLE, "2.0.0")
    assert person.reason.endswith("; breaking, started by @octocat")
    bot = start(repo, at_day(0, 7), "shipmill[bot]")
    assert (bot.action, bot.lane) == ("skip", None)
    assert bot.reason == "stable: 2.0.0 waits, a breaking release is started by a person, not shipmill[bot]"
    # lane=policy plans as a scheduled run does (D-1), whoever starts it
    assert start(repo, at_day(0, 7), "octocat", lane=None).action == "propose"
    # a run that names nobody is not a person's decision
    unnamed = start(repo, at_day(0, 7), None)
    assert unnamed.action == "skip" and "a breaking release is started by a person" in unnamed.reason


def test_s029_6_the_hold_still_stops_a_persons_hand_start(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + EVERY_BATCH)
    repo.merge(1, "Breaking", "Drop the old API")
    repo.github.holds = ["#7 Incident"]
    held = start(repo, at_day(0, 7), "octocat")
    assert held.action == "skip"
    assert held.reason.startswith("stable: 2.0.0 held by shipmill-hold #7; close it to release by hand")


def test_s029_6_a_bot_still_starts_a_non_breaking_stable_release(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + EVERY_BATCH)
    repo.merge(1, "Added", "Feature A")
    for actor in ("shipmill[bot]", None):
        started = start(repo, at_day(0, 7), actor)
        assert (started.action, str(started.version)) == ("release", "1.1.0")
        assert started.reason == "stable 1.1.0: 1 pending entries; started by hand"


def test_s029_6_the_cli_takes_the_actor_and_refuses_a_malformed_login(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + EVERY_BATCH)
    repo.merge(1, "Breaking", "Drop the old API")
    start(repo, at_day(0, 7), None)  # checks out main's head, as the workflow does
    now = at_day(0, 7).isoformat()
    argv = ["--repo", str(repo.root), "plan", "--event", "workflow_dispatch", "--lane", "stable", "--now", now]
    assert main([*argv, "--actor", "octocat"], repo.github) == 0
    outputs = json.loads(capsys.readouterr().out)
    assert (outputs["action"], outputs["version"]) == ("release", "2.0.0")
    assert outputs["reason"].endswith("; breaking, started by @octocat")
    assert main([*argv, "--actor", "dependabot[bot]"], repo.github) == 0
    assert json.loads(capsys.readouterr().out)["reason"].endswith("not dependabot[bot]")
    for bad in ("octo cat", "-octocat", "octocat[app]", "a" * 40):
        with pytest.raises(ReleaseError, match="--actor is a GitHub login"):
            Actor(bad)
    with pytest.raises(ReleaseError, match="--actor is a GitHub login"):
        main([*argv, "--actor", "octo;cat"], repo.github)


def test_s029_6_an_enterprise_managed_users_login_plans_a_push_and_starts_stable(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    # the workflow passes every run's actor, so a login it refused would fail every release
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + EVERY_BATCH)
    repo.merge(1, "Breaking", "Drop the old API")
    start(repo, at_day(0, 7), None)
    now = at_day(0, 7).isoformat()
    argv = ["--repo", str(repo.root), "plan", "--now", now, "--actor", "octocat_acme"]
    assert main([*argv, "--event", "push"], repo.github) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "propose"
    assert main([*argv, "--event", "workflow_dispatch", "--lane", "stable"], repo.github) == 0
    assert json.loads(capsys.readouterr().out)["reason"].endswith("; breaking, started by @octocat_acme")


def test_s029_6_land_closes_the_breaking_proposal_under_act(repo: Repo) -> None:
    repo.at(at_day(0, 6))
    use_policy(repo, HEAD + HEADINGS + EVERY_BATCH)
    repo.merge(1, "Breaking", "Drop the old API")
    [done] = propose(repo.git, repo.policy, repo.github, plan(repo, at_day(0, 7)).proposals)
    release(repo, start(repo, at_day(0, 7), "octocat"))
    closed = close_released(repo.policy, repo.github, Lane.STABLE, Version.parse("2.0.0"), None)
    assert closed == f"closed proposal #{done.issue}: v2.0.0 released"
    assert done.issue in repo.github.closed
