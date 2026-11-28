"""The watch reads spec 106's goal, project, and opportunity rows that intake_state.py
--plans --goals --projects prints, lists their actions on the PLANS row, and gives
`shipmill status --item` their states (S-106-25, S-106-26); without gh or the network"""

import json
from types import ModuleType

import pytest

from .test_status_plan_waits import BOT, INTAKE_STATE, intake_lines, load
from .test_watch_plans import WATCH_STATE

REPO = "o/r"


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load(WATCH_STATE, "watch_state_goal_states")


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    return load(INTAKE_STATE, "intake_state_goal_states")


def goal(ist: ModuleType, ident: str | None, state: str, note: str, holder: str | None, by: str | None = None) -> str:
    """intake_state.py's own --json line for a goal's state (or a proposal's, with no id)"""
    number = 45 if ident is None else None
    return json.dumps(ist.goal_json(ist.GoalRow(ident, state, "SECRET text", note, holder, by, number)))


def head(ist: ModuleType, number: int, state: str, note: str, check: int | None = None) -> str:
    """intake_state.py's own --json line for a project head"""
    return json.dumps(ist.project_json(ist.ProjectRow(number, state, "SECRET title", note, check, 1, 2)))


def opportunity(
    ist: ModuleType, number: int, state: str, note: str = "", author: str = BOT, association: str = "NONE"
) -> str:
    """intake_state.py's own --json line for an accepted opportunity that names its goal"""
    item = ist.Item(number, "opportunity", "SECRET", 0, state=state, note=note, author=author, association=association)
    return json.dumps(ist.json_row(item))


def plan(ist: ModuleType, number: int, state: str, note: str, answer_by: str | None = None) -> str:
    row = ist.PlanRow("G-1", state, "SECRET plan", note, number, "plan", BOT, "NONE", answer_by=answer_by)
    return json.dumps(ist.plan_json(row), sort_keys=True)


def first(ist: ModuleType, active: int = 2, limit: int = 2) -> str:
    projects = ist.Projects("o/home", limit, active)
    return json.dumps(ist.first_line("propose", None, projects))


def spec106_lines(ist: ModuleType) -> str:
    """One row of every spec 106 kind intake_state.py prints, with each of its actions"""
    rows = [
        first(ist),
        goal(ist, "G-1", "GOAL_WRITTEN", "plan #60 waits on your answer", "maintainer", "2027-01-01"),
        goal(ist, "G-2", "GOAL_OVERDUE", "2026-11-01 passed; a plan is due", "agent", "2026-11-01"),
        goal(ist, "G-3", "GOAL_PLANNED", "project #51 open", "projects", "v2.0.0"),
        goal(ist, "G-4", "GOAL_MET", "met", None, None),
        goal(ist, None, "GOAL_PROPOSED", "waits on your answer", "maintainer"),
        opportunity(ist, 40, "NEEDS_GOAL", "names no goal: answer `accept G-<n>` or `accept new goal`"),
        opportunity(ist, 41, "GOAL_PROPOSAL_DUE", "open its goal proposal"),
        opportunity(ist, 42, "ACCEPTED_INTO", "G-1"),
        head(ist, 50, "PROJECT_START_DUE", "its turn to start"),
        head(ist, 51, "PROJECT_IDLE", "no update since 2026-11-01", check=70),
        head(ist, 52, "PROJECT_STOP_DUE", "stop: out of scope", check=71),
        head(ist, 53, "PROJECT_HELD", "labelled held"),
        head(ist, 54, "PROJECT_HELD", "no check issue"),
        head(ist, 55, "PROJECT_CLOSING", "no cleanup listed", check=72),
        plan(ist, 60, "PLAN_OPEN", "waits on your answer; answer by 2026-12-01", "2026-12-01"),
        plan(ist, 61, "PLAN_OVERDUE", "answer by 2026-11-20", "2026-11-20"),
        plan(ist, 62, "PLAN_REPLACED", "by #63"),
        plan(ist, 63, "PLAN_OPEN", "waits on your answer; answer by 2026-12-03", "2026-12-03"),
    ]
    return "\n".join(rows) + "\n"


def test_s106_26_the_plans_row_lists_every_spec_106_action(ws: ModuleType, ist: ModuleType) -> None:
    (row,) = ws.plans_rows(spec106_lines(ist), REPO, BOT).rows
    assert row.state == "PLANS" and row.action and row.json()["agent"] is True
    assert row.detail == (
        "PLAN_REPLACED #62; GOAL_OVERDUE G-2; GOAL_PROPOSAL_DUE #41; NEEDS_GOAL #40;"
        " PROJECT_START_DUE #50; PROJECT_IDLE #51; PROJECT_STOP_DUE #52"
    )
    assert "SECRET" not in row.detail and "SECRET" not in (row.fix or "")  # ids and numbers only (D-16)
    # the same lines leave the feedback rows as they were, and the first line's projects reads
    assert ws.feedback_rows(spec106_lines(ist), REPO, ws.parse_time("2026-11-26T00:00:00Z"), BOT).rows == []
    assert ws.intake_level(spec106_lines(ist)) == "propose"


def test_s106_26_the_watch_knows_every_state_intake_prints(ws: ModuleType, ist: ModuleType) -> None:
    assert set(ist.PROJECT_HOLDERS) == ws.PROJECT_STATES
    assert set(ws.PROJECT_ACTION) == ist.PROJECT_ACTION and set(ws.GOAL_ACTION) == ist.GOAL_ACTION
    assert ist.ACTION - {"NEW_FEEDBACK", "ACCEPTED", "NO_REASON", "OVERLAP"} <= set(ws.OPPORTUNITY_ACTION)
    assert {"PLAN_REPLACED", "PLAN_OVERDUE"} <= ws.PLAN_STATES


@pytest.mark.parametrize(
    "line",
    [
        '{"kind": "project", "number": 5, "state": "PROJECT_LOST", "note": "", "holder": null, "check": null,'
        ' "parts": {"open": 0, "closed": 0}}',
        '{"kind": "project", "number": 5, "state": "PROJECT_HELD", "note": "", "holder": "anyone", "check": null,'
        ' "parts": {"open": 0, "closed": 0}}',
        '{"kind": "project", "number": 5, "state": "PROJECT_HELD", "note": "", "holder": "start", "check": null,'
        ' "parts": {"open": -1, "closed": 0}}',
        '{"kind": "goal-state", "goal": "G-1", "number": null, "state": "GOAL_GONE", "note": "", "holder": null,'
        ' "by": null}',
        '{"kind": "goal-state", "goal": "G-1", "number": null, "state": "GOAL_WRITTEN", "note": "", "holder": null,'
        ' "by": "next week"}',
        '{"kind": "goal-state", "goal": null, "number": null, "state": "GOAL_PROPOSED", "note": "", "holder": null,'
        ' "by": null}',
        '{"kind": "opportunity", "number": "12", "state": "NEEDS_GOAL"}',
    ],
)
def test_s106_26_a_row_intake_could_not_print_is_refused(ws: ModuleType, line: str) -> None:
    with pytest.raises(ws.Refused, match="malformed"):
        ws.plans_rows(intake_lines(line), REPO, BOT)


def test_s106_26_a_malformed_projects_count_is_refused(ws: ModuleType) -> None:
    bad = json.dumps({"autonomy": "propose", "projects": {"limit": 2, "active": 2, "room": 1}})
    with pytest.raises(ws.Refused, match="not its autonomy line"):
        ws.intake_level(bad + "\n")


def test_s106_25_the_item_read_gives_each_goal_plan_and_head_its_state(ws: ModuleType, ist: ModuleType) -> None:
    found = {r.state: r for r in ws.item_states(spec106_lines(ist), REPO, BOT)}
    assert found["GOAL_STATE"].detail == (
        "G-1 GOAL_WRITTEN holder=maintainer by=2027-01-01 on=#60; G-2 GOAL_OVERDUE holder=agent by=2026-11-01;"
        " G-3 GOAL_PLANNED holder=projects by=v2.0.0 on=#51; G-4 GOAL_MET holder=none;"
        " #45 GOAL_PROPOSED holder=maintainer"
    )
    assert found["PLAN_STATE"].detail == (
        "#60 PLAN_OPEN answer_by=2026-12-01; #61 PLAN_OVERDUE answer_by=2026-11-20; #62 PLAN_REPLACED replaced_by=#63;"
        " #63 PLAN_OPEN answer_by=2026-12-03"
    )
    assert found["PROJECT_STATE"].detail == (
        "#50 PROJECT_START_DUE holder=agent; #51 PROJECT_IDLE holder=agent check=#70;"
        " #52 PROJECT_STOP_DUE holder=agent check=#71; #53 PROJECT_HELD holder=start held=label;"
        " #54 PROJECT_HELD holder=start held=check; #55 PROJECT_CLOSING holder=checker check=#72;"
        " active 2 of 2; overdue o/r#61"
    )
    assert all(not r.action and not r.json()["agent"] and "SECRET" not in r.detail for r in found.values())
    assert all(s not in ws.SWEPT and all(s not in t for t in ws.TIERS.values()) for s in found)


def test_s106_25_a_closing_head_whose_check_closed_reads_checked(ws: ModuleType, ist: ModuleType) -> None:
    text = intake_lines(
        head(ist, 57, "PROJECT_CLOSING", "check #74 closed; the head is open", check=74),
        head(ist, 58, "PROJECT_CLOSING", "no cleanup listed", check=75),
    )
    (row,) = ws.item_states(text, REPO, BOT)
    assert row.detail == (
        "#57 PROJECT_CLOSING holder=agent check=#74 checked; #58 PROJECT_CLOSING holder=checker check=#75"
    )


def test_s106_25_an_overdue_plan_of_another_repo_reaches_the_heads(ws: ModuleType, ist: ModuleType) -> None:
    waits = ist.PlanRow("G-1", "PLAN_WAITS", "SECRET", "plan o/other#8 overdue")
    text = intake_lines(json.dumps(ist.plan_json(waits)), head(ist, 53, "PROJECT_HELD", "no check issue"))
    (row,) = ws.item_states(text, REPO, BOT)
    assert row.detail == "#53 PROJECT_HELD holder=start held=check; overdue o/other#8"


def test_s106_25_item_reads_a_goal_id(ws: ModuleType, ist: ModuleType) -> None:
    assert ws.item_arg("G-3") == "G-3" and ws.item_arg("12") == 12
    for bad in ("0", "g-3", "G-0", "#3"):
        with pytest.raises(Exception, match="neither"):
            ws.item_arg(bad)
    rows = [
        *ws.plans_rows(spec106_lines(ist), REPO, BOT).rows,
        *ws.item_states(spec106_lines(ist), REPO, BOT),
        ws.Row("PLANS", REPO, "GOAL_OVERDUE G-20", "x"),
        ws.Row("HOLD", "#9", "held", "close #9"),
        ws.Row("NEEDS_DECISION", REPO, "#2", "answer #2"),
    ]
    kept = [(r.state, r.detail) for r in rows if ws.item_row(r, "G-2")]
    assert [s for s, _ in kept] == ["PLANS", "GOAL_STATE", "PLAN_STATE", "PROJECT_STATE", "HOLD"]
    assert "GOAL_OVERDUE G-20" not in [d for _, d in kept]


def test_s106_26_an_outsiders_opportunity_or_plan_starts_no_session(ws: ModuleType, ist: ModuleType) -> None:
    """D-16: under --trusted-only an accepted opportunity an outsider opened is UNTRUSTED, and a
    plan replaced by an untrusted plan is in no row, so the App's plan is never closed for it"""
    text = intake_lines(
        opportunity(ist, 40, "NEEDS_GOAL", author="drive-by"),
        opportunity(ist, 41, "GOAL_PROPOSAL_DUE", author="amy", association="OWNER"),
        plan(ist, 62, "PLAN_REPLACED", "by #64"),
        json.dumps(ist.plan_json(ist.PlanRow("G-1", "PLAN_OPEN", "t", "n", 64, "plan", "drive-by", "NONE"))),
    )
    headless = ws.plans_rows(text, REPO, BOT, trusted_only=True)
    # the OWNER's opportunity is trusted, as feedback_rows trusts an ACCEPTED one (opener_trusted)
    assert [r.detail for r in headless.rows] == ["GOAL_PROPOSAL_DUE #41"] and headless.untrusted == {40, 64}
    # a person's pass lists the outsider's opportunity too, and still never the outsider's replacing plan
    (row,) = ws.plans_rows(text, REPO, BOT).rows
    assert row.detail == "GOAL_PROPOSAL_DUE #41; NEEDS_GOAL #40"
    trusted = intake_lines(plan(ist, 62, "PLAN_REPLACED", "by #63"), plan(ist, 63, "PLAN_OPEN", "n", "2026-12-03"))
    assert [r.detail for r in ws.plans_rows(trusted, REPO, BOT, trusted_only=True).rows] == ["PLAN_REPLACED #62"]


def test_s106_26_an_opportunity_row_without_its_opener_is_refused(ws: ModuleType) -> None:
    line = '{"kind": "opportunity", "number": 12, "state": "NEEDS_GOAL", "note": ""}'
    with pytest.raises(ws.Refused, match="malformed opportunity"):
        ws.plans_rows(intake_lines(line), REPO, BOT)


def test_s106_25_the_products_overdue_plans_reach_the_heads(ws: ModuleType, ist: ModuleType) -> None:
    line = json.dumps(ist.first_line("propose", None, None, ("o/other#8",)))
    text = "\n".join([line, head(ist, 53, "PROJECT_HELD", "no check issue")]) + "\n"
    (row,) = ws.item_states(text, REPO, BOT)
    assert row.detail == "#53 PROJECT_HELD holder=start held=check; overdue o/other#8"
    # the same plan in another case is named once
    twice = json.dumps(ist.first_line("propose", None, None, ("O/Other#8", "o/other#8")))
    (row,) = ws.item_states("\n".join([twice, head(ist, 53, "PROJECT_HELD", "no check issue")]) + "\n", REPO, BOT)
    assert [p for p in row.detail.split("; ") if p.startswith("overdue ")] == ["overdue O/Other#8"]
    assert ws.intake_level(text) == "propose"
    for bad in ([], ["o/other"], "o/other#8"):
        with pytest.raises(ws.Refused, match="not its autonomy line"):
            ws.intake_level(json.dumps({"autonomy": "propose", "overdue": bad}) + "\n")
    late = '{"goal": "G-1", "kind": "plan", "number": 9, "state": "PLAN_OVERDUE", "title": "t", "note": "",'
    late += ' "author": "shipmill-app[bot]", "association": "NONE"}'
    with pytest.raises(ws.Refused, match="malformed plan row"):
        ws.item_states(intake_lines(late), REPO, BOT)
