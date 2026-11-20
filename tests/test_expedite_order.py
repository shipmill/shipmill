"""Spec 070's expedite outcomes taken first: watch_state.py's expedite rows of tiers 3 and 6
(S-070-3), walk.order's expedite group (S-070-4), and triage_state.py's --wip ready list
(S-070-6), without the network"""

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.errors import ReleaseError
from shipmill.findings import Finding, fingerprint, parse_findings
from shipmill.walk import Changes, Handed, Rows, Swept, order, walk

from .test_watch_tiers import HEAD, checkout, known, pr

ROOT = Path(__file__).resolve().parents[1]
WATCH = ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
TRIAGE = ROOT / "skills" / "github-issue-triage" / "scripts" / "triage_state.py"
NOW = dt.datetime(2026, 11, 19, 12, 0, tzinfo=dt.UTC)
BOT = "shipmill-app[bot]"
TRIAGE_FIX = "/shipmill:github-issue-triage o/r"
LAND_FIX = "/shipmill:github-pr-triage o/r"


def load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load(WATCH, "watch_state_expedite")


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load(TRIAGE, "triage_state_expedite")


def person(login: str) -> dict[str, str]:
    return {"__typename": "User", "login": login}


APP = {"__typename": "Bot", "login": "shipmill-app"}


def labeled(label: str, actor: dict[str, str] | None) -> dict[str, Any]:
    return {"label": {"name": label}, "actor": actor}


# -- S-070-3: the rows watch_state.py marks ------------------------------------------------


def test_s070_3_each_row_is_cut_into_its_expedite_and_standard_subjects(ws: ModuleType) -> None:
    issues = frozenset({5, 101, 102})  # opportunity #5 and its sub-issues #101, #102
    rows = [
        ws.Row("ISSUES", "o/r", "NEW #6 #101", TRIAGE_FIX),
        ws.Row("ISSUES", "o/r", "UNBLOCKED #102", TRIAGE_FIX),
        ws.Row("ISSUES", "o/r", "NEEDS_PR #7 #8", TRIAGE_FIX),  # no expedite issue: stays whole
        ws.Row("ISSUES", "docs/specs/001-x.md", "SPEC_UNSPLIT S-001 x (docs/specs/001-x.md): #5", TRIAGE_FIX),
        ws.Row("PRS_OPEN", "o/r", "#3 #4 #9", LAND_FIX, ((3, HEAD), (4, HEAD), (9, HEAD))),
        ws.Row("AGENT_DRAFT", "o/r", "#20 #21", LAND_FIX),
        ws.Row("LAND_DUE", "#30", "a title: the land window is open", LAND_FIX),
        ws.Row("LAND_DUE", "#31", "a title: the land window is open", LAND_FIX),
        ws.Row("NEEDS_DECISION", "o/r", "#5", "answer it"),  # never an expedite row
    ]
    # pull requests #3 and #21 close a sub-issue, #30 the opportunity itself; #4 closes another issue
    closing = {3: frozenset({101}), 4: frozenset({7}), 9: frozenset(), 20: frozenset(), 21: frozenset({102})}
    closing |= {30: frozenset({5}), 31: frozenset()}
    found = [(r.state, r.subject, r.detail, r.expedite) for r in ws.expedite_marked(rows, issues, closing)]
    assert found == [
        ("ISSUES", "o/r", "NEW #101", True),
        ("ISSUES", "o/r", "NEW #6", False),
        ("ISSUES", "o/r", "UNBLOCKED #102", True),
        ("ISSUES", "o/r", "NEEDS_PR #7 #8", False),
        ("ISSUES", "docs/specs/001-x.md", "SPEC_UNSPLIT S-001 x (docs/specs/001-x.md): #5", False),
        ("PRS_OPEN", "o/r", "#3", True),
        ("PRS_OPEN", "o/r", "#4 #9", False),
        ("AGENT_DRAFT", "o/r", "#21", True),
        ("AGENT_DRAFT", "o/r", "#20", False),
        ("LAND_DUE", "#30", "a title: the land window is open", True),
        ("LAND_DUE", "#31", "a title: the land window is open", False),
        ("NEEDS_DECISION", "o/r", "#5", False),
    ]
    marked = ws.expedite_marked(rows, issues, closing)
    assert [r.heads for r in marked if r.state == "PRS_OPEN"] == [((3, HEAD),), ((4, HEAD), (9, HEAD))]
    # --json prints the key on an expedite row alone, so every other row prints as before
    assert marked[0].json()["expedite"] is True and "expedite" not in marked[1].json()
    # nothing expedite: every row as it was
    assert ws.expedite_marked(rows, frozenset(), closing) == rows
    with pytest.raises(ValueError, match="never expedite"):
        ws.Row("NEEDS_DECISION", "o/r", "#5", "answer it", expedite=True)


def test_s070_3_the_outcome_is_the_expedite_opportunity_and_its_sub_issues(ws: ModuleType) -> None:
    def node(
        labels: tuple[str, ...], events: list[dict[str, Any]], subs: tuple[int, ...], repo: str = "O/R"
    ) -> dict[str, Any]:
        nodes = [{"number": n, "state": "OPEN", "repository": {"nameWithOwner": repo}} for n in subs]
        return {
            "labels": {"nodes": [{"name": n} for n in ("opportunity", "planned", *labels)]},
            "milestone": None,
            "subIssues": {"pageInfo": {"hasNextPage": False}, "nodes": nodes},
            "timelineItems": {"nodes": events},
        }

    across = node(("expedite",), [labeled("expedite", person("alice"))], (101,))
    # a sub-issue in another repo is no issue of this one, whatever its number
    across["subIssues"]["nodes"].append({"number": 104, "state": "OPEN", "repository": {"nameWithOwner": "o/other"}})
    answer = {
        "n4": across,
        "n5": node(("expedite",), [labeled("expedite", person("alice"))], (101, 102)),
        "n6": node(("expedite",), [labeled("expedite", APP)], (103,)),  # the App's label: standard
        # both labels a person added: standard (S-070-2)
        "n7": node(
            ("expedite", "fixed-date"), [labeled("expedite", person("a")), labeled("fixed-date", person("a"))], ()
        ),
    }

    def read(cmd: list[str]) -> str:
        return json.dumps({"data": {"repository": answer}})

    found = ws.read_opportunities("o/r", [4, 5, 6, 7], BOT, read)
    assert {o.number: (o.service, o.outcome) for o in found} == {
        4: ("expedite", frozenset({101})),
        5: ("expedite", frozenset({101, 102})),
        6: ("standard", frozenset({103})),
        7: ("standard", frozenset()),
    }
    bad = node(("expedite",), [], ())
    bad["subIssues"]["nodes"] = [{"state": "OPEN"}]
    with pytest.raises(ws.Refused, match="sub-issue without its number"):
        ws.read_opportunities("o/r", [5], BOT, lambda cmd: json.dumps({"data": {"repository": {"n5": bad}}}))


def test_s070_3_closing_issues_are_read_for_the_pull_requests_of_this_repo(ws: ModuleType) -> None:
    ran: list[list[str]] = []

    def read(cmd: list[str]) -> str:
        ran.append(cmd)
        refs = [
            {"number": 101, "repository": {"nameWithOwner": "O/R"}},
            {"number": 5, "repository": {"nameWithOwner": "x/y"}},
        ]
        repository = {
            "n3": {"closingIssuesReferences": {"nodes": refs}},
            "n4": {"closingIssuesReferences": {"nodes": []}},
        }
        return json.dumps({"data": {"repository": repository}})

    assert ws.closing_issues("o/r", [4, 3, 3], read) == {3: frozenset({101}), 4: frozenset()}
    assert len(ran) == 1 and "n3: pullRequest(number: 3)" in ran[0][4] and "n4: pullRequest(number: 4)" in ran[0][4]
    with pytest.raises(ws.Refused, match="closing issues"):
        ws.closing_issues("o/r", [3], lambda cmd: json.dumps({"data": {"repository": {"n3": None}}}))


# tier 3 as the gate reads it: the expedite opportunities' list, their GraphQL read, and the
# pull requests' closing issues, each answered from the environment and logged
EXPEDITE_GH = """#!{python}
import json, os, sys
args = sys.argv[1:]
joined = " ".join(args)
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["issue", "list"] and "expedite" in args:
    print(os.environ["FAKE_EXPEDITE"])
elif args[:2] == ["api", "graphql"] and ": issue(number:" in joined:
    print(json.dumps({"data": {"repository": json.loads(os.environ["FAKE_OPPORTUNITIES"])}}))
elif args[:2] == ["api", "graphql"] and ": pullRequest(number:" in joined:
    print(json.dumps({"data": {"repository": json.loads(os.environ["FAKE_CLOSING"])}}))
else:
    sys.stderr.write("unexpected gh call: " + joined + "\\n")
    sys.exit(1)
"""


def opportunity_issue(number: int, *labels: str) -> dict[str, Any]:
    """One open issue as `gh issue list --json` prints it"""
    return {
        "number": number,
        "title": "t",
        "body": "",
        "createdAt": "2026-11-01T00:00:00Z",
        "closedAt": None,
        "stateReason": None,
        "author": {"login": "alice", "is_bot": False},
        "labels": [{"name": n} for n in labels],
        "closedByPullRequestsReferences": [],
    }


def tier_3(tmp_path: Path, expedite: list[dict[str, Any]], prs: list[dict[str, object]]) -> tuple[Any, list[Any]]:
    work = checkout(tmp_path)
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    (fakes / "gh").write_text(EXPEDITE_GH.replace("{python}", sys.executable), encoding="utf-8")
    (fakes / "gh").chmod(0o700)
    log = tmp_path / "gh.log"
    log.touch()
    opportunities = {
        "n5": {
            "labels": {"nodes": [{"name": n} for n in ("opportunity", "planned", "expedite")]},
            "milestone": None,
            "subIssues": {
                "pageInfo": {"hasNextPage": False},
                "nodes": [{"number": 101, "state": "OPEN", "repository": {"nameWithOwner": "o/r"}}],
            },
            "timelineItems": {"nodes": [labeled("expedite", person("alice"))]},
        }
    }
    closing = {
        "n3": {"closingIssuesReferences": {"nodes": [{"number": 101, "repository": {"nameWithOwner": "o/r"}}]}},
        "n7": {"closingIssuesReferences": {"nodes": []}},
    }
    path = tmp_path / "known.json"
    path.write_text(json.dumps(known(prs=prs)), encoding="utf-8")
    env = {
        "PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]),
        "HOME": str(tmp_path),
        "FAKE_LOG": str(log),
        "FAKE_EXPEDITE": json.dumps(expedite),
        "FAKE_OPPORTUNITIES": json.dumps(opportunities),
        "FAKE_CLOSING": json.dumps(closing),
    }
    cmd = [sys.executable, str(WATCH), "o/r", "--repo-dir", str(work), "--json", "--tier", "3", "--known", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    assert proc.returncode in (0, 1), proc.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return parse_findings(proc.stdout), calls


def test_s070_3_tier_3_marks_the_pull_request_closing_a_sub_issue_and_no_other(tmp_path: Path) -> None:
    rows, calls = tier_3(tmp_path, [opportunity_issue(5, "opportunity", "planned", "expedite")], [pr(3), pr(7)])
    assert [(f.state, f.detail, f.expedite, f.heads) for f in rows] == [
        ("PRS_OPEN", "#3", True, ((3, HEAD),)),
        ("PRS_OPEN", "#7", False, ((7, HEAD),)),
    ]
    assert [c[:2] for c in calls] == [["issue", "list"], ["api", "graphql"], ["api", "graphql"]]
    # no expedite opportunity open: one list, nothing more read, and the row as before
    rows, calls = tier_3(tmp_path / "none", [], [pr(3), pr(7)])
    assert [(f.state, f.detail, f.expedite) for f in rows] == [("PRS_OPEN", "#3 #7", False)]
    assert [c[:2] for c in calls] == [["issue", "list"]]
    # no pull request: no row an expedite outcome could be in, so nothing is read
    rows, calls = tier_3(tmp_path / "empty", [opportunity_issue(5, "opportunity", "planned", "expedite")], [])
    assert rows == [] and calls == []


# -- S-070-4: walk.order -------------------------------------------------------------------


def issues(detail: str, *, expedite: bool = False) -> Finding:
    return Finding("ISSUES", "o/r", detail, True, (), TRIAGE_FIX, expedite)


def test_s070_4_an_expedite_row_comes_before_every_standard_row_of_its_tier() -> None:
    incident = Finding("INCIDENT_OPEN", "#1", "down", True)
    stalled = Finding("BOT_STALLED", "release.yml", "due", True)
    land = Finding("LAND_DUE", "#30", "t: open", True, (), LAND_FIX)
    fast_pr = Finding("PRS_OPEN", "o/r", "#3", True, ((3, HEAD),), LAND_FIX, True)
    slow_pr = Finding("PRS_OPEN", "o/r", "#7", True, ((7, HEAD),), LAND_FIX)
    unblocked = issues("UNBLOCKED #2")
    new_fast, needs_fast = issues("NEW #101", expedite=True), issues("NEEDS_PR #102", expedite=True)
    new_slow = issues("NEW #6")
    plans = Finding("PLANS", "o/r", "PLAN_DUE G-1", True, (), "intake", True)  # tier 7 keeps its order
    direction = Finding("DIRECTION_PENDING", "docs/product.md", "open", True)
    shuffled = [plans, new_slow, slow_pr, needs_fast, direction, unblocked, land, new_fast, fast_pr, stalled, incident]
    assert order(shuffled) == [
        incident,  # tiers 1 and 2 still come first
        stalled,
        fast_pr,  # tier 3: the expedite row, then LAND_DUE and PRS_OPEN as S-046-12 has them
        land,
        slow_pr,
        new_fast,  # tier 6: the expedite rows in S-046-12's order (NEW before NEEDS_PR), then the rest
        needs_fast,
        new_slow,
        unblocked,
        direction,
        plans,
    ]


def test_s070_4_the_walk_hands_the_expedite_row_of_tier_6_first() -> None:
    unblocked, fast = issues("UNBLOCKED #2"), issues("NEEDS_PR #101", expedite=True)
    source = Rows((unblocked, fast))
    walked = walk(source, Changes("sig"), Swept(NOW, (), None), Handed(), NOW, dt.timedelta(hours=24), False)
    assert (walked.item, walked.tier) == (fast, 6)
    handed = Handed().handing(fast, "s1", NOW)
    walked = walk(source, Changes("sig"), Swept(NOW, (), None), handed, NOW, dt.timedelta(hours=24), False)
    assert walked.item == unblocked


def test_s070_4_the_gate_reads_the_expedite_mark_and_its_fingerprint_is_unchanged() -> None:
    row = {"state": "ISSUES", "subject": "o/r", "detail": "NEW #5", "agent": True, "fix": TRIAGE_FIX}
    (plain,) = parse_findings(json.dumps(row))
    (fast,) = parse_findings(json.dumps(row | {"expedite": True}))
    assert (plain.expedite, fast.expedite) == (False, True)
    assert fingerprint([plain]) == fingerprint([fast])
    with pytest.raises(ReleaseError, match="expedite must be true or false"):
        parse_findings(json.dumps(row | {"expedite": "yes"}))


# -- S-070-6: triage_state.py --wip --------------------------------------------------------


def test_s070_6_wip_lists_expedite_issues_first_and_counts_them_in_progress(ts: ModuleType) -> None:
    rows = [
        {"number": 3, "state": "NEEDS_PR"},
        {"number": 9, "state": "UNBLOCKED"},
        {"number": 5, "state": "NEEDS_PR"},
        {"number": 101, "state": "IN_PROGRESS"},  # an expedite issue with an open pull request
        {"number": 102, "state": "NEEDS_PR"},
    ]
    room = ts.wip_room(rows, 2, expedite=frozenset({9, 101, 102}))
    assert room == {"wip": 2, "in_progress": 1, "room": 1, "ready": [9, 102, 3, 5]}
    # full: the expedite issues wait for a slot like any other, and the room never goes below 0
    busy = [*rows, {"number": 104, "state": "IN_PROGRESS"}, {"number": 105, "state": "AGENT_DRAFT"}]
    assert ts.wip_room(busy, 2, expedite=frozenset({101, 102}))["room"] == 0
    assert ts.wip_room(busy, 2, expedite=frozenset({101, 102}))["in_progress"] == 3
    # with no expedite outcome the order is S-046-12's, as before spec 070
    assert ts.wip_room(rows, 2)["ready"] == [3, 5, 9, 102]


def open_issue(number: int, *labels: str, parent: tuple[int, str] | None = None) -> dict[str, Any]:
    found: dict[str, Any] = {"number": number, "labels": {"nodes": [{"name": n} for n in labels]}}
    if parent is not None:
        found["parent"] = {"number": parent[0], "repository": {"nameWithOwner": parent[1]}}
    return found


def test_s070_6_the_expedite_outcomes_are_read_by_the_label_events(ts: ModuleType) -> None:
    accepted = ("opportunity", "planned")
    issues = [
        open_issue(5, *accepted, "expedite"),
        open_issue(6, *accepted, "expedite"),  # the App added it
        open_issue(7, *accepted, "expedite", "fixed-date"),  # both: standard
        open_issue(8, "opportunity", "expedite"),  # not accepted: never read
        open_issue(101, parent=(5, "O/R")),
        open_issue(102, parent=(5, "x/other")),  # a parent in another repo
        open_issue(103, parent=(6, "o/r")),
        open_issue(104),
    ]
    events = {
        "n5": [labeled("expedite", person("alice"))],
        "n6": [labeled("expedite", APP)],
        "n7": [labeled("expedite", person("alice")), labeled("fixed-date", person("alice"))],
    }
    queries: list[str] = []

    def run(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        queries.append(query)
        assert variables == {"owner": "o", "name": "r"}
        repository = {k: {"timelineItems": {"nodes": v}} for k, v in events.items()}
        return {"data": {"repository": repository}}

    outcomes = ts.expedite_outcomes("o/r", issues, BOT, run)
    assert outcomes == frozenset({5})
    assert len(queries) == 1 and "n5: issue(number: 5)" in queries[0] and "n8:" not in queries[0]
    assert ts.expedite_issues(issues, outcomes, "o/r") == frozenset({5, 101})
    # no open issue labelled opportunity, planned, and expedite: no read at all
    assert ts.expedite_outcomes("o/r", issues[4:], BOT, run) == frozenset() and len(queries) == 1
