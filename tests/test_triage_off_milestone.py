"""Spec 022, #400: triage_state.py reports a build issue outside its feature issue's milestone"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_triage_state import comment, first_page, open_issue

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-issue-triage" / "scripts" / "triage_state.py"
REPO = ("o", "r")
TRIAGED = comment("Triage: implement")


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    spec = importlib.util.spec_from_file_location("triage_state_milestone", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build(own: str | None, goal: str | None, parent_repo: str = "o/r", parent: bool = True) -> dict[str, Any]:
    """Build issue #7, triaged implement, in milestone ``own``, under feature issue #3 in ``goal``"""
    item = open_issue(7, [TRIAGED])
    item["milestone"] = {"title": own} if own is not None else None
    if parent:
        milestone = {"title": goal} if goal is not None else None
        item["parent"] = {"number": 3, "repository": {"nameWithOwner": parent_repo}, "milestone": milestone}
    else:
        item["parent"] = None
    return item


def classify(ts: ModuleType, item: dict[str, Any]) -> tuple[str, str]:
    found: tuple[str, str] = ts.classify_open(item, "Triage:", "postponed", {}, None, REPO)
    return found


@pytest.mark.parametrize(
    ("own", "note"),
    [
        (None, "parent #3 is in milestone 1.5.0, this is in no milestone"),
        ("1.6.0", "parent #3 is in milestone 1.5.0, this is in milestone 1.6.0"),
    ],
)
def test_s022_12_a_build_issue_outside_its_parents_milestone_reads_off_milestone(
    ts: ModuleType, own: str | None, note: str
) -> None:
    assert classify(ts, build(own, "1.5.0")) == ("OFF_MILESTONE", note)
    assert "OFF_MILESTONE" in ts.ACTION  # the script exits 1 on it


@pytest.mark.parametrize(
    "item",
    [
        build("1.5.0", "1.5.0"),  # already in it
        build(None, None),  # the parent has no milestone
        build("1.6.0", None),
        build(None, None, parent=False),  # no parent at all
        build(None, "1.5.0", parent_repo="other/lib"),  # another repo's milestones aren't this one's
    ],
)
def test_s022_12_one_in_the_milestone_or_whose_parent_has_none_reads_its_usual_state(
    ts: ModuleType, item: dict[str, Any]
) -> None:
    assert classify(ts, item)[0] == "NEEDS_PR"


def test_s022_12_the_parent_repo_compares_without_case(ts: ModuleType) -> None:
    assert classify(ts, build(None, "1.5.0", parent_repo="O/R"))[0] == "OFF_MILESTONE"


def test_s022_12_an_issue_fetched_without_milestone_fields_reads_its_usual_state(ts: ModuleType) -> None:
    assert classify(ts, open_issue(7, [TRIAGED]))[0] == "NEEDS_PR"


def test_s022_12_it_is_read_before_the_other_states_but_after_the_gates(ts: ModuleType) -> None:
    item = build(None, "1.5.0")
    item["timelineItems"]["nodes"] = [{"willCloseTarget": True, "source": {"number": 8, "state": "OPEN"}}]
    assert classify(ts, item)[0] == "OFF_MILESTONE"  # not IN_PROGRESS: one edit, then its usual state
    item["labels"]["nodes"] = [{"name": "needs-decision"}]
    assert ts.gated(item, None, False)[0] == "NEEDS_DECISION"


def test_s022_12_the_parent_and_milestone_come_in_the_existing_queries(ts: ModuleType) -> None:
    # one query asks for every open issue's parent and milestone, never a call per issue
    for query in (ts.QUERY, ts.OPEN_PAGE):
        assert "milestone { title }" in query
        assert "parent { number repository { nameWithOwner } milestone { title } }" in query
    # a forge without sub-issues has no parent field either: the text query asks for neither
    for query in (ts.TEXT_QUERY, ts.TEXT_OPEN_PAGE):
        assert "parent" not in query and "milestone { title }" in query
    error = {"extensions": {"code": "undefinedField", "fieldName": "parent"}, "message": "undefined"}
    assert ts.native_refused({"errors": [error]}) is not None


FAKE_GH = """#!{python}
import json, os, sys
print(open(os.environ["FAKE_GH_DATA"]).read())
"""


def test_s022_12_the_script_reports_off_milestone_and_exits_1(tmp_path: Path) -> None:
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    gh = fakes / "gh"
    gh.write_text(FAKE_GH.format(python=sys.executable), encoding="utf-8")
    gh.chmod(0o700)
    data = tmp_path / "gh.json"
    page = first_page([build(None, "1.5.0")])
    data.write_text(json.dumps({"data": {"repository": page}}), encoding="utf-8")
    env = {"PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]), "FAKE_GH_DATA": str(data)}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "o/r", "--json"], capture_output=True, text=True, check=False, env=env
    )
    assert proc.returncode == 1, proc.stderr
    assert [json.loads(line) for line in proc.stdout.splitlines()] == [
        {
            "number": 7,
            "state": "OFF_MILESTONE",
            "title": "issue 7",
            "note": "parent #3 is in milestone 1.5.0, this is in no milestone",
        }
    ]
