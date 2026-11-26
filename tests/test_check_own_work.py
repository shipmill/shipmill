"""#1671: an issue with a ## Check and no sub-issue reads by its check only once its own work
merged (a linked PR, or a hold that is a merged PR); held only by closed issues, it is work
to build and reads UNBLOCKED (#1027). Parents read as spec 042 says, unchanged"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_parent_check import CHECK, CLOSED_2, both_closed, parent, part, parted, waiting
from .test_triage_human import said

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-issue-triage" / "scripts" / "triage_state.py"
REPO = ("o", "r")
BOT = "shipmill-gate[bot]"
BUILD = f"Depends on o/r#30\n\n{CHECK}"
STATES = {("o", "r", 30): "CLOSED"}
CLOSES = {("o", "r", 30): CLOSED_2}


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    spec = importlib.util.spec_from_file_location("triage_state_check_own_work", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read(ts: ModuleType, item: dict[str, Any], states: dict[Any, str] = STATES) -> tuple[str, str]:
    verdict: tuple[str, str] = ts.classify_open(item, "Triage:", "postponed", states, None, REPO, BOT, CLOSES)
    return verdict


def test_1671_a_build_issue_whose_dependency_closed_is_work_to_build(ts: ModuleType) -> None:
    # A spec's build issue: Depends on #30, a ## Check, #30 closed, no PR of its own yet
    assert read(ts, parent([], body=BUILD)) == ("UNBLOCKED", "o/r#30:closed")
    assert read(ts, parent([], [waiting()], body=BUILD)) == ("UNBLOCKED", "o/r#30:closed")


def test_1671_once_its_own_pr_merged_its_comments_date_from_that_merge(ts: ModuleType) -> None:
    merged = "2026-09-05T10:00:00Z"  # after #30's close
    item = parted([part(21, merged=merged)], [waiting(at="2026-09-04T12:00:00Z")], body=BUILD)
    assert read(ts, item) == ("VERIFY_DUE", "o/r#30:closed #21:merged(part): run its ## Check")
    later = parted([part(21, merged=merged)], [waiting()], body=BUILD)
    assert read(ts, later)[0] == "WITH_PERSON"


def test_1671_a_merged_closer_of_an_open_issue_with_a_check_reads_by_its_check(ts: ModuleType) -> None:
    pr = {"number": 21, "state": "MERGED", "title": "Serve colour", "body": "Fixes #1", "mergedAt": CLOSED_2}
    node = {"willCloseTarget": True, "isCrossRepository": False, "source": pr}
    assert read(ts, parted([node]), {}) == ("VERIFY_DUE", "#21:merged: run its ## Check")
    early = parted([node], [waiting(at="2026-09-02T10:00:00Z")])
    assert read(ts, early, {})[0] == "VERIFY_DUE"


def test_1671_a_feature_issue_whose_spec_pr_merged_is_work_to_split(ts: ModuleType) -> None:
    # A feature issue held on its spec PR #40 by a hold comment, with a ## Check, #40 merged and
    # nothing built yet: the spec merged, so it is split into build issues, not checked
    item = parent([], body=CHECK)
    item["comments"]["nodes"] = [
        said(
            "Triage: **feature**. The spec is in #40.\n\nOn hold: the build waits on o/r#40, the spec PR.",
            "2026-09-01T10:00:00Z",
        )
    ]
    states = {("o", "r", 40): "MERGED"}
    verdict = ts.classify_open(item, "Triage:", "postponed", states, None, REPO, BOT, {("o", "r", 40): CLOSED_2})
    assert verdict == ("UNBLOCKED", "o/r#40:merged")


def test_1671_a_pull_request_linked_by_hand_dates_its_comments_from_its_merge(ts: ModuleType) -> None:
    # A PR linked in the Development sidebar (a ConnectedEvent) merged: a check-waiting comment
    # from before that merge counts no more than one before a "Part of #N" PR's merge does
    node = {"subject": {"number": 21, "state": "MERGED", "mergedAt": "2026-09-05T10:00:00Z"}}
    early = parted([node], [waiting(at="2026-09-04T12:00:00Z")])
    assert read(ts, early, {}) == ("VERIFY_DUE", "#21:merged: run its ## Check")
    assert "subject { ... on PullRequest { number state mergedAt" in ts.OPEN_TIMELINE


def test_1671_a_postponed_issue_without_sub_issues_reads_postponed_first(ts: ModuleType) -> None:
    held = parted([part(21)], body=BUILD, labels=("postponed",))
    assert read(ts, held)[0] == "POSTPONED"
    merged_hold = parent([], body=BUILD, labels=("postponed",))
    assert read(ts, merged_hold, {("o", "r", 30): "MERGED"})[0] == "POSTPONED"


def test_1671_a_postponed_parent_keeps_main_s_reading(ts: ModuleType) -> None:
    item = parent(both_closed(), labels=("postponed",))
    assert read(ts, item, {})[0] == "VERIFY_DUE"
