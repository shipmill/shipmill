"""S-106-30 (#1823): a started project reads alike everywhere, as triage_state.py reads it since
S-106-29. chains.py's walk never holds the head on its own check issue, `shipmill status --item`
reads the check issue waiting on the head's work and the head on its due check, and
`intake_state.py --projects` reads a head whose work is done closing, its linked pull requests
read for it; without gh or the network"""

import datetime as dt
from types import ModuleType
from typing import Any

import pytest

from shipmill.status import Issue

from .test_chains_show import Forge, forge, shown
from .test_chains_show import ch as ch
from .test_intake_projects import BOT, CHECK, Gh, check, head, read, sub
from .test_intake_projects import ist as ist
from .test_status_goal_states import conditions
from .test_status_item import blocks
from .test_status_picture import REPO, facts

__all__ = ["forge"]

MERGED_AT = "2026-11-26T10:00:00Z"


def state(ist: ModuleType, node: dict[str, Any]) -> str:
    """The state a head reads; it is a head"""
    found = read(ist, node)
    assert found is not None
    return found[0]


def linked(pr: int, state: str, body: str = "Part of #7", updated: str = MERGED_AT) -> dict[str, Any]:
    """A same-repo pull request linked to head #7, as intake's WORK reads it"""
    merged = MERGED_AT if state == "MERGED" else None
    return {
        "willCloseTarget": False,
        "isCrossRepository": False,
        "source": {
            "number": pr,
            "state": state,
            "title": "Build it",
            "body": body,
            "mergedAt": merged,
            "updatedAt": updated,
        },
    }


def started(*prs: dict[str, Any], subs: tuple[dict[str, Any], ...] = (), more: bool = False) -> dict[str, Any]:
    """Head #7 with its open check issue #50, its parts subs, and the pull requests linked to it"""
    node = head(subs=(check(), *subs))
    node["prs"] = {"pageInfo": {"hasNextPage": more}, "nodes": list(prs)}
    return node


# -- intake_state.py --projects ---------------------------------------------------------------


def test_s106_30_a_head_with_no_parts_reads_closing_once_its_part_of_pr_merged(ist: ModuleType) -> None:
    assert read(ist, started()) == ("PROJECT_ACTIVE", "no part filed")
    building = ist.project_row(started(linked(80, "OPEN")), BOT)
    assert (building.state, building.note, building.counted) == ("PROJECT_ACTIVE", "no part filed, a PR open", True)
    done = ist.project_row(started(linked(80, "MERGED")), BOT)
    assert (done.state, done.note, done.counted) == ("PROJECT_CLOSING", "no cleanup listed", False)
    # another pull request of the head still open: its work isn't done
    assert read(ist, started(linked(80, "MERGED"), linked(81, "OPEN"))) == (
        "PROJECT_ACTIVE",
        "no part filed, a PR open",
    )
    # a closed unmerged pull request is no work, and a mention that neither closes nor is Part of is none
    assert state(ist, started(linked(80, "CLOSED"), linked(82, "MERGED", body="See #7"))) == "PROJECT_ACTIVE"


def test_s106_30_a_head_with_parts_closes_once_they_closed_and_no_pr_of_its_is_open(ist: ModuleType) -> None:
    assert state(ist, started(subs=(sub(8, "CLOSED"),))) == "PROJECT_CLOSING"
    assert read(ist, started(linked(80, "OPEN"), subs=(sub(8, "CLOSED"),))) == (
        "PROJECT_ACTIVE",
        "0 of 1 parts open, a PR open",
    )
    assert read(ist, started(linked(80, "MERGED"), subs=(sub(8),))) == ("PROJECT_ACTIVE", "1 of 1 parts open")


def test_s106_30_a_reverted_pr_is_no_done_work_while_its_revert_stands(ist: ModuleType) -> None:
    record = ((BOT, "<!-- shipmill:reverted #80 by #81 -->"),)
    reverted = started(linked(80, "MERGED"))
    reverted["comments"] = head(comments=record)["comments"]
    assert read(ist, reverted) == ("PROJECT_ACTIVE", "no part filed")
    # the same record by anyone else counts for nothing
    other = started(linked(80, "MERGED"))
    other["comments"] = head(comments=(("drive-by", record[0][1]),))["comments"]
    assert state(ist, other) == "PROJECT_CLOSING"
    # the revert closed unmerged, read on the head: #80 counts again
    refused = started(linked(80, "MERGED"), linked(81, "CLOSED", body="Revert #80, Part of #7"))
    refused["comments"] = reverted["comments"]
    assert state(ist, refused) == "PROJECT_CLOSING"


def test_s106_30_a_head_read_without_its_prs_or_with_more_than_a_page(ist: ModuleType) -> None:
    assert read(ist, head(subs=(check(),))) == ("PROJECT_ACTIVE", "no part filed")  # a closed head's read
    with pytest.raises(SystemExit):
        ist.project_row(started(linked(80, "MERGED"), more=True), BOT)
    assert "prs: timelineItems" in ist.OPEN_HEADS and "prs: timelineItems" in ist.heads_query(["o/a"])
    assert "prs: timelineItems" not in ist.CLOSED_HEADS


def test_s106_30_a_done_head_of_another_repo_counts_nothing(ist: ModuleType) -> None:
    summed = check()
    del summed["subIssues"]
    summed["subIssuesSummary"] = {"total": 0, "completed": 0}
    done = head(5, (summed,))
    done["prs"] = {"pageInfo": {"hasNextPage": False}, "nodes": [linked(80, "MERGED", body="Part of #5")]}
    building = head(6, (dict(summed),))
    building["prs"] = {"pageInfo": {"hasNextPage": False}, "nodes": [linked(81, "OPEN", body="Part of #6")]}
    product = ist.Product("o/home", ("o/home", "o/api"), 3)
    assert ist.projects_active(product, [], Gh(ist, {"o/api": [done, building]}), BOT).active == 1


def test_s106_30_a_pr_linked_to_the_head_moves_its_tree(ist: ModuleType) -> None:
    later = "2026-12-20T10:00:00Z"
    node = started(linked(80, "OPEN", updated=later))
    assert ist.tree_updated(node, BOT) == dt.datetime(2026, 12, 20, 10, tzinfo=dt.UTC)
    # a pull request that only mentions the head, or one of another repo, is no work of its
    mention = started(linked(81, "OPEN", body="See #7", updated=later))
    assert ist.tree_updated(mention, BOT) < dt.datetime(2026, 12, 20, 10, tzinfo=dt.UTC)
    foreign = linked(82, "OPEN", updated=later) | {"isCrossRepository": True}
    assert ist.tree_updated(started(foreign), BOT) < dt.datetime(2026, 12, 20, 10, tzinfo=dt.UTC)


# -- chains.py show ---------------------------------------------------------------------------


def project(forge: Forge, labels: tuple[str, ...] = ("project",), check_repo: str = "o/r") -> str:
    forge.issue("o/r#7", labels=list(labels), children=[f"{check_repo}#50"], blocking=["o/r#9"])
    forge.issue(f"{check_repo}#50", title="Check: the page shows the plan", body=CHECK, parent="o/r#7")
    forge.issue("o/r#9", blocked_by=["o/r#7"])
    forge.configs = {"o/r": None, "o/x": None}
    return f"{check_repo}#50"


def test_s106_30_the_walk_never_holds_a_started_head_on_its_check(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    check_ref = project(forge)
    _, rows = shown(ch, forge, capsys, "o/r#7")
    by = {r["ref"]: r for r in rows}
    assert (by["o/r#7"]["holds"], by["o/r#7"]["state"]) == ([], "READY")
    assert check_ref not in by  # the check issue is in no chain of its head's
    _, rows = shown(ch, forge, capsys, check_ref)
    assert [(r["ref"], r["waited_on_by"]) for r in rows] == [(check_ref, [])]


@pytest.mark.parametrize(("labels", "check_repo"), [(("project", "held"), "o/r"), (("project",), "o/x"), ((), "o/r")])
def test_s106_30_a_held_head_another_repos_check_or_no_project_reads_as_before(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str], labels: tuple[str, ...], check_repo: str
) -> None:
    check_ref = project(forge, labels, check_repo)
    _, rows = shown(ch, forge, capsys, check_ref)
    by = {r["ref"]: r for r in rows}
    assert by["o/r#7"]["holds"] == [check_ref] and by["o/r#7"]["state"] == "BLOCKED"
    assert by[check_ref]["waited_on_by"] == ["o/r#7"]


# -- shipmill status --item -------------------------------------------------------------------


def test_s106_30_the_check_issue_waits_on_the_heads_work_not_the_head_on_it() -> None:
    waits = "project #7: check waits on its work (no part filed, a PR open)"
    found = facts(issues=[Issue(7, "IN_PROGRESS", "#80:open(part)"), Issue(50, "BLOCKED", waits)])
    assert blocks(found, 50, []) == []
    assert blocks(found, 7, []) == [f"  blocks:  {REPO}#50 (parked: waits on this)"]
    reason, _, clears = conditions(found, 50)[0]
    assert reason == "project #7's check: waits on its work (no part filed, a PR open)"
    assert clears.startswith("#7's parts closing and its pull requests merging")


def test_s106_30_a_done_projects_head_waits_on_its_check() -> None:
    due = "project #7: check #50 due (no part filed, 1 PR merged)"
    found = facts(issues=[Issue(7, "BLOCKED", due), Issue(50, "VERIFY_DUE", "project #7: run its ## Check")])
    assert blocks(found, 7, []) == []
    (line,) = blocks(found, 50, [])
    assert line.startswith(f"  blocks:  {REPO}#7 (") and line.endswith(": waits on this)")
    assert conditions(found, 7)[0][0] == "its project's work is done: waits on check #50"
