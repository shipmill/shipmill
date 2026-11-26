"""triage_state.py holds a held project's issues (spec 106, S-106-16): the head and each open
sub-issue under it read BLOCKED `project #<head> held`; without gh or the network"""

import json
from pathlib import Path
from types import ModuleType
from typing import Any

from .test_triage_state import REPO, forward, open_issue, run_script, ts

__all__ = ["ts"]  # the module fixture

CHECK = "## Check\n\nRun the release and see the page.\n"


def sub_node(
    number: int, state: str = "OPEN", title: str = "Part", body: str = "", repo: str = "o/r"
) -> dict[str, Any]:
    """A sub-issue as the native field reads it, with the title and body that tell a check issue"""
    return {
        "number": number,
        "state": state,
        "stateReason": None,
        "closedAt": None,
        "repository": {"nameWithOwner": repo},
        "title": title,
        "body": body,
    }


def check_node(number: int = 50) -> dict[str, Any]:
    return sub_node(number, title="Check: the page shows the plan", body=CHECK)


def with_subs(item: dict[str, Any], *subs: dict[str, Any]) -> dict[str, Any]:
    item["subIssues"] = forward(list(subs))
    item["blockedBy"] = forward([])
    return item


def held_map(ts: ModuleType, *issues: dict[str, Any]) -> dict[int, str]:
    found: dict[int, str] = ts.held_projects(list(issues), REPO)
    return found


def test_s106_16_a_head_with_no_check_issue_and_its_open_sub_issues_read_blocked(ts: ModuleType) -> None:
    head = with_subs(open_issue(7, labels=("project",)), sub_node(8), sub_node(9, "CLOSED"), sub_node(3, repo="o/x"))
    assert held_map(ts, head) == {7: "project #7 held", 8: "project #7 held"}  # closed or another repo's: not held
    assert ts.classify_open(head, "Triage:", "postponed", {}, None, REPO, project="project #7 held") == (
        "BLOCKED",
        "project #7 held",
    )


def test_s106_16_a_head_labelled_held_holds_the_check_issues_parts_too(ts: ModuleType) -> None:
    head = with_subs(open_issue(7, labels=("project", "held")), check_node(), sub_node(8))
    check = with_subs(open_issue(50), sub_node(60), sub_node(61, "CLOSED"))
    part = with_subs(open_issue(60))
    assert held_map(ts, head, check, part) == {n: "project #7 held" for n in (7, 50, 8, 60)}


def test_s106_16_a_head_in_any_other_state_reads_as_any_parent(ts: ModuleType) -> None:
    head = with_subs(open_issue(7, labels=("project",)), check_node(), sub_node(8))
    check = with_subs(open_issue(50), sub_node(60))
    assert held_map(ts, head, check) == {}
    # a `Check: ` title without a ## Check section is no check issue: the head is held
    titled = with_subs(open_issue(7, labels=("project",)), sub_node(50, title="Check: it works"))
    assert held_map(ts, titled) == {7: "project #7 held", 50: "project #7 held"}
    # no project label, or a forge that read no sub-issues: no hold
    assert held_map(ts, with_subs(open_issue(7, labels=("held",)), sub_node(8))) == {}
    assert held_map(ts, open_issue(7, labels=("project",))) == {}


def test_s106_16_the_run_reads_the_held_projects_issues_blocked(tmp_path: Path) -> None:
    head = with_subs(open_issue(7, labels=("project",)), sub_node(8))
    part = with_subs(open_issue(8))
    other = with_subs(open_issue(9))
    run = run_script(tmp_path, [head, part, other])
    rows = {r["number"]: r for r in map(json.loads, run.stdout.splitlines()) if "number" in r}
    assert (rows[7]["state"], rows[7]["note"]) == ("BLOCKED", "project #7 held"), run.stderr
    assert (rows[8]["state"], rows[8]["note"]) == ("BLOCKED", "project #7 held")
    assert rows[9]["state"] != "BLOCKED"


def test_s106_16_the_query_reads_sub_issues_titles_and_bodies_at_no_more_cost(ts: ModuleType) -> None:
    assert "subIssues(first: 50) { pageInfo { hasNextPage endCursor } nodes { number title body state" in ts.QUERY
    assert "blockedBy(first: 50) { pageInfo { hasNextPage endCursor } nodes { number state" in ts.QUERY
    assert "nodes { number title body" in ts.NATIVE_PAGES["subIssues"]
