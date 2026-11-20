"""Spec 070: an accepted opportunity's class of service, read from the `expedite` and
`fixed-date` labels a person added, and the rows of watch_state.py that wait on the
maintainer's choice: CLASS_CONFLICT, FIXED_DATE_AT_RISK, and FIXED_DATE_NO_DATE"""

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.findings import Finding
from shipmill.gate import Action, parse_findings
from shipmill.gitrepo import Git
from shipmill.status import Row, Verdict, report

from .test_gate import checkout
from .test_gate_walk import Source, cfg, tick
from .test_status_picture import URL, facts, lines
from .test_watch_gate_idle import FAKE_GH, Host

__all__ = ["checkout"]  # the fixture, imported for the tests below

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
NOW = dt.datetime(2026, 11, 19, 12, 0, tzinfo=dt.UTC)
ACCEPTED = ("opportunity", "planned")


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    spec = importlib.util.spec_from_file_location("watch_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


def person(login: str) -> dict[str, str]:
    return {"__typename": "User", "login": login}


APP = {"__typename": "Bot", "login": "shipmill-app"}


def labeled(label: str, actor: dict[str, str] | None) -> dict[str, Any]:
    """A LabeledEvent node as the GraphQL timeline prints it"""
    return {"label": {"name": label}, "actor": actor}


def node(
    labels: tuple[str, ...],
    events: list[dict[str, Any]],
    due: str | None = None,
    milestone: bool = False,
    subs: tuple[str, ...] = (),
) -> dict[str, Any]:
    """One opportunity of read_opportunities' answer"""
    return {
        "labels": {"nodes": [{"name": n} for n in (*ACCEPTED, *labels)]},
        "milestone": {"dueOn": due} if milestone or due is not None else None,
        "subIssues": {
            "pageInfo": {"hasNextPage": False},
            "nodes": [
                {"number": 100 + i, "state": s, "repository": {"nameWithOwner": "o/r"}} for i, s in enumerate(subs)
            ],
        },
        "timelineItems": {"nodes": events},
    }


def opportunities(ws: ModuleType, bot_login: str | None = None, **nodes: dict[str, Any]) -> list[Any]:
    """read_opportunities against a fake gh answering one GraphQL query with nodes (n<N>: node)"""
    ran: list[list[str]] = []

    def read(cmd: list[str]) -> str:
        ran.append(cmd)
        return json.dumps({"data": {"repository": nodes}})

    found: list[Any] = ws.read_opportunities("o/r", [int(k[1:]) for k in nodes], bot_login, read)
    assert len(ran) == 1 and ran[0][:3] == ["gh", "api", "graphql"]
    return found


def services(ws: ModuleType, found: list[Any]) -> dict[int, str]:
    return {o.number: o.service for o in found}


# -- S-070-1: a class label counts only when a person added it


def test_s070_1_an_expedite_label_a_person_added_reads_as_expedite(ws: ModuleType) -> None:
    found = opportunities(
        ws,
        "shipmill-app[bot]",
        n5=node(("expedite",), [labeled("planned", APP), labeled("expedite", person("alice"))]),
        n6=node(("expedite",), [labeled("expedite", APP)]),  # the App added it
        n7=node(("expedite",), [labeled("expedite", None)]),  # its actor can't be read (a deleted account)
        n8=node(("expedite",), []),  # no event adding it among those read
        n9=node(("expedite",), [labeled("expedite", person("shipmill-app"))]),  # the --bot-login, as a User
        # removed and added again: the newest event decides, either way
        n10=node(("expedite",), [labeled("expedite", person("alice")), labeled("expedite", APP)]),
        n11=node(("expedite",), [labeled("expedite", APP), labeled("expedite", person("alice"))]),
    )
    assert services(ws, found) == {
        5: "expedite",
        6: "standard",
        7: "standard",
        8: "standard",
        9: "standard",
        10: "standard",
        11: "expedite",
    }


def test_s070_1_a_fixed_date_label_a_person_added_reads_as_fixed_date(ws: ModuleType) -> None:
    found = opportunities(
        ws,
        n5=node(("fixed-date",), [labeled("fixed-date", person("alice"))], due="2026-12-01T08:00:00Z"),
        n6=node(("fixed-date",), [labeled("fixed-date", APP)], due="2026-12-01T08:00:00Z"),
    )
    assert services(ws, found) == {5: "fixed date", 6: "standard"}
    assert found[0].due == dt.date(2026, 12, 1)


def test_s070_1_only_accepted_opportunities_with_a_class_label_are_read(ws: ModuleType) -> None:
    def issue(number: int, *labels: str) -> Any:
        return ws.Issue(number, "t", "", NOW, "alice", labels, ())

    issues = [
        issue(1, *ACCEPTED, "expedite"),
        issue(2, *ACCEPTED),  # standard: nothing more to read
        issue(3, "opportunity", "expedite"),  # not accepted (D-10)
        issue(4, *ACCEPTED, "fixed-date"),
    ]
    assert ws.classed(issues) == [1, 4]
    assert ws.classed([issue(2, *ACCEPTED)]) == []  # service_rows reads no GraphQL then


def test_s070_1_an_answer_without_the_fields_asked_for_is_refused(ws: ModuleType) -> None:
    with pytest.raises(SystemExit, match=r"o/r#5"):
        opportunities(ws, n5={"labels": {"nodes": []}})
    many = node(("expedite",), [])
    many["subIssues"]["pageInfo"]["hasNextPage"] = True
    with pytest.raises(SystemExit, match=r"more than 100 sub-issues"):
        opportunities(ws, n5=many)


# -- S-070-2: both labels read as standard and are reported


def test_s070_2_both_labels_read_as_standard_and_report_class_conflict(ws: ModuleType) -> None:
    both = [labeled("expedite", person("alice")), labeled("fixed-date", person("alice"))]
    (found,) = opportunities(ws, n5=node(("expedite", "fixed-date"), both, due="2026-11-20T00:00:00Z"))
    assert found.service == "standard" and found.conflict
    (row,) = ws.class_rows([found], NOW)  # no FIXED_DATE_AT_RISK though it's due tomorrow: it reads as standard
    assert (row.state, row.subject) == ("CLASS_CONFLICT", "#5")
    assert row.detail == "labelled both expedite and fixed-date: reads as standard"
    assert row.fix == "remove one of `expedite` and `fixed-date` from #5"
    assert row.json()["agent"] is False and "CLASS_CONFLICT" in ws.ACTION


def test_s070_2_a_label_the_app_added_is_no_conflict(ws: ModuleType) -> None:
    events = [labeled("expedite", person("alice")), labeled("fixed-date", APP)]
    (found,) = opportunities(ws, n5=node(("expedite", "fixed-date"), events))
    assert (found.service, found.conflict) == ("expedite", False)
    assert ws.class_rows([found], NOW) == []


# -- S-070-11, S-070-12: a fixed date that will be missed, or has no date


def fixed(ws: ModuleType, number: int, due: dt.date | None, subs: int, open_subs: int, milestone: bool = True) -> Any:
    return ws.Opportunity(number, frozenset({"fixed-date"}), milestone, due, subs, open_subs)


def test_s070_11_a_fixed_date_due_in_2_days_or_past_with_work_open_is_at_risk(ws: ModuleType) -> None:
    today = NOW.date()
    at_risk = [
        fixed(ws, 1, today + dt.timedelta(days=2), 3, 2),  # 2 days away
        fixed(ws, 2, today, 1, 1),
        fixed(ws, 3, today - dt.timedelta(days=4), 2, 1),  # past
        fixed(ws, 4, today + dt.timedelta(days=1), 0, 0),  # no sub-issue at all
    ]
    rows = ws.class_rows(at_risk, NOW)
    assert [(r.state, r.subject, r.detail) for r in rows] == [
        ("FIXED_DATE_AT_RISK", "#1", "due 2026-11-21, 2 build issues open"),
        ("FIXED_DATE_AT_RISK", "#2", "due 2026-11-19, 1 build issues open"),
        ("FIXED_DATE_AT_RISK", "#3", "due 2026-11-15, 1 build issues open"),
        ("FIXED_DATE_AT_RISK", "#4", "due 2026-11-20, 0 build issues open"),
    ]
    assert rows[0].fix == "expedite #1 or move its milestone's due date"
    assert all(r.json()["agent"] is False for r in rows) and "FIXED_DATE_AT_RISK" in ws.ACTION


def test_s070_11_a_fixed_date_further_away_or_with_every_sub_issue_closed_is_not(ws: ModuleType) -> None:
    today = NOW.date()
    safe = [
        fixed(ws, 1, today + dt.timedelta(days=3), 2, 2),  # more than 2 days away
        fixed(ws, 2, today, 2, 0),  # every sub-issue closed
        fixed(ws, 3, today - dt.timedelta(days=1), 1, 0),
    ]
    assert ws.class_rows(safe, NOW) == []


def test_s070_11_the_due_date_and_open_sub_issues_are_read_from_github(ws: ModuleType) -> None:
    events = [labeled("fixed-date", person("alice"))]
    (found,) = opportunities(
        ws, n5=node(("fixed-date",), events, due="2026-11-21T07:00:00Z", subs=("OPEN", "CLOSED", "OPEN"))
    )
    assert (found.due, found.subs, found.open_subs) == (dt.date(2026, 11, 21), 3, 2)
    (row,) = ws.class_rows([found], NOW)
    assert row.text().startswith("FIXED_DATE_AT_RISK #5")
    assert row.detail == "due 2026-11-21, 2 build issues open"


def test_s070_12_a_fixed_date_in_no_milestone_or_one_without_a_due_date_has_no_date(ws: ModuleType) -> None:
    events = [labeled("fixed-date", person("alice"))]
    found = opportunities(
        ws,
        n5=node(("fixed-date",), events),  # in no milestone
        n6=node(("fixed-date",), events, milestone=True),  # a milestone without a due date
    )
    rows = ws.class_rows(found, NOW)
    assert [(r.state, r.subject, r.detail, r.fix) for r in rows] == [
        ("FIXED_DATE_NO_DATE", "#5", "it is in no milestone", "set the due date of #5's milestone"),
        ("FIXED_DATE_NO_DATE", "#6", "its milestone has no due date", "set the due date of #6's milestone"),
    ]
    assert "FIXED_DATE_NO_DATE" in ws.ACTION and "FIXED_DATE_NO_DATE" not in ws.AGENT


def test_s070_12_an_expedite_or_standard_opportunity_needs_no_date(ws: ModuleType) -> None:
    expedite = ws.Opportunity(5, frozenset({"expedite"}), False, None, 0, 0)
    standard = ws.Opportunity(6, frozenset(), False, None, 0, 0)
    assert ws.class_rows([expedite, standard], NOW) == []


# -- S-070-13: they wait on the maintainer in shipmill status, and the gate hands none


def class_rows(ws: ModuleType) -> list[Any]:
    found = [
        ws.Opportunity(21, frozenset({"expedite", "fixed-date"}), True, None, 0, 0),
        ws.Opportunity(22, frozenset({"fixed-date"}), True, NOW.date(), 1, 1),
        ws.Opportunity(23, frozenset({"fixed-date"}), False, None, 0, 0),
    ]
    rows: list[Any] = ws.class_rows(found, NOW)
    assert [r.state for r in rows] == ["CLASS_CONFLICT", "FIXED_DATE_AT_RISK", "FIXED_DATE_NO_DATE"]
    return rows


def test_s070_13_the_class_rows_wait_on_the_maintainer_in_shipmill_status(ws: ModuleType) -> None:
    rows = [Row(r.state, r.subject, r.detail, r.json()["agent"], r.fix) for r in class_rows(ws)]
    found = report(facts(*rows))
    assert found.verdict is Verdict.WAITS
    assert [(r.text, r.fix) for r in found.reasons] == [(r.text(), r.fix) for r in rows]
    text = lines(facts(*rows))
    assert text[0].endswith(": WAITS ON YOU")
    assert (
        f"  class          CLASS_CONFLICT #21 {URL}/issues/21: labelled both expedite and fixed-date: reads as standard"
        in text
    )
    assert "                 fix: remove one of `expedite` and `fixed-date` from #21" in text
    assert f"                 FIXED_DATE_NO_DATE #23 {URL}/issues/23: it is in no milestone" in text
    assert not any(line.startswith("  other") for line in text)


def test_s070_13_a_gate_tick_with_only_the_class_rows_launches_no_session(ws: ModuleType, checkout: Git) -> None:
    printed = "\n".join(json.dumps(r.json(), sort_keys=True) for r in class_rows(ws))
    findings: list[Finding] = parse_findings(printed)
    assert findings and not any(f.agent for f in findings)
    # no --tier prints them, so a walk never meets one; even met in every tier, none is an item
    assert not any(f.state in kinds for kinds in ws.TIERS.values() for f in findings)
    source = Source({n: list(findings) for n in (1, 2, 3, 4, 6)}, swept=list(findings))
    decision = tick(checkout, source, agents=cfg())
    assert (decision.action, decision.work) == (Action.QUIET, ())


# -- #1377: only a read that prints the class rows reads the accepted opportunities

# test_watch_gate_idle's fake gh for the full report, each call logged to FAKE_LOG, and with
# [agents] the direction issues' read answered (none, as --jq '.[]' prints them)
LOGGING_GH = """#!{python}
import json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["api", "--paginate"] and "labels=shipmill-direction" in args[2]:
    sys.exit(0)
sys.exit(subprocess.run([sys.executable, os.environ["FAKE_GH"], *args]).returncode)
"""


def class_reads(host: Host, *flags: str) -> int:
    """How many `gh issue list --label opportunity --label planned` reads one run made"""
    log = host.tmp / "gh.log"
    log.write_text("", encoding="utf-8")
    proc = host.watch(*flags)
    assert proc.returncode in (0, 1), proc.stderr
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert calls  # the fake gh logged the run's reads
    return sum(1 for c in calls if c[:2] == ["issue", "list"] and "opportunity" in c and "planned" in c)


def test_1377_only_the_reads_with_the_host_rows_read_the_classes(ws: ModuleType, tmp_path: Path) -> None:
    host = Host(tmp_path)
    fakes = host.tmp / "fakes"
    (fakes / "gh-full").write_text(FAKE_GH.replace("{python}", sys.executable), encoding="utf-8")
    (fakes / "gh").write_text(LOGGING_GH.replace("{python}", sys.executable), encoding="utf-8")
    host.env |= {"FAKE_LOG": str(host.tmp / "gh.log"), "FAKE_GH": str(fakes / "gh-full")}
    config = 'mode = "off"\n\n[agents]\nprompt = "/triage {repo}"\n'
    (host.work / ".github" / "shipmill.toml").write_text(config, encoding="utf-8")
    known = host.tmp / "known.json"
    empty = {"default_branch": "main", "held": False, "prs": [], "incidents": [], "runs": []}
    known.write_text(json.dumps(empty), encoding="utf-8")
    # the full report and shipmill status's --no-host print the class rows: one read each
    assert class_reads(host) == 1
    assert class_reads(host, "--no-host") == 1
    # the sweep and tiers 5 and 7 keep none of them (S-070-13), so they read none
    kept = {s for n in (5, 7) for s in ws.TIERS[n]} | set(ws.SWEPT)
    assert not set(ws.CLASS_STATES) & kept
    assert class_reads(host, "--sweep") == 0
    for n in (5, 7):
        assert class_reads(host, "--tier", str(n), "--known", str(known)) == 0, n
