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


def test_s106_16_a_persons_item_whose_parent_closed_reads_stale_handoff_first(ts: ModuleType) -> None:
    item = with_subs(open_issue(8, labels=("human",)))
    item["assignees"] = {"nodes": [{"login": "amy"}]}
    item["parent"] = {"number": 7, "state": "CLOSED", "closedAt": None, "repository": {"nameWithOwner": "o/r"}}
    found = ts.classify_open(item, "Triage:", "postponed", {}, None, REPO, project="project #7 held")
    assert found == ("STALE_HANDOFF", "parent o/r#7 closed")


IMPLEMENT = "Triage: **implement**. Build it."


def part_of(pr: int, state: str, merged_at: str | None = None) -> dict[str, Any]:
    """A same-repo PR linked to head #7 by `Part of #7`"""
    return {
        "willCloseTarget": False,
        "isCrossRepository": False,
        "source": {"number": pr, "state": state, "title": "Build it", "body": "Part of #7", "mergedAt": merged_at},
    }


def started_pair(*prs: dict[str, Any], comments: tuple[str, ...] = (IMPLEMENT,)) -> list[dict[str, Any]]:
    """#1802: the eight live projects' shape, a head with no parts and its open check issue"""
    head = with_subs(
        open_issue(
            7, [{"body": c, "createdAt": "2026-11-27T07:00:00Z"} for c in comments], ("project",), forward(list(prs))
        ),
        check_node(),
    )
    check = with_subs(open_issue(50))
    check["title"], check["body"] = "Check: the page shows the plan", CHECK
    return [head, check]


def read(ts: ModuleType, issues: list[dict[str, Any]]) -> dict[int, tuple[str, str]]:
    started = ts.started_projects(issues, REPO)
    return {
        int(i["number"]): ts.classify_open(i, "Triage:", "postponed", {}, None, REPO, started=started.get(i["number"]))
        for i in issues
    }


def test_s106_29_a_head_with_no_parts_is_built_like_any_issue_not_held_on_its_check(ts: ModuleType) -> None:
    found = read(ts, started_pair())
    assert found[7] == ("NEEDS_PR", "")  # not `children 0/1 closed`
    assert found[50] == ("BLOCKED", "project #7: check waits on its work (no part filed, 0 PR merged)")
    untriaged = read(ts, started_pair(comments=()))
    assert untriaged[7][0] == "NEW"
    assert untriaged[50][0] == "BLOCKED"  # never NEW: the check issue is no work to triage


def test_s106_29_the_check_is_due_once_the_heads_part_of_prs_merged(ts: ModuleType) -> None:
    building = read(ts, started_pair(part_of(80, "OPEN")))
    assert building[7] == ("IN_PROGRESS", "#80:open(part)")
    assert building[50][0] == "BLOCKED"
    merged = read(ts, started_pair(part_of(80, "MERGED", "2026-11-28T10:00:00Z")))
    assert merged[7] == ("BLOCKED", "project #7: check #50 due (no part filed, 1 PR merged)")
    assert merged[50] == ("VERIFY_DUE", "project #7: run its ## Check")
    # another PR of the head still open: the work isn't done
    more = read(ts, started_pair(part_of(80, "MERGED", "2026-11-28T10:00:00Z"), part_of(81, "OPEN")))
    assert more[50] == ("BLOCKED", "project #7: check waits on its work (no part filed, a PR open)")


def test_s106_29_a_head_with_parts_waits_on_them_and_then_on_its_check(ts: ModuleType) -> None:
    head, check = started_pair()
    head["subIssues"]["nodes"].append(sub_node(8))
    part = with_subs(open_issue(8))
    found = read(ts, [head, check, part])
    assert found[7][0] == "BLOCKED" and found[7][1].startswith("children 0/1 closed"), found[7]
    assert found[50] == ("BLOCKED", "project #7: check waits on its work (1 of 1 parts open)")
    head["subIssues"]["nodes"][-1] = {**sub_node(8, "CLOSED"), "closedAt": "2026-11-28T10:00:00Z"}
    done = read(ts, [head, check])
    assert done[7] == ("BLOCKED", "project #7: check #50 due (0 of 1 parts open)")
    assert done[50] == ("VERIFY_DUE", "project #7: run its ## Check")


def test_s106_29_a_due_check_still_waits_on_its_own_holds(ts: ModuleType) -> None:
    head, check = started_pair(part_of(80, "MERGED", "2026-11-28T10:00:00Z"))
    check["body"] = CHECK + "\nDepends on #1802\n"
    started = ts.started_projects([head, check], REPO)
    found = ts.classify_open(check, "Triage:", "postponed", {(*REPO, 1802): "OPEN"}, None, REPO, started=started[50])
    assert found == ("BLOCKED", "o/r#1802:open project #7")


def test_s106_29_the_run_reads_a_started_project(tmp_path: Path) -> None:
    run = run_script(tmp_path, started_pair())
    rows = {r["number"]: r for r in map(json.loads, run.stdout.splitlines()) if "number" in r}
    assert rows[7]["state"] == "NEEDS_PR", run.stderr
    assert rows[50]["state"] == "BLOCKED"
