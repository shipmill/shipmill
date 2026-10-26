"""Spec 030's veto as triage_state.py and watch_state.py read it (S-030-14 to S-030-16)"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.autonomy import Autonomy
from shipmill.gate import Action, decide, parse_findings

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
REPO = ("o", "r")
BOT = "shipmill-o[bot]"
NOW = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.UTC)
DAY = dt.timedelta(hours=24)
DECIDED = (
    "<!-- shipmill:decided zone=triage-verdict until=2026-10-21T10:00:00Z -->\n"
    "@amy Decided without waiting: close this as a duplicate of #3"
)
HANDLED = "<!-- shipmill:veto-handled zone=triage-verdict -->\nReopened it, as the veto asks"
VETO = "Veto: keep it open, it is not a duplicate"


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load("vetoed_triage_state", SKILLS / "github-issue-triage" / "scripts" / "triage_state.py")


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("vetoed_watch_state", SKILLS / "github-ship-watch" / "scripts" / "watch_state.py")


def author(login: str) -> dict[str, str]:
    """GraphQL's author: a Bot's login comes without "[bot]" """
    if login.endswith("[bot]"):
        return {"__typename": "Bot", "login": login.removesuffix("[bot]")}
    return {"__typename": "User", "login": login}


def comment(body: str, by: str = "amy", association: str = "COLLABORATOR") -> dict[str, Any]:
    return {"body": body, "createdAt": "2026-10-20T10:00:00Z", "author": author(by), "authorAssociation": association}


def decided() -> dict[str, Any]:
    """The bot's decided marker, as the App posts it (GraphQL gives it no trusted association)"""
    return comment(DECIDED, by=BOT, association="NONE")


def issue(*comments: dict[str, Any], labels: tuple[str, ...] = ("decided",)) -> dict[str, Any]:
    """An open issue the bot triaged as one to implement, comments oldest first"""
    return {
        "number": 7,
        "title": "t",
        "body": "",
        "author": author("amy"),
        "authorAssociation": "OWNER",
        "labels": {"nodes": [{"name": n} for n in labels]},
        "comments": {"nodes": [comment("Triage: implement", by=BOT, association="NONE"), *comments]},
        "timelineItems": {"nodes": []},
    }


def state(ts: ModuleType, item: dict[str, Any], bot_login: str | None = BOT) -> tuple[str, str]:
    """As triage_state.py's main reads an open issue"""
    found: tuple[str, str] = ts.gated(item, bot_login, False) or ts.classify_open(
        item, "Triage:", "postponed", {}, None, REPO, bot_login
    )
    return found


# -- S-030-14: an open issue


def test_s030_14_a_collaborators_veto_after_the_bots_decided_marker_reads_vetoed(ts: ModuleType) -> None:
    assert state(ts, issue(decided(), comment(VETO))) == ("VETOED", "vetoed by @amy")
    assert "VETOED" in ts.ACTION  # an action: the script exits 1
    # the first word in any case, from an OWNER or MEMBER too
    for body, association in (("veto, see the thread", "OWNER"), ("VETO", "MEMBER"), ("\n\nVeto.", "COLLABORATOR")):
        assert state(ts, issue(decided(), comment(body, association=association)))[0] == "VETOED", body


def test_s030_14_a_contributors_veto_or_a_veto_mid_comment_leaves_the_usual_state(ts: ModuleType) -> None:
    assert state(ts, issue(decided())) == ("NEEDS_PR", "")
    assert state(ts, issue(decided(), comment("veto", by="eve", association="CONTRIBUTOR")))[0] == "NEEDS_PR"
    assert state(ts, issue(decided(), comment("I would veto this one", association="OWNER")))[0] == "NEEDS_PR"
    assert state(ts, issue(decided(), comment("vetoes are rare", association="OWNER")))[0] == "NEEDS_PR"
    # nor does the bot veto its own decision
    assert state(ts, issue(decided(), comment("Veto", by=BOT, association="MEMBER")))[0] == "NEEDS_PR"


def test_s030_14_a_newer_veto_handled_comment_by_the_bot_answers_the_veto(ts: ModuleType) -> None:
    handled = comment(HANDLED, by=BOT, association="NONE")
    assert state(ts, issue(decided(), comment(VETO), handled))[0] == "NEEDS_PR"
    # an outsider's veto-handled marker answers nothing, and a veto after the handled one counts again
    outsider = comment(HANDLED, by="eve", association="NONE")
    assert state(ts, issue(decided(), comment(VETO), outsider))[0] == "VETOED"
    assert state(ts, issue(decided(), comment(VETO), handled, comment("Veto again")))[0] == "VETOED"


def test_s030_14_a_veto_counts_only_after_a_trusted_decided_marker_on_a_labelled_issue(ts: ModuleType) -> None:
    assert state(ts, issue(comment(VETO), decided()))[0] == "NEEDS_PR"  # before the decision
    outsider = comment(DECIDED, by="eve", association="NONE")
    assert state(ts, issue(outsider, comment(VETO)))[0] == "NEEDS_PR"
    assert state(ts, issue(decided(), comment(VETO), labels=()))[0] == "NEEDS_PR"  # no decided label
    # a quoted marker is no marker: only a comment's first line is
    quoted = comment(f"About this:\n{DECIDED}", by=BOT, association="NONE")
    assert state(ts, issue(quoted, comment(VETO)))[0] == "NEEDS_PR"
    # without --bot-login, a trusted author's marker is the decision
    assert state(ts, issue(comment(DECIDED, association="MEMBER"), comment(VETO)), None)[0] == "VETOED"


def test_s030_14_vetoed_is_read_right_after_decided_and_before_any_other_state(ts: ModuleType) -> None:
    question = comment("<!-- shipmill:needs-decision -->\n@amy Decision needed: which?", by=BOT, association="NONE")
    both = ("needs-decision", "decided")
    # a session that took the veto up as a question: the question waits, then its answer is DECIDED
    assert state(ts, issue(decided(), comment(VETO), question, labels=both))[0] == "NEEDS_DECISION"
    assert state(ts, issue(decided(), comment(VETO), question, comment("1"), labels=both))[0] == "DECIDED"
    # a veto naming an open issue is no hold, and a postponed or blocked issue still reads VETOED
    held = issue(decided(), comment("Veto: this waits on o/r#40"), labels=("decided", "postponed", "blocked"))
    assert state(ts, held)[0] == "VETOED"
    # an upstream report still waits outside, and an untrusted author's issue stays UNTRUSTED
    assert state(ts, issue(decided(), comment(VETO), labels=("decided", "upstream")))[0] == "UPSTREAM"
    outsiders = issue(decided(), comment(VETO))
    outsiders["author"], outsiders["authorAssociation"] = author("eve"), "NONE"
    assert ts.gated(outsiders, BOT, True)[0] == "UNTRUSTED"


# -- S-030-15: a closed issue


def closed(number: int, *comments: dict[str, Any]) -> dict[str, Any]:
    """A closed issue labelled decided, as the first query's vetoable connection returns it"""
    return {"number": number, "title": f"issue {number}", "comments": {"nodes": list(comments)}}


def recent(number: int) -> dict[str, Any]:
    """One of the --closed most recently updated closed issues: closed by hand, no merged PR"""
    return {
        "number": number,
        "title": f"issue {number}",
        "stateReason": "COMPLETED",
        "body": "",
        "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": "decided"}]},
        "comments": {"nodes": []},
        "refs": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []},
        "timelineItems": {"nodes": [{"createdAt": "2026-10-20T09:00:00Z", "actor": None, "closer": None}]},
    }


def test_s030_15_a_closed_decided_issue_reads_vetoed_with_an_unanswered_trusted_veto(ts: ModuleType) -> None:
    data = {
        "vetoable": {"nodes": [closed(9, decided(), comment(VETO)), closed(8, decided())]},
        "closed": {"nodes": [recent(9), recent(8)]},
    }
    rows = ts.closed_rows(data, 20, "release-blocker", "incident", BOT)
    # #9 reads VETOED and nothing else; #8, with no veto, reads only what any closed issue reads
    assert rows == [
        {"number": 9, "state": "VETOED", "title": "issue 9", "note": "closed, vetoed by @amy", "closed": True},
        {"number": 8, "state": "SUSPECT_CLOSE", "title": "issue 8", "note": rows[1]["note"]},
    ]


def test_s030_15_a_closed_decided_issue_reports_nothing_without_an_unanswered_trusted_veto(ts: ModuleType) -> None:
    handled = comment(HANDLED, by=BOT, association="NONE")
    for comments in (
        (decided(),),
        (decided(), comment("veto", by="eve", association="CONTRIBUTOR")),
        (decided(), comment(VETO), handled),
    ):
        data = {"vetoable": {"nodes": [closed(9, *comments)]}, "closed": {"nodes": []}}
        assert ts.closed_rows(data, 20, "release-blocker", "incident", BOT) == []


class Recorder:
    """A fake GraphQL runner: the first query, with a second page of closed decided issues"""

    def __init__(self, ts: ModuleType) -> None:
        self.ts = ts
        self.calls: list[tuple[str, dict[str, str | int]]] = []

    def __call__(self, query: str, variables: dict[str, str | int]) -> dict[str, Any]:
        self.calls.append((query, variables))
        empty: dict[str, Any] = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}
        if query == self.ts.VETOABLE_PAGE:
            page = {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [closed(5, decided(), comment(VETO))],
            }
            return {"data": {"repository": {"vetoable": page}}}
        first = {"pageInfo": {"hasNextPage": True, "endCursor": "v1"}, "nodes": [closed(9, decided())]}
        tags = {"pageInfo": {"hasPreviousPage": False, "startCursor": None}, "nodes": []}
        return {"data": {"repository": {"open": empty, "tags": tags, "closed": {"nodes": []}, "vetoable": first}}}


def test_s030_15_the_closed_decided_issues_of_the_last_14_days_come_with_the_first_query(ts: ModuleType) -> None:
    gh = Recorder(ts)
    data = ts.fetch("o/r", 20, run=gh, now=NOW)
    first, page = gh.calls
    assert first[0] == ts.QUERY and first[1]["since"] == "2026-10-11T12:00:00Z"
    assert 'labels: ["decided"]' in ts.QUERY and "filterBy: {since: $since}" in ts.QUERY
    assert "states: CLOSED" in ts.QUERY.split("vetoable:")[1]
    assert page[0] == ts.VETOABLE_PAGE and page[1]["cursor"] == "v1" and page[1]["since"] == "2026-10-11T12:00:00Z"
    assert [i["number"] for i in data["vetoable"]["nodes"]] == [9, 5]
    rows = ts.closed_rows(data, 20, "release-blocker", "incident", BOT)
    assert [(r["number"], r["state"]) for r in rows] == [(5, "VETOED")]


# -- S-030-16: watch_state.py's VETOED row


def pr(number: int, *, labels: tuple[str, ...] = (), fork: bool = False) -> dict[str, Any]:
    """One `gh pr list --json number,isDraft,isCrossRepository,labels,headRefOid` row"""
    found = {"number": number, "isDraft": False, "isCrossRepository": fork, "labels": [{"name": n} for n in labels]}
    return {**found, "headRefOid": f"{number:040x}"}


def triage(*rows: dict[str, Any]) -> str:
    return "\n".join(json.dumps({"title": "t", "note": "", **r}) for r in rows)


Comments = list[tuple[str, str, str]]
DECIDED_PR: Comments = [(BOT, "NONE", DECIDED)]
VETOED_PR: Comments = [*DECIDED_PR, ("amy", "COLLABORATOR", VETO)]


def comments(by_pr: dict[int, Comments]) -> Any:
    """A fake for the comments of a pull request; it fails on one the test didn't expect read"""

    def read(number: int) -> Comments:
        if number not in by_pr:
            raise AssertionError(f"read the comments of #{number}")
        return by_pr[number]

    return read


def test_s030_16_vetoed_issues_and_pull_requests_open_closed_or_merged_share_a_work_row(ws: ModuleType) -> None:
    lines = triage(
        {"number": 7, "state": "VETOED"},
        {"number": 9, "state": "VETOED", "closed": True},
        {"number": 12, "state": "NEW"},
    )
    open_prs = [pr(3, labels=("decided",)), pr(4)]
    closed_prs = [{"number": 5, "isCrossRepository": False}, {"number": 6, "isCrossRepository": False}]
    read = comments({3: VETOED_PR, 5: VETOED_PR, 6: VETOED_PR})  # #5 closed, #6 merged: gh lists both
    found = {r.state: r.json() for r in ws.intake("o/r", 1, lines, open_prs, read, BOT, closed_prs=closed_prs)}
    assert found["VETOED"] == {
        "state": "VETOED",
        "subject": "o/r",
        "detail": "#3 #5 #6 #7 #9",
        "agent": True,
        "fix": "take up each veto (needs-decision.md): /shipmill:github-issue-triage o/r",
    }
    assert found["ISSUES"]["detail"] == "NEW #12"  # a vetoed issue is in no other row
    assert found["PRS_OPEN"]["detail"] == "#4"
    assert "VETOED" in ws.ACTION and "VETOED" in ws.AGENT
    # the gate starts a session for it alone
    only = ws.intake("o/r", 1, triage({"number": 7, "state": "VETOED"}), [], comments({}), BOT)
    text = "\n".join(json.dumps(r.json(), sort_keys=True) for r in only)
    assert decide(parse_findings(text), [], None, NOW, DAY).action is Action.LAUNCH
    # a closed vetoed issue starts no chain walk; an open one does
    assert ws.chain_starts("o/r", lines) == ["o/r#7", "o/r#12"]


def test_s030_16_an_item_labelled_decided_without_a_veto_is_in_no_work_row(ws: ModuleType) -> None:
    lines = triage({"number": 7, "state": "TRIAGED"})  # triage_state.py reads it as it would unlabelled
    open_prs = [pr(3, labels=("decided",))]
    closed_prs = [{"number": 5, "isCrossRepository": False}]
    handled: Comments = [*VETOED_PR, (BOT, "NONE", HANDLED)]
    outsider: Comments = [*DECIDED_PR, ("eve", "CONTRIBUTOR", "veto")]
    for history in (DECIDED_PR, handled, outsider):
        read = comments({3: history, 5: history})
        found = ws.intake("o/r", 0, lines, open_prs, read, BOT, closed_prs=closed_prs)
        # the rows are what they are without the label: a notify pull request still lands when ready
        plain = ws.intake("o/r", 0, lines, [pr(3)], comments({}), BOT)
        assert [r.json() for r in found] == [r.json() for r in plain]
        assert not [r for r in found if r.json()["agent"]]
        text = "\n".join(json.dumps(r.json(), sort_keys=True) for r in found)
        # land observe: the open pull request alone, not a veto, would be work (S-040-9)
        assert decide(parse_findings(text), [], None, NOW, DAY, Autonomy.OBSERVE).action is Action.QUIET


def test_s030_16_a_forks_closed_pull_request_starts_no_unattended_session(ws: ModuleType) -> None:
    closed_prs = [{"number": 5, "isCrossRepository": True}]
    assert ws.intake("o/r", 0, "", [], comments({}), BOT, True, closed_prs=closed_prs) == []
    found = ws.intake("o/r", 0, "", [], comments({5: VETOED_PR}), BOT, closed_prs=closed_prs)
    assert [(r.state, r.detail) for r in found] == [("VETOED", "#5")]


def test_s030_16_the_closed_pull_requests_read_are_the_decided_ones_of_the_last_14_days(ws: ModuleType) -> None:
    assert ws.decided_prs_command("o/r", NOW) == [
        "gh",
        "pr",
        "list",
        "-R",
        "o/r",
        "--state",
        "closed",
        "--label",
        "decided",
        "--search",
        "updated:>=2026-10-11",
        "--json",
        "number,isCrossRepository",
        "-L",
        "1000",
    ]
