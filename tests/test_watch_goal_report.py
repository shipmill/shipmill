"""Spec 110: the watch reads intake_state.py's `goal-report` lines into the full report's GOALS
row and the DIRECTION_DUE action, deduplicated by a trusted `Direction:` issue, and the gate's
walk places DIRECTION_DUE in tier 7 right after PLANS; without gh or the network"""

import datetime as dt
import json
from types import ModuleType
from typing import Any

import pytest

from shipmill import walk as gate_walk
from shipmill.findings import Finding
from shipmill.gate import Action, decide, parse_findings, state_dir
from shipmill.gitrepo import Git
from shipmill.walk import SWEEP, Swept

from .test_gate_walk import NOW, PLANS, Source, cfg, checkout, tick
from .test_status_plan_waits import BOT, INTAKE_STATE, intake_lines, load
from .test_watch_plans import WATCH_STATE

__all__ = ["checkout"]  # the fixture, imported for the gate's test below

REPO = "o/r"
WATCH_FIX = "/shipmill:github-ship-watch o/r"


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load(WATCH_STATE, "watch_state_goal_report")


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    return load(INTAKE_STATE, "intake_state_goal_report")


def report(
    ist: ModuleType,
    goal: str,
    status: str,
    *,
    kind: str | None = None,
    value: str | None = None,
    met: int = 0,
    stalled: bool = False,
    unserved: int = 0,
    ended: str | None = None,
) -> str:
    """intake_state.py's own goal-report line for a goal (S-110-1)"""
    reading = ist.GoalReport(status, stalled, value, met, unserved)
    return json.dumps(ist.goal_report_json(ist.Goal(goal, "SECRET goal", kind, ended), reading))


def state(goal: str, name: str) -> str:
    """intake_state.py's goal-state line for a goal of kind goal (spec 106)"""
    row = {"kind": "goal-state", "goal": goal, "number": None, "state": name, "title": "SECRET", "note": "n"}
    return json.dumps(row | {"holder": "agent" if name == "GOAL_WRITTEN" else None, "by": None})


def spec_lines(ist: ModuleType) -> str:
    """The spec's example: G-1 a measure met 4 weeks, G-2 a goal not met, G-3 a goal written
    with no measure, G-5 no kind, G-6 a goal planned and stalled"""
    return intake_lines(
        state("G-2", "GOAL_WRITTEN"),
        state("G-3", "GOAL_WRITTEN"),
        state("G-6", "GOAL_PLANNED"),
        report(ist, "G-1", "met", kind="measure", value="p90 1.2 d", met=4),
        report(ist, "G-2", "not met", kind="goal", value="7%"),
        report(ist, "G-3", "no measure", kind="goal"),
        report(ist, "G-5", "no measure"),
        report(ist, "G-6", "no measure", kind="goal", stalled=True, unserved=3),
    )


class Search:
    """gh api search/issues' --jq lines for the Direction issues, each call logged"""

    def __init__(self, *issues: dict[str, Any]) -> None:
        self.issues = issues
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> str:
        self.calls.append(cmd)
        return "".join(json.dumps(i) + "\n" for i in self.issues)


def issue(
    title: str, state: str = "open", reason: str | None = None, *, by: str = "OWNER", login: str = "amy"
) -> dict[str, Any]:
    return {"title": title, "state": state, "state_reason": reason, "author_association": by, "login": login}


# -- S-110-3: the GOALS row -------------------------------------------------------------------


def test_s110_3_goals_lists_each_goal_in_the_directions_order(ws: ModuleType, ist: ModuleType) -> None:
    (row,) = ws.goals_row(spec_lines(ist), REPO)
    assert (row.state, row.subject) == ("GOALS", REPO)
    assert row.detail == (
        "G-1 met (p90 1.2 d), 4 weeks; G-2 not met (7%), written; G-3 no measure, written; G-5 no measure;"
        " G-6 no measure, planned, stalled 3 weeks"
    )
    assert "SECRET" not in row.detail  # ids, statuses, and metrics.py's value text only (D-16)


def test_s110_3_a_goal_of_kind_goal_shows_its_spec_106_state(ws: ModuleType, ist: ModuleType) -> None:
    for name, shown in [("GOAL_OVERDUE", "overdue"), ("GOAL_MET", "met"), ("GOAL_DROPPED", "dropped")]:
        text = intake_lines(state("G-4", name), report(ist, "G-4", "no data", kind="goal", value="no data"))
        assert [r.detail for r in ws.goals_row(text, REPO)] == [f"G-4 no data (no data), {shown}"]
    # spec 106 gives every goal of kind goal its row in the same run: none is refused
    with pytest.raises(ws.Refused, match="no goal-state row for G-4"):
        ws.goals_row(intake_lines(report(ist, "G-4", "no measure", kind="goal")), REPO)


def test_s110_3_no_goal_report_line_gives_no_goals_row(ws: ModuleType) -> None:
    # without docs/product.md intake_state.py runs without --plans and prints no goal-report line
    assert ws.goals_row(intake_lines(), REPO) == []
    assert ws.measure_rows(intake_lines(), REPO, BOT, True, read=Search()) == []


def test_s110_3_the_lines_are_intake_states_own(ws: ModuleType, ist: ModuleType) -> None:
    line = json.loads(report(ist, "G-1", "met", kind="measure", value="p90 1.2 d", met=4))
    assert set(line) == ws.GOAL_REPORT_KEYS
    assert set(ist.REPORT_STATUSES) == ws.GOAL_REPORT_STATUSES


# -- S-110-4: report-only, in the full report alone -------------------------------------------


def test_s110_4_goals_adds_nothing_to_the_exit_code_and_is_no_agents(ws: ModuleType, ist: ModuleType) -> None:
    (row,) = ws.goals_row(spec_lines(ist), REPO)
    assert not row.action and row.json()["agent"] is False and row.fix is None
    assert "GOALS" not in ws.ACTION | ws.AGENT | ws.FIXED
    assert all("GOALS" not in states for states in ws.TIERS.values()) and "GOALS" not in ws.SWEPT
    assert "GOALS" not in gate_walk.SWEPT and all("GOALS" not in kinds for kinds in gate_walk.TIERS.values())
    findings = parse_findings(json.dumps(row.json(), sort_keys=True))
    assert decide(findings, [], None, NOW, dt.timedelta(hours=6)).action is Action.QUIET


def test_s110_4_a_tier_or_sweep_read_prints_no_goals_row(ws: ModuleType, ist: ModuleType) -> None:
    text = spec_lines(ist)
    full = [r.state for r in ws.measure_rows(text, REPO, BOT, True, read=Search())]
    swept = [r.state for r in ws.measure_rows(text, REPO, BOT, False, read=Search())]
    assert full == ["GOALS", "DIRECTION_DUE"] and swept == ["DIRECTION_DUE"]


# -- S-110-5: a goal-report line intake could not have printed --------------------------------


GOOD = {
    "kind": "goal-report",
    "goal": "G-1",
    "goal_kind": None,
    "status": "met",
    "value_text": "7%",
    "met_weeks": 1,
    "stalled": False,
    "weeks_unserved": 0,
    "ended": None,
}


@pytest.mark.parametrize(
    "bad",
    [
        {"status": "almost met"},
        {"status": None},
        {"goal": "G-0"},
        {"goal": "g-1"},
        {"goal": "#3"},
        {"met_weeks": -1},
        {"met_weeks": "4"},
        {"met_weeks": True},
        {"met_weeks": 1.5},
        {"weeks_unserved": -2},
        {"weeks_unserved": None},
        {"goal_kind": "wish"},
        {"stalled": "yes"},
        {"ended": "done"},
    ],
)
def test_s110_5_a_malformed_goal_report_line_stops_the_watch(ws: ModuleType, bad: dict[str, Any]) -> None:
    line = json.dumps(GOOD | bad)
    for host in (True, False):  # the full report, and a --tier or --sweep read
        with pytest.raises(ws.Refused, match="malformed goal-report line") as refused:
            ws.measure_rows(intake_lines(line), REPO, BOT, host, read=Search())
        assert line[:60] in str(refused.value)  # it names the line


@pytest.mark.parametrize("key", sorted(GOOD))
def test_s110_5_a_goal_report_line_missing_a_key_stops_the_watch(ws: ModuleType, key: str) -> None:
    if key == "kind":
        assert ws.goals_row(intake_lines(json.dumps({k: v for k, v in GOOD.items() if k != key})), REPO) == []
        return  # without its kind the line is no goal-report line
    line = json.dumps({k: v for k, v in GOOD.items() if k != key})
    with pytest.raises(ws.Refused, match="malformed goal-report line"):
        ws.goals_row(intake_lines(line), REPO)


def test_s110_5_a_well_formed_line_reads(ws: ModuleType) -> None:
    assert [r.detail for r in ws.goals_row(intake_lines(json.dumps(GOOD)), REPO)] == ["G-1 met (7%), 1 weeks"]


# -- S-110-6: which goals are due --------------------------------------------------------------


def test_s110_6_a_met_and_a_stalled_goal_are_due(ws: ModuleType, ist: ModuleType) -> None:
    (row,) = ws.direction_due_rows(spec_lines(ist), REPO, BOT, read=Search())
    assert (row.state, row.subject) == ("DIRECTION_DUE", REPO)
    assert row.detail == "G-1 met for 4 weeks; G-6 stalled for 3 weeks"
    assert row.action and row.json()["agent"] is True and row.fix == WATCH_FIX
    assert "DIRECTION_DUE" in ws.ACTION & ws.AGENT


def test_s110_6_who_is_never_due(ws: ModuleType, ist: ModuleType) -> None:
    text = intake_lines(
        report(ist, "G-1", "met", kind="measure", value="1", met=3),  # not yet 4 weeks
        report(ist, "G-2", "no measure", kind="measure", stalled=True, unserved=5),  # a standing measure
        report(ist, "G-3", "met", value="1", met=4, ended="met"),  # the direction marks it met
        report(ist, "G-4", "no measure", stalled=True, unserved=3, ended="dropped"),
        report(ist, "G-5", "no measure", met=4),  # no measure line: never due as met
    )
    search = Search()
    assert ws.direction_due_rows(text, REPO, BOT, read=search) == []
    assert search.calls == []  # S-110-7: no goal due, no read


def test_s110_6_a_goal_met_and_stalled_is_listed_once_as_met(ws: ModuleType, ist: ModuleType) -> None:
    text = intake_lines(
        report(ist, "G-2", "not met", value="1", met=4, stalled=True, unserved=3),
        report(ist, "G-7", "no data", value="no data", met=4, stalled=True, unserved=4),
        report(ist, "G-8", "no measure", stalled=True, unserved=6),  # no kind: due as stalled
    )
    (row,) = ws.direction_due_rows(text, REPO, BOT, read=Search())
    assert row.detail == "G-2 met for 4 weeks; G-7 met for 4 weeks; G-8 stalled for 3 weeks"


# -- S-110-7: a proposal already open or declined ----------------------------------------------


def test_s110_7_a_trusted_open_or_declined_proposal_leaves_the_row(ws: ModuleType, ist: ModuleType) -> None:
    search = Search(
        issue("Direction: G-1 met for 4 weeks"),  # open, by an OWNER
        # the App's decline, in another case and punctuation
        issue("direction: g-6 STALLED for 3 weeks.", "closed", "not_planned", by="NONE", login=BOT),
    )
    assert ws.direction_due_rows(spec_lines(ist), REPO, BOT, read=search) == []
    (cmd,) = search.calls  # one search, of the Direction titles
    assert cmd[:5] == ["gh", "api", "-X", "GET", "search/issues"]
    assert f"q=repo:{REPO} is:issue {ws.DIRECTION_SEARCH}" in cmd
    for association in ("MEMBER", "COLLABORATOR"):
        found = Search(issue("Direction: G-1 met for 4 weeks", by=association))
        assert [r.detail for r in ws.direction_due_rows(spec_lines(ist), REPO, BOT, read=found)] == [
            "G-6 stalled for 3 weeks"
        ]
    # either of a goal's two titles holds it: a stalled proposal still open keeps the met goal out
    either = Search(issue("Direction: G-1 stalled for 3 weeks"))
    assert [r.detail for r in ws.direction_due_rows(spec_lines(ist), REPO, BOT, read=either)] == [
        "G-6 stalled for 3 weeks"
    ]


def test_s110_7_an_outsiders_or_completed_proposal_leaves_the_goal_due(ws: ModuleType, ist: ModuleType) -> None:
    search = Search(
        issue("Direction: G-1 met for 4 weeks", by="NONE", login="drive-by"),  # D-16: an outsider's
        issue("Direction: G-1 met for 4 weeks", by="CONTRIBUTOR", login="someone"),
        issue("Direction: G-6 stalled for 3 weeks", "closed", "completed"),  # acted on: proposed again
        issue("Direction: G-6 stalled for 3 weeks", "closed", "not_planned", by="NONE", login="drive-by"),
        issue("Direction: G-16 stalled for 3 weeks"),  # another goal's
        issue("Direction: G-1 met for 5 weeks"),  # another threshold's title
    )
    (row,) = ws.direction_due_rows(spec_lines(ist), REPO, BOT, read=search)
    assert row.detail == "G-1 met for 4 weeks; G-6 stalled for 3 weeks"
    # without --bot-login the App's own issue counts only by its association
    bots = Search(issue("Direction: G-1 met for 4 weeks", by="NONE", login=BOT))
    assert [r.detail for r in ws.direction_due_rows(spec_lines(ist), REPO, None, read=bots)] == [
        "G-1 met for 4 weeks; G-6 stalled for 3 weeks"
    ]


def test_s110_7_an_unreadable_search_line_stops_the_watch(ws: ModuleType, ist: ModuleType) -> None:
    with pytest.raises(ws.Refused, match="not JSON"):
        ws.direction_due_rows(spec_lines(ist), REPO, BOT, read=lambda cmd: "oops\n")
    with pytest.raises(ws.Refused, match="not an issue"):
        ws.direction_due_rows(spec_lines(ist), REPO, BOT, read=lambda cmd: '{"title": 3}\n')


# -- S-110-8: tier 7 right after PLANS, and the sweep ------------------------------------------


def test_s110_8_direction_due_is_in_tier_7_after_plans_and_swept(ws: ModuleType) -> None:
    for tiers in (ws.TIERS, gate_walk.TIERS):
        kinds = tiers[7]
        assert kinds.index("DIRECTION_DUE") == kinds.index("PLANS") + 1
    assert "DIRECTION_DUE" in ws.SWEPT and "DIRECTION_DUE" in gate_walk.SWEPT
    assert set(ws.SWEPT) == gate_walk.SWEPT
    due = Finding("DIRECTION_DUE", REPO, "G-1 met for 4 weeks", True, (), WATCH_FIX)
    assert gate_walk.order([due, PLANS]) == [PLANS, due]


def test_s110_8_the_gate_starts_a_session_for_a_swept_direction_due_row(checkout: Git) -> None:
    due = Finding("DIRECTION_DUE", "romamo/demo", "G-1 met for 4 weeks", True, (), WATCH_FIX)
    source = Source(swept=[due, PLANS])
    first = tick(checkout, source, agents=cfg(sweep_hours=6))
    assert first.walk is not None and first.walk.sweep and first.work == (PLANS,)
    stored = Swept.load(state_dir(checkout) / SWEEP)
    assert stored is not None and set(stored.rows) == {due, PLANS}
    # the next tick reads the stored sweep and hands DIRECTION_DUE, PLANS being handed
    source.reads.clear()
    source.signature = "changed"
    later = tick(checkout, source, NOW + dt.timedelta(hours=1), agents=cfg(sweep_hours=6))
    assert "sweep" not in source.reads and later.action is Action.LAUNCH and later.work == (due,)
