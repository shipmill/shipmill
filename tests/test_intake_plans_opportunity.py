"""An accepted opportunity names its goal, and one open plan per goal (spec 106, #1742):
ACCEPTED_INTO, GOAL_PROPOSAL_DUE, NEEDS_GOAL, PLAN_DUE for a request or an accepted opportunity
with or without an open plan, PLAN_REPLACED, and an opportunity filed as its own head"""

import datetime as dt
from collections.abc import Sequence
from types import ModuleType
from typing import Any

from .test_intake_plans import (
    BOT,
    GOALS,
    PLANS_NOW,
    Fake,
    carrier,
    comment,
    full_plan,
    issue,
    ist,
    open_plan,
    owner,
    plan_states,
)

__all__ = ["ist"]  # the module fixture

AFTER = dt.datetime(2026, 11, 28, tzinfo=dt.UTC)  # accepted after spec 106's build
BEFORE = dt.datetime(2026, 11, 20, tzinfo=dt.UTC)


def opp(number: int, *replies: str, serves: str = "") -> dict[str, Any]:
    """An opportunity labelled accepted, with the maintainer's replies"""
    body = f"## Problem\n\nSlow.\n\n{serves}\n" if serves else "## Problem\n\nSlow.\n"
    return issue(
        number, *[owner(r, 10 + i) for i, r in enumerate(replies)], body=body, labels=("opportunity", "planned")
    )


def classify(
    ist: ModuleType, issues: list[dict[str, Any]], reads: dict[int, Any], open_issues: Sequence[dict[str, Any]] = ()
) -> dict[int, tuple[str, str]]:
    goals = [
        ist.Goal("G-1", "a. Check: c. By: 2026-12-31", "goal"),
        ist.Goal("G-2", "Held: x. Threshold: t. Source: s", "measure"),
        ist.Goal("G-3", "b. Check: c. By: 2026-12-31. Met: 2026-11-01", "goal", "met"),
        ist.Goal("G-4", "People hear"),
    ]
    items = [ist.Item(int(i["number"]), "opportunity", "t", 0, state="ACCEPTED") for i in issues]
    intake = ist.Intake("propose", [], [], {}, open_issues=list(open_issues), opportunity_issues=issues)
    found = ist.opportunity_goals(items, intake, goals, reads, "Triage:", BOT, frozenset())
    return {i.number: (i.state, i.note) for i in found}


# -- S-106-22, S-106-24 ---------------------------------------------------------------------


def test_s106_22_an_accepted_opportunity_reads_into_its_goal(ist: ModuleType) -> None:
    issues = [opp(40, "accept G-1"), opp(41, serves="Serves: G-1"), opp(42, "Accept g-1.")]
    reads = {n: ist.Accepted(AFTER, None) for n in (40, 41, 42)}
    assert classify(ist, issues, reads) == {
        40: ("ACCEPTED_INTO", "G-1"),
        41: ("ACCEPTED_INTO", "G-1"),
        42: ("ACCEPTED_INTO", "G-1"),
    }


def test_s106_24_a_new_goal_waits_on_its_proposal_and_no_goal_needs_one(ist: ModuleType) -> None:
    proposal = issue(60, labels=("goal-proposal",), author="shipmill-app", bot=True)
    issues = [opp(50, "accept new goal"), opp(51, "accept new goal"), opp(52), opp(53, "accept G-2")]
    issues += [opp(54, "accept G-3"), opp(55, "accept G-4"), opp(56, "accept G-9"), opp(57, serves="Serves: G-1, G-4")]
    reads = {int(i["number"]): ist.Accepted(AFTER, None) for i in issues} | {51: ist.Accepted(AFTER, 60)}
    found = classify(ist, issues, reads, [proposal])
    assert found[50] == ("GOAL_PROPOSAL_DUE", "open its goal proposal")
    assert found[51] == ("GOAL_PROPOSED", "goal proposal #60 waits on your answer")
    assert found[52][0] == found[57][0] == "NEEDS_GOAL" and found[52][1].startswith("names no goal")
    for number, goal in ((53, "G-2"), (54, "G-3"), (55, "G-4"), (56, "G-9")):  # measure, met, no kind, unlisted
        assert found[number] == (
            "NEEDS_GOAL",
            f"{goal} is no goal still open: answer `accept G-<n>` or `accept new goal`",
        )
    assert "GOAL_PROPOSAL_DUE" in ist.ACTION and "NEEDS_GOAL" not in ist.ACTION


def test_s106_24_an_opportunity_accepted_before_the_build_reads_as_before(ist: ModuleType) -> None:
    issues = [opp(40, "accept G-1"), opp(41)]
    reads = {40: ist.Accepted(BEFORE, None), 41: ist.Accepted(None, None)}
    assert classify(ist, issues, reads) == {40: ("ACCEPTED", ""), 41: ("ACCEPTED", "")}


def test_s106_22_only_a_trusted_accept_names_the_goal(ist: ModuleType) -> None:
    stranger = issue(40, comment("accept G-1", 10, association="NONE", author="x"), labels=("opportunity", "planned"))
    assert classify(ist, [stranger], {40: ist.Accepted(AFTER, None)})[40][0] == "NEEDS_GOAL"


def test_s106_22_accepted_reads_the_label_time_and_parent(ist: ModuleType) -> None:
    nodes = [
        {
            "number": 40,
            "parent": {"number": 60},
            "timelineItems": {
                "nodes": [
                    {"createdAt": "2026-11-20T10:00:00Z", "label": {"name": "planned"}},
                    {"createdAt": "2026-11-28T10:00:00Z", "label": {"name": "planned"}},
                    {"createdAt": "2026-11-29T10:00:00Z", "label": {"name": "other"}},
                ]
            },
        }
    ]

    def run(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        assert "states: OPEN" in query and variables["label"] == "planned"
        return {"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": False}, "nodes": nodes}}}}

    assert ist.accepted_reads("o/r", "planned", run) == {
        40: ist.Accepted(dt.datetime(2026, 11, 28, 10, tzinfo=dt.UTC), 60)
    }


# -- S-106-10 -------------------------------------------------------------------------------


def goal_rows(ist: ModuleType, fake: Fake, into: dict[str, Any] | None = None) -> dict[str, tuple[str, str]]:
    intake = ist.fetch(
        "o/r",
        label="opportunity",
        accepted="planned",
        marker="Triage:",
        skip=set(ist.SKIP_LABELS),
        categories=None,
        autonomy="propose",
        run=fake,
    )
    found = ist.fetch_plans(
        "o/r",
        intake,
        now=PLANS_NOW,
        goals=lambda: [ist.Goal(i, t) for i, t in GOALS],
        marker="Triage:",
        bot_login=BOT,
        wip=None,
        room=lambda limit: 1,
        run=fake,
        filing=lambda issue, plan: ("PLAN_FILED", ""),
        into=into,
    )
    return {r.goal: (r.state, r.note) for r in found if r.kind == "goal"}


def opened(plan: dict[str, Any], at: str) -> dict[str, Any]:
    return {**plan, "createdAt": at}


def test_s106_10_a_request_or_an_accepted_opportunity_reads_due_with_an_open_plan(ist: ModuleType) -> None:
    plan = opened(open_plan(20), "2026-10-01T09:00:00Z")
    request = opened(issue(25, title="Plan G-1", labels=("goal-plan",), association="OWNER"), "2026-10-02T09:00:00Z")
    assert goal_rows(ist, Fake([request], plans=[plan]))["G-1"] == ("PLAN_DUE", "requested in #25")
    older = opened(request, "2026-09-30T09:00:00Z")  # a plan opened since the request answers it
    assert "G-1" not in goal_rows(ist, Fake([older], plans=[plan]))
    into = {"G-1": (40, dt.datetime(2026, 10, 2, tzinfo=dt.UTC))}
    assert goal_rows(ist, Fake(plans=[plan]), into)["G-1"] == ("PLAN_DUE", "opportunity #40 accepted")
    stale = {"G-1": (40, dt.datetime(2026, 9, 30, tzinfo=dt.UTC))}  # the open plan came after the accept
    assert "G-1" not in goal_rows(ist, Fake(plans=[plan]), stale)
    assert goal_rows(ist, Fake(), into)["G-1"] == ("PLAN_DUE", "opportunity #40 accepted")  # with no plan too


def test_s106_10_the_older_open_plan_reads_replaced_by_the_newer(ist: ModuleType) -> None:
    old, new = opened(open_plan(20), "2026-10-01T09:00:00Z"), opened(open_plan(21), "2026-10-02T09:00:00Z")
    found = plan_states(ist, Fake(plans=[new, old]))
    assert found[20] == ("PLAN_REPLACED", "by #21") and found[21][0] == "PLAN_OPEN"
    assert "PLAN_REPLACED" in ist.PLAN_ACTION


def test_s106_10_a_replaced_plan_is_no_decline(ist: ModuleType) -> None:
    marker = comment("<!-- shipmill:plan-replaced #21 -->\nReplaced by #21.", 12, author="shipmill-app", bot=True)
    replaced = open_plan(20, marker, state="CLOSED", reason="NOT_PLANNED")
    assert 20 not in plan_states(ist, Fake(plans=[replaced]))  # neither declined nor answered
    assert goal_rows(ist, Fake(plans=[replaced]))["G-1"] == ("PLAN_DUE", "no-work")  # its no-work trigger reads on
    by_anyone = comment("<!-- shipmill:plan-replaced #21 -->", 12, association="OWNER", author="maintainer")
    declined = open_plan(20, by_anyone, state="CLOSED", reason="NOT_PLANNED")
    assert plan_states(ist, Fake(plans=[declined]))[20][0] == "PLAN_DECLINED"


# -- S-106-23 -------------------------------------------------------------------------------


def test_s106_23_a_plan_item_naming_an_accepted_opportunity_files_no_issue(ist: ModuleType) -> None:
    body = full_plan().replace("- W-2 feature: A release cut", "- W-2 feature: #401 the opportunity's outcome")
    accepted = open_plan(20, owner("accept", 10), body=body)
    carriers = [carrier(302, "W-3")]
    unlabelled = {401: {"opportunity", "planned"}}
    fake = Fake(plans=[accepted], carriers=carriers, parents={401: ("o/r", 20)})
    states = plan_states(ist, fake, filing=ist.gh_filing("o/r", BOT, fake, unlabelled))
    assert states[20] == ("PLAN_ACCEPTED", "not labelled project: #401")  # not `not filed: W-2`
    labelled = {401: {"opportunity", "planned", "project"}}
    fake = Fake(plans=[accepted], carriers=carriers, parents={401: ("o/r", 20)})
    assert plan_states(ist, fake, filing=ist.gh_filing("o/r", BOT, fake, labelled))[20] == ("PLAN_FILED", "filed: #302")
    unlinked = Fake(plans=[accepted], carriers=carriers, parents={401: None})
    note = plan_states(ist, unlinked, filing=ist.gh_filing("o/r", BOT, unlinked, labelled))[20][1]
    assert "not linked: #401" in note
    # a feature item naming any other issue is filed as before
    plain = Fake(plans=[accepted], carriers=carriers, parents={401: ("o/r", 20)})
    assert plan_states(ist, plain, filing=ist.gh_filing("o/r", BOT, plain, {}))[20] == (
        "PLAN_ACCEPTED",
        "not filed: W-2",
    )


def test_s106_22_a_plan_since_the_accept_answers_it_open_or_closed(ist: ModuleType) -> None:
    """the goal's plan opened after the accept takes the opportunity; declined, it isn't proposed again"""
    into = {"G-1": (40, dt.datetime(2026, 10, 2, tzinfo=dt.UTC))}
    declined = opened(open_plan(20, state="CLOSED", reason="NOT_PLANNED"), "2026-10-03T09:00:00Z")
    assert "G-1" not in goal_rows(ist, Fake(plans=[declined]), into)


def test_s106_23_a_closed_opportunity_still_carries_its_item(ist: ModuleType) -> None:
    body = full_plan().replace("- W-2 feature: A release cut", "- W-2 feature: #401 the opportunity's outcome")
    accepted = open_plan(20, owner("accept", 10), body=body)
    closed = {401: ("CLOSED", "COMPLETED")}
    fake = Fake(plans=[accepted], carriers=[carrier(302, "W-3")], parents={401: ("o/r", 20)}, states=closed)
    done = plan_states(ist, fake, filing=ist.gh_filing("o/r", BOT, fake, {401: {"opportunity", "project"}}))[20]
    assert done[0] in ("PLAN_FILED", "PLAN_DONE") and "not filed" not in done[1]


def test_s106_24_a_goal_naming_opportunity_line_carries_its_opener(ist: ModuleType) -> None:
    """D-16: the watch trusts an accepted opportunity by its opener before a session starts
    for it, so each state that names a goal prints author and association, as ACCEPTED does"""
    for state in ("ACCEPTED_INTO", "GOAL_PROPOSAL_DUE", "GOAL_PROPOSED", "NEEDS_GOAL"):
        item = ist.Item(12, "opportunity", "t", 0, state=state, author="drive-by", association="NONE")
        line = ist.json_row(item)
        assert (line["author"], line["association"], line["handed"]) == ("drive-by", "NONE", None), state
