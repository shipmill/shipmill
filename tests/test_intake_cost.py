"""What intake_state.py's GraphQL queries cost GitHub's rate limit (#1459), without gh or the network"""

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "product-intake" / "scripts" / "intake_state.py"


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    spec = importlib.util.spec_from_file_location("intake_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def worst_case_nodes(query: str) -> int:
    """GitHub's node count for a query: each connection's first or last times the sizes of the
    connections it sits in, summed (as tests/test_gate_walk.py counts it, #1458)"""
    total, stack, size = 0, [1], None
    for token in re.finditer(r"\([^()]*\)|\{|\}", query):
        if token[0] == "}":
            stack.pop()
        elif token[0] == "{":
            nested = stack[-1] * (size or 1)
            total += nested if size else 0
            stack.append(nested)
            size = None
        else:
            found = re.search(r"\b(?:first|last): (\d+)", token[0])
            size = int(found[1]) if found else None
    return total


def worst_case_points(query: str) -> int:
    """GitHub's rate-limit points for a query: each connection costs one request per node of
    the connections it sits in, and the points are the requests over 100, rounded, at least 1"""
    requests, stack, size = 0, [1], None
    for token in re.finditer(r"\([^()]*\)|\{|\}", query):
        if token[0] == "}":
            stack.pop()
        elif token[0] == "{":
            requests += stack[-1] if size else 0
            stack.append(stack[-1] * (size or 1))
            size = None
        else:
            found = re.search(r"\b(?:first|last): (\d+)", token[0])
            size = int(found[1]) if found else None
    return max(1, round(requests / 100))


def test_1459_the_counting_matches_githubs() -> None:
    nested = "a(first: 2) { nodes { b(last: 3) { n } c(first: 4) { n } } }"
    assert worst_case_nodes(nested) == 2 + 2 * 3 + 2 * 4
    assert worst_case_points(" ".join([nested] * 30)) == 2  # 30 x (1 + 2 + 2) requests


# Measured on shipmill/shipmill with `rateLimit { cost nodeCount }`: each query is 1 point and
# returns these nodeCounts; a page of 75 issues measured 2 points (151 requests)
PINNED = {
    "OPEN_ISSUES": 70 + 70 * 100 + 70 * 100,
    "OPPORTUNITIES": 70 + 70 * 100 + 70 * 100,
    "PLAN_ISSUES": 70 + 70 * 100 + 70 * 100,
    "DISCUSSIONS": 100,
    "PULLS": 100,
    "OLDER_COMMENTS": 100,
    "OLDER_PLAN_COMMENTS": 100,
}


@pytest.mark.parametrize("name", sorted(PINNED))
def test_1459_each_query_costs_1_point_and_its_pinned_nodes(ist: ModuleType, name: str) -> None:
    query = getattr(ist, name)
    assert worst_case_nodes(query) == PINNED[name]
    assert worst_case_points(query) == 1


@pytest.mark.parametrize("name", ["OPEN_ISSUES", "OPPORTUNITIES", "PLAN_ISSUES"])
def test_1459_a_bigger_page_of_issues_would_cost_2_points(ist: ModuleType, name: str) -> None:
    # 1 + 2 x 75 requests is 151: the page of issues with labels and comments nested is as
    # big as 1 point allows, within a margin
    query = getattr(ist, name)
    page = f"first: {ist.ISSUE_PAGE}, after: $cursor"
    assert query.count(page) == 1
    assert worst_case_points(query.replace(page, "first: 75, after: $cursor")) == 2


def test_1459_the_aliased_reads_cost_1_point(ist: ModuleType) -> None:
    asked: list[str] = []

    def run(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        asked.append(query)
        numbers = re.findall(r"\b([me])(\d+):", query)
        return {"data": {"repository": {f"{k}{n}": {"milestone": None} for k, n in numbers}}}

    assert ist.member_thumbs(run, "o", "r", list(range(1, 51))) == {n: 0 for n in range(1, 51)}
    ist.existing_milestones(run, "o", "r", list(range(1, 51)))
    assert len(asked) == 2 and all(worst_case_points(q) == 1 and worst_case_nodes(q) == 0 for q in asked)


def issue(number: int) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"Issue {number}",
        "url": f"https://github.com/o/r/issues/{number}",
        "state": "OPEN",
        "stateReason": None,
        "closedAt": None,
        "body": "",
        "author": {"__typename": "User", "login": "someone"},
        "authorAssociation": "NONE",
        "labels": {"pageInfo": {"hasNextPage": False}, "nodes": []},
        "reactions": {"totalCount": 0},
        "comments": {"pageInfo": {"hasPreviousPage": False, "startCursor": None}, "nodes": []},
    }


def discussion(number: int, closed: bool) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"Discussion {number}",
        "url": f"https://github.com/o/r/discussions/{number}",
        "closed": closed,
        "category": {"name": "Ideas"},
        "reactions": {"totalCount": number},
        "author": {"__typename": "User", "login": "someone"},
    }


def test_1459_every_issue_and_discussion_past_a_page_is_still_read(ist: ModuleType) -> None:
    # the pages' sizes changed, not what is read: 150 open issues and 250 discussions, open and
    # closed, come over pages of the queries' own size
    opened = [issue(n) for n in range(1, 151)]
    discussions = [discussion(n, closed=n % 2 == 0) for n in range(1001, 1251)]
    asked: list[tuple[str, int]] = []

    def run(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        head = re.search(r"(issues|discussions)\([^()]*first: (\d+)", query)
        assert head is not None, query
        key, size = head[1], int(head[2])
        start = int(variables.get("cursor") or 0)
        source = discussions if key == "discussions" else [] if "labels: [$label]" in query else opened
        asked.append((key, size))
        nodes = source[start : start + size]
        info = {"hasNextPage": start + size < len(source), "endCursor": str(start + size)}
        repo: dict[str, Any] = {key: {"pageInfo": info, "nodes": nodes}}
        if "hasDiscussionsEnabled" in query:
            repo["hasDiscussionsEnabled"] = True
        return {"data": {"repository": repo}}

    intake = ist.fetch(
        "o/r",
        label="opportunity",
        accepted="planned",
        marker="Triage:",
        skip=set(ist.SKIP_LABELS),
        categories=None,
        autonomy="propose",
        run=run,
    )
    assert [i["number"] for i in intake.open_issues] == list(range(1, 151))
    assert set(intake.thumbs) == set(range(1, 151)) | set(range(1001, 1251))  # the closed discussions too
    assert intake.thumbs[1250] == 1250
    feedback = [f.number for f in intake.feedback]
    assert feedback == list(range(1, 151)) + list(range(1001, 1251, 2))
    assert asked == [("issues", 70)] * 3 + [("issues", 70)] + [("discussions", 100)] * 3
