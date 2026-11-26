"""Spec 097: a goal plan whose work has closed is product intake's to close with its outcome,
never triage's with the parent's close comment"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "github-issue-triage"
SCRIPT = SKILL / "scripts" / "triage_state.py"
REPO = ("o", "r")
BOT = "shipmill-app[bot]"
NOTE = "work closed; product intake reports the outcome"
PLAN = "Triage: **plan**. Proposed for G-6; the maintainer accepts or declines it."
FILED = "Triage: **plan**: accepted and filed: W-1 #13, W-2 #14"


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    spec = importlib.util.spec_from_file_location("triage_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def comment(body: str, author: str = BOT, association: str = "NONE") -> dict[str, Any]:
    kind = "Bot" if author.endswith("[bot]") else "User"
    return {
        "createdAt": "2026-11-01T10:00:00Z",
        "body": body,
        "author": {"login": author.removesuffix("[bot]"), "__typename": kind},
        "authorAssociation": association,
    }


def plan(
    *comments: dict[str, Any], children: tuple[str, ...], labels: tuple[str, ...] = ("goal-plan",), body: str = ""
) -> dict[str, Any]:
    """A plan issue with its filed items as sub-issues #13, #14, ... in the given states"""
    nodes = [
        {
            "number": 13 + i,
            "state": state,
            "closedAt": None if state == "OPEN" else "2026-11-20T10:00:00Z",
            "repository": {"nameWithOwner": "o/r"},
        }
        for i, state in enumerate(children)
    ]
    return {
        "number": 12,
        "body": body,
        "labels": {"nodes": [{"name": n} for n in labels]},
        "comments": {"nodes": list(comments)},
        "timelineItems": {"nodes": []},
        "subIssues": {"nodes": nodes},
    }


def read(ts: ModuleType, item: dict[str, Any]) -> tuple[str, str]:
    found: tuple[str, str] = ts.classify_open(item, "Triage:", "postponed", {}, None, REPO, BOT, {})
    return found


def test_s097_5_a_plan_whose_work_closed_reads_triaged_never_unblocked(ts: ModuleType) -> None:
    assert read(ts, plan(comment(PLAN), children=("CLOSED", "CLOSED"))) == ("TRIAGED", NOTE)


def test_s097_5_the_filed_line_form_and_a_not_planned_item_read_the_same(ts: ModuleType) -> None:
    assert read(ts, plan(comment(FILED), children=("CLOSED", "NOT_PLANNED"))) == ("TRIAGED", NOTE)


def test_s097_5_a_maintainers_plan_comment_counts_too(ts: ModuleType) -> None:
    item = plan(comment(PLAN, "maintainer", "OWNER"), children=("CLOSED",))
    assert read(ts, item) == ("TRIAGED", NOTE)


def test_s097_5_a_plan_with_an_item_open_stays_blocked(ts: ModuleType) -> None:
    found = read(ts, plan(comment(FILED), children=("CLOSED", "OPEN")))
    assert found == ("BLOCKED", "children 1/2 closed o/r#13:closed(child) o/r#14:open(child)")


def test_s097_5_a_plan_with_a_check_reads_no_verify_due(ts: ModuleType) -> None:
    item = plan(comment(PLAN), children=("CLOSED",), body="## Check\n\nRun it.\n")
    assert read(ts, item) == ("TRIAGED", NOTE)


def test_s097_5_any_other_parent_whose_holds_closed_reads_unblocked_as_before(ts: ModuleType) -> None:
    unlabelled = plan(comment(PLAN), children=("CLOSED",), labels=())
    other_verdict = plan(comment("Triage: **implement**"), children=("CLOSED",))
    for item in (unlabelled, other_verdict):
        assert read(ts, item) == ("UNBLOCKED", "children 1/1 closed o/r#13:closed(child)")


def test_s097_5_an_outsiders_plan_comment_makes_no_plan(ts: ModuleType) -> None:
    item = plan(comment("Triage: **implement**"), comment(PLAN, "someone", "NONE"), children=("CLOSED",))
    assert read(ts, item) == ("UNBLOCKED", "children 1/1 closed o/r#13:closed(child)")
    # nor does an outsider's later triage comment take the plan reading away
    item = plan(comment(PLAN), comment("Triage: **implement**", "someone", "NONE"), children=("CLOSED",))
    assert read(ts, item) == ("TRIAGED", NOTE)


def test_s097_12_the_references_leave_a_plan_whose_work_closed_to_product_intake() -> None:
    comments = (SKILL / "references" / "comments.md").read_text(encoding="utf-8")
    close = comments.split("## A parent's close", 1)[1].split("\n## ", 1)[0]
    rubric = (SKILL / "references" / "triage-rubric.md").read_text(encoding="utf-8")
    for text in (close, rubric):
        flat = " ".join(text.split())
        assert f"`{NOTE}`" in flat
        assert "product intake's to close with its outcome" in flat
        assert "triage never closes it with the parent's close comment" in flat
