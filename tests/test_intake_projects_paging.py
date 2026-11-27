"""intake_state.py --projects (spec 106, #1827): a head's sub-issues and its check issue's parts
past the first page are read in full by a follow-up query on that one issue, never refused"""

from types import ModuleType
from typing import Any

import pytest

from .test_intake_outcomes import ist
from .test_intake_projects import BOT, FRESH, NOW, check, head, sub

__all__ = ["ist"]  # the module fixture, shared with spec 101's tests


class Run:
    """gh api graphql as a stub: the heads' pages, and each issue's sub-issues paged by first
    and cursor; the calls' queries and variables"""

    def __init__(self, heads: dict[str, list[dict[str, Any]]], trees: dict[int, list[dict[str, Any]]]):
        self.heads, self.trees = heads, trees
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((query, variables))
        if "issue(number: $number)" in query:
            nodes = self.trees[variables["number"]]
            start = int(variables.get("cursor") or 0)
            page = nodes[start : start + variables["first"]]
            end = start + len(page)
            info = {"hasNextPage": end < len(nodes), "endCursor": str(end)}
            connection = {"totalCount": len(nodes), "pageInfo": info, "nodes": page}
            return {"data": {"repository": {"issue": {"subIssues": connection}}}}
        nodes = self.heads["OPEN" if "states: OPEN" in query else "CLOSED"]
        return {"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": False}, "nodes": nodes}}}}

    def followed(self) -> list[int]:
        """The issues a follow-up query read, in order, once per page"""
        return [v["number"] for q, v in self.calls if "issue(number: $number)" in q]


def parts(states: str) -> list[dict[str, Any]]:
    """A check issue's parts as the follow-up reads them, O open and C closed"""
    return [
        {"number": 900 + i, "state": "OPEN" if s == "O" else "CLOSED", "updatedAt": FRESH} for i, s in enumerate(states)
    ]


def short(node: dict[str, Any], read: int) -> dict[str, Any]:
    """node's sub-issues as the head query reads them: the first read of them, the whole count"""
    connection = node["subIssues"]
    connection["nodes"] = connection["nodes"][:read]
    return node


def test_s106_12_a_check_issue_with_more_parts_than_a_page_reads_them_all(ist: ModuleType) -> None:
    """#1827: a check issue with 13 parts, 10 read with the head, counts all 13"""
    all_parts = parts("OOOOOCCCCCCCC")
    checked = check(parts=tuple(p["state"] for p in all_parts))
    run = Run({"OPEN": [head(7, (short(checked, ist.PROJECT_PARTS), sub(8, "CLOSED")))], "CLOSED": []}, {50: all_parts})
    (row,) = ist.fetch_projects("o/r", BOT, NOW, run)
    assert (row.state, row.note, row.parts_open, row.parts_closed) == ("PROJECT_ACTIVE", "5 of 14 parts open", 5, 9)
    assert run.followed() == [50]
    query, variables = next((q, v) for q, v in run.calls if "issue(number: $number)" in q)
    assert "nodes { number state updatedAt }" in query
    assert (variables["owner"], variables["name"], variables["first"]) == ("o", "r", 100)


def test_s106_12_a_head_with_more_sub_issues_than_a_page_reads_them_all(ist: ModuleType) -> None:
    """#1827: a head with 25 sub-issues, 20 read with it, reads the rest in pages of 20; its
    check issue, past the first page and with 12 parts, reads its parts in full too"""
    checked = check(parts=tuple("OPEN" for _ in range(ist.PROJECT_PARTS)))
    checked["subIssues"]["totalCount"] = 12
    subs = [sub(100 + i, "CLOSED") for i in range(24)] + [checked]
    node = head(7, tuple(subs))
    node["subIssues"]["nodes"] = node["subIssues"]["nodes"][: ist.PROJECT_SUBS]
    run = Run({"OPEN": [node], "CLOSED": []}, {7: subs, 50: parts("OOCCCCCCCCCC")})
    (row,) = ist.fetch_projects("o/r", BOT, NOW, run)
    assert (row.check, row.parts_open, row.parts_closed) == (50, 2, 34)
    assert row.note == "2 of 36 parts open"
    assert run.followed() == [7, 7, 50]  # two pages of the head's, one of the check's
    query = next(q for q, v in run.calls if v.get("number") == 7)
    # an open head's sub-issues as the head query reads them: their pull requests and parts
    assert "closedByPullRequestsReferences" in query and "subIssues(first: 10)" in query


def test_s106_12_a_closed_heads_sub_issues_page_with_their_parts_as_counts(ist: ModuleType) -> None:
    summed = check()
    del summed["subIssues"]
    summed["subIssuesSummary"] = {"total": 3, "completed": 3}
    subs = [sub(100 + i, "CLOSED") for i in range(24)] + [summed]
    for each in subs[:24]:
        del each["subIssues"]
        each["subIssuesSummary"] = {"total": 0, "completed": 0}
    closed = head(9, tuple(subs), state="CLOSED", reason="COMPLETED", closed_at="2026-11-20T00:00:00Z")
    closed["subIssues"]["nodes"] = closed["subIssues"]["nodes"][: ist.PROJECT_SUBS]
    run = Run({"OPEN": [], "CLOSED": [closed]}, {9: subs})
    (row,) = ist.fetch_projects("o/r", BOT, NOW, run)
    assert (row.state, row.parts_open, row.parts_closed) == ("PROJECT_CLOSED", 0, 27)
    query = next(q for q, v in run.calls if v.get("number") == 9)
    assert "subIssuesSummary { total completed }" in query and "closedByPullRequestsReferences" not in query


def test_s106_12_a_head_read_in_full_makes_no_follow_up(ist: ModuleType) -> None:
    """the common case costs what it did: no follow-up query, nor for an issue that is no head"""
    outsider = short(head(8, (check(parts=("OPEN",) * 13),), association="NONE", author="drive-by"), 1)
    outsider["subIssues"]["totalCount"] = 30
    run = Run({"OPEN": [head(7, (check(parts=("OPEN", "CLOSED")), sub(8))), outsider], "CLOSED": []}, {})
    assert [(r.number, r.note) for r in ist.fetch_projects("o/r", BOT, NOW, run)] == [(7, "2 of 3 parts open")]
    assert run.followed() == []


def test_s106_12_a_connection_still_short_after_paging_is_refused(
    ist: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """a follow-up that reads fewer sub-issues than GitHub counts is a read error: exit 2"""
    all_parts = parts("O" * 13)
    checked = short(check(parts=("OPEN",) * 13), ist.PROJECT_PARTS)

    class Short(Run):
        def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
            answer = super().__call__(query, variables)
            issue = answer["data"]["repository"].get("issue")
            if issue is not None:
                issue["subIssues"]["nodes"] = issue["subIssues"]["nodes"][:12]
            return answer

    with pytest.raises(SystemExit) as exited:
        ist.fetch_projects("o/r", BOT, NOW, Short({"OPEN": [head(7, (checked,))], "CLOSED": []}, {50: all_parts}))
    assert exited.value.code == 2
    assert "check issue #50 has 13 sub-issues, more than intake_state.py reads (12)" in capsys.readouterr().err


def test_s106_12_a_follow_up_on_another_issue_than_the_head_read_is_refused(
    ist: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """a check issue of another repo (chains.py's own_check) follows up on the checkout's issue
    of its number: a count other than the head query read is a read error, never its parts"""
    checked = short(check(parts=("OPEN",) * 13), ist.PROJECT_PARTS)
    run = Run({"OPEN": [head(7, (checked,))], "CLOSED": []}, {50: parts("CCC")})
    with pytest.raises(SystemExit) as exited:
        ist.fetch_projects("o/r", BOT, NOW, run)
    assert exited.value.code == 2
    assert "#50 has 3 sub-issues in o/r, where the first read counted 13" in capsys.readouterr().err
