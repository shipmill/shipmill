"""intake_state.py --goals (spec 106, #1737): a goal's state from the direction, its plans, and
its projects, GOAL_OVERDUE past its horizon, and the goal proposals; without the network"""

from collections.abc import Sequence
from types import ModuleType
from typing import Any

import pytest

from .test_intake_plans import ist
from .test_intake_projects import BOT, check, head, sub, who

__all__ = ["ist"]  # the module fixture


def goal(ist: ModuleType, ident: str, by: str | None = "2026-12-31", past: bool | None = False, **kw: Any) -> Any:
    return ist.Goal(ident, f"Goal {ident}. Check: c. By: {by}", kw.get("kind", "goal"), kw.get("state"), by, past)


def plan(ist: ModuleType, ident: str, number: int, state: str) -> Any:
    return ist.PlanRow(ident, state, f"Plan for {ident}", "", number, "plan", BOT, "NONE")


def proposal(number: int, association: str = "OWNER", author: str = "maintainer") -> dict[str, Any]:
    return {
        "number": number,
        "title": f"Goal proposal {number}",
        "author": who(author),
        "authorAssociation": association,
        "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": "goal-proposal"}]},
    }


def rows(
    ist: ModuleType, goals: list[Any], plans: Sequence[Any] = (), heads: Sequence[Any] = (), **kw: Any
) -> dict[Any, Any]:
    found = ist.goal_rows(
        goals, list(plans), list(heads), kw.get("issues", []), BOT, kw.get("tagged", set()), kw.get("reviews", set())
    )
    return {(r.goal or r.number): (r.state, r.holder, r.note) for r in found}


# -- S-106-4 --------------------------------------------------------------------------------


def test_s106_4_each_goal_of_kind_goal_reads_its_state(ist: ModuleType) -> None:
    goals = [
        goal(ist, "G-1"),
        goal(ist, "G-2"),
        goal(ist, "G-3"),
        goal(ist, "G-4", state="met"),
        goal(ist, "G-5", state="dropped"),
        goal(ist, "G-6"),
    ]
    plans = [plan(ist, "G-2", 20, "PLAN_FILED"), plan(ist, "G-3", 21, "PLAN_OPEN"), plan(ist, "G-6", 22, "PLAN_DONE")]
    head_row = ist.project_row(head(30, (check(), sub(31))), BOT)
    found = rows(ist, goals, plans, [ist.replace(head_row, parent=22)])
    assert found == {
        "G-1": ("GOAL_WRITTEN", "agent", "a plan is due"),
        "G-2": ("GOAL_PLANNED", "projects", "plan #20 accepted"),
        "G-3": ("GOAL_WRITTEN", "maintainer", "plan #21 waits on your answer"),
        "G-4": ("GOAL_MET", None, "met"),
        "G-5": ("GOAL_DROPPED", None, "dropped"),
        "G-6": ("GOAL_PLANNED", "projects", "project #30 open"),  # its plan is done, its project isn't
    }
    accepted = rows(ist, [goal(ist, "G-2")], [plan(ist, "G-2", 20, "PLAN_ACCEPTED")])
    assert accepted["G-2"][0] == "GOAL_PLANNED"


def test_s106_4_a_measure_and_a_goal_of_no_kind_read_no_row(ist: ModuleType) -> None:
    goals = [goal(ist, "G-1", kind="measure", by=None, past=None), goal(ist, "G-2", kind=None, by=None, past=None)]
    assert rows(ist, goals) == {}


def test_s106_4_a_trusted_goal_proposal_reads_proposed(ist: ModuleType) -> None:
    issues = [proposal(40), proposal(41, "NONE", "drive-by"), proposal(42, "NONE", BOT)]
    found = rows(ist, [], issues=issues)
    assert found == {
        40: ("GOAL_PROPOSED", "maintainer", "waits on your answer"),
        42: ("GOAL_PROPOSED", "maintainer", "waits on your answer"),
    }


def test_s106_4_json_carries_state_holder_and_by(ist: ModuleType) -> None:
    (row,) = ist.goal_rows([goal(ist, "G-1")], [], [], [], BOT, set(), set())
    assert ist.goal_json(row) == {
        "kind": "goal-state",
        "goal": "G-1",
        "number": None,
        "state": "GOAL_WRITTEN",
        "title": "Goal G-1. Check: c. By: 2026-12-31",
        "note": "a plan is due",
        "holder": "agent",
        "by": "2026-12-31",
    }


def test_s106_4_the_goals_horizon_is_read_strictly(ist: ModuleType) -> None:
    text = (
        '{"goals": [{"id": "G-1", "text": "x", "kind": "goal", "state": null, "by": {"date": "2026-12-31"}, '
        '"past": true}, {"id": "G-2", "text": "y", "kind": "goal", "by": {"release": "0.7.0"}, "past": null}]}'
    )
    assert ist.parse_goals(text) == [
        ist.Goal("G-1", "x", "goal", None, "2026-12-31", True),
        ist.Goal("G-2", "y", "goal", None, "0.7.0", None),
    ]
    for bad in ('"by": "2026-12-31"', '"by": {"date": 1}', '"by": {"day": "x"}', '"past": "yes"'):
        with pytest.raises(SystemExit):
            ist.parse_goals('{"goals": [{"id": "G-1", "text": "x", ' + bad + "}]}")


# -- S-106-5 --------------------------------------------------------------------------------


def test_s106_5_a_goal_past_its_horizon_reads_overdue_until_the_bots_review(ist: ModuleType) -> None:
    goals = [goal(ist, "G-1", past=True), goal(ist, "G-2", by="0.7.0", past=None), goal(ist, "G-3", past=False)]
    found = rows(ist, goals, tagged={"0.7.0"})
    assert found["G-1"] == ("GOAL_OVERDUE", "agent", "past 2026-12-31; a plan is due")
    assert found["G-2"] == ("GOAL_OVERDUE", "agent", "release 0.7.0 tagged; a plan is due")
    assert found["G-3"][0] == "GOAL_WRITTEN"
    assert "GOAL_OVERDUE" in ist.GOAL_ACTION
    reviewed = rows(ist, goals, tagged={"0.7.0"}, reviews={("G-1", "2026-12-31"), ("G-2", "0.7.0")})
    assert reviewed["G-1"][0] == reviewed["G-2"][0] == "GOAL_WRITTEN"
    # a new horizon makes a new question due: the review named the old one
    moved = rows(ist, [goal(ist, "G-1", by="2027-01-31", past=True)], reviews={("G-1", "2026-12-31")})
    assert moved["G-1"][0] == "GOAL_OVERDUE"
    # a planned goal is overdue too; a met one never
    planned = rows(ist, [goal(ist, "G-1", past=True)], [plan(ist, "G-1", 20, "PLAN_FILED")])
    assert planned["G-1"] == ("GOAL_OVERDUE", "agent", "past 2026-12-31; plan #20 accepted")
    assert rows(ist, [goal(ist, "G-1", past=True, state="met")])["G-1"][0] == "GOAL_MET"


def run_with(responses: dict[str, dict[str, Any]], seen: list[str]) -> Any:
    def run(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        seen.append(query)
        key = "reviews" if "goal-review" in query else "tags"
        return {"data": {"repository": responses[key]}}

    return run


def test_s106_5_only_the_bots_marker_counts_as_the_review(ist: ModuleType) -> None:
    marker = "<!-- shipmill:goal-overdue G-1 by=2026-12-31 -->\nThe goal is past its horizon."
    nodes = [
        {"number": 1, "body": marker, "author": who(BOT)},
        {"number": 2, "body": marker.replace("G-1", "G-2"), "author": who("someone")},
        {"number": 3, "body": "no marker\n" + marker, "author": who(BOT)},
    ]
    seen: list[str] = []
    found = ist.reviewed("o/r", BOT, run_with({"reviews": {"issues": {"totalCount": 3, "nodes": nodes}}}, seen))
    assert found == {("G-1", "2026-12-31")}
    assert ist.reviewed("o/r", None, run_with({"reviews": {"issues": {"totalCount": 3, "nodes": nodes}}}, [])) == set()


def test_s106_5_a_release_horizon_is_past_once_its_version_is_tagged(ist: ModuleType) -> None:
    seen: list[str] = []
    tags = {"t0a": None, "t0b": {"name": "v0.7.0"}, "t1a": None, "t1b": None}
    assert ist.release_tagged("o/r", ["0.7.0", "v0.8.0"], run_with({"tags": tags}, seen)) == {"0.7.0"}
    assert 'qualifiedName: "refs/tags/v0.7.0"' in seen[0] and 'qualifiedName: "refs/tags/0.8.0"' in seen[0]
    assert ist.release_tagged("o/r", [], run_with({}, seen)) == set() and len(seen) == 1  # nothing read
