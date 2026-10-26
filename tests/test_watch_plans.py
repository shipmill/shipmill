"""The watch's PLANS row and triage's reading of a plan (spec 028, #515), without gh or the network"""

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.gate import Action, decide, parse_findings

from .test_intake_plans import Fake, issue, plan

ROOT = Path(__file__).resolve().parents[1]
WATCH_STATE = ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
INTAKE_STATE = ROOT / "skills" / "product-intake" / "scripts" / "intake_state.py"
TRIAGE_STATE = ROOT / "skills" / "github-issue-triage" / "scripts" / "triage_state.py"
BOT = "shipmill-app[bot]"
NOW = dt.datetime(2026, 10, 20, 12, tzinfo=dt.UTC)


def load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load(WATCH_STATE, "watch_state_plans")


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    return load(INTAKE_STATE, "intake_state_watch")


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load(TRIAGE_STATE, "triage_state_plans")


def goal_row(goal: str, state: str, note: str = "no-work", number: int | None = None) -> str:
    row = {"goal": goal, "kind": "goal", "number": number, "state": state, "title": "t", "note": note, "author": None}
    return json.dumps(row, sort_keys=True)


def plan_row(number: int, state: str, author: str = BOT, note: str = "") -> str:
    row = {
        "goal": "G-1",
        "kind": "plan",
        "number": number,
        "state": state,
        "title": "t",
        "note": note,
        "author": author,
    }
    return json.dumps(row, sort_keys=True)


FEEDBACK = [
    json.dumps({"autonomy": "propose"}),
    json.dumps({"number": 4, "kind": "issue", "state": "NEW_FEEDBACK", "title": "x", "thumbs": 0, "members": []}),
]


def intake_lines(*rows: str) -> str:
    return "\n".join([*FEEDBACK, *rows]) + "\n"


def test_s028_13_the_plans_row_lists_each_action_state(ws: ModuleType) -> None:
    text = intake_lines(
        goal_row("G-1", "PLAN_DUE"),
        goal_row("G-3", "PLAN_DUE", "requested in #25", 25),
        plan_row(20, "PLAN_MALFORMED", note="line 1: no marker"),
        plan_row(21, "PLAN_ANSWERED", note="edit"),
        plan_row(22, "PLAN_ACCEPTED", note="not filed: W-2"),
        goal_row("G-2", "PLAN_WAITS", "no-work; waits for room"),
        plan_row(23, "PLAN_OPEN"),
        plan_row(24, "PLAN_FILED"),
        plan_row(26, "PLAN_DECLINED", note="not now"),
    )
    found = ws.plans_rows(text, "o/r", BOT)
    (row,) = found.rows
    assert (row.state, row.subject) == ("PLANS", "o/r")
    assert row.detail == "PLAN_DUE G-1 G-3; PLAN_MALFORMED #20; PLAN_ANSWERED #21; PLAN_ACCEPTED #22"
    assert row.fix == "/shipmill:product-intake o/r"
    assert row.json()["agent"] is True and "PLANS" in ws.ACTION and "PLANS" in ws.AGENT
    assert found.untrusted == frozenset()


def test_s028_13_no_plan_action_gives_no_row(ws: ModuleType) -> None:
    text = intake_lines(goal_row("G-2", "PLAN_WAITS"), plan_row(23, "PLAN_OPEN"), plan_row(24, "PLAN_FILED"))
    assert ws.plans_rows(text, "o/r", BOT) == ws.Plans([], frozenset())
    assert ws.plans_rows(intake_lines(), "o/r", BOT) == ws.Plans([], frozenset())  # feedback alone


def test_s028_13_shipmill_gate_starts_a_session_for_plans(ws: ModuleType) -> None:
    (row,) = ws.plans_rows(intake_lines(goal_row("G-1", "PLAN_DUE")), "o/r", BOT).rows
    findings = parse_findings(json.dumps(row.json(), sort_keys=True))
    decision = decide(findings, [], None, NOW, dt.timedelta(hours=6))
    assert decision.action is Action.LAUNCH and [f.state for f in decision.work] == ["PLANS"]


def test_s028_13_trusted_only_starts_none_for_a_plan_the_bot_login_did_not_open(ws: ModuleType) -> None:
    text = intake_lines(
        goal_row("G-1", "PLAN_DUE"),
        plan_row(20, "PLAN_ANSWERED", author="maintainer"),
        plan_row(21, "PLAN_ACCEPTED", author="Shipmill-App[bot]"),  # logins compare in any case
        plan_row(22, "PLAN_OPEN", author="drive-by"),
        plan_row(23, "PLAN_DECLINED", author="drive-by"),  # closed: in no row
    )
    found = ws.plans_rows(text, "o/r", BOT, trusted_only=True)
    (row,) = found.rows
    assert row.detail == "PLAN_DUE G-1; PLAN_ACCEPTED #21"
    assert found.untrusted == frozenset({20, 22})
    # without --trusted-only every plan is listed
    assert ws.plans_rows(text, "o/r", BOT).rows[0].detail == "PLAN_DUE G-1; PLAN_ANSWERED #20; PLAN_ACCEPTED #21"
    # with no --bot-login, no plan issue is the gate's own
    bare = ws.plans_rows(text, "o/r", None, trusted_only=True)
    assert bare.rows[0].detail == "PLAN_DUE G-1" and bare.untrusted == frozenset({20, 21, 22})


def test_s028_13_an_untrusted_plan_is_in_untrusted_and_nothing_else(ws: ModuleType) -> None:
    triage = "\n".join(
        json.dumps({"number": n, "state": s, "title": "t", "note": ""})
        for n, s in ((20, "NEW"), (22, "TRIAGED"), (30, "NEW"))
    )
    rows = ws.intake("o/r", 1, triage, [], lambda n: [], BOT, True, None, None, frozenset({20, 22}))
    shown = {r.state: r.detail for r in rows}
    assert shown == {"ISSUES": "NEW #30", "UNTRUSTED": "#20 #22"}
    assert all(r.json()["agent"] is False for r in rows if r.state == "UNTRUSTED")


def test_s028_13_issues_and_prs_open_are_unchanged_without_plans(ws: ModuleType) -> None:
    triage = json.dumps({"number": 30, "state": "NEW", "title": "t", "note": ""})
    pr = {"number": 3, "isDraft": False, "isCrossRepository": False, "labels": [], "headRefOid": "a" * 40}
    rows = ws.intake("o/r", 1, triage, [pr], lambda n: [], BOT, True)
    assert [(r.state, r.detail) for r in rows] == [("ISSUES", "NEW #30"), ("PRS_OPEN", "#3")]
    assert rows[1].json()["heads"] == {"3": "a" * 40}  # #546's heads stay


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        json.dumps({"kind": "goal", "goal": "Q-1", "state": "PLAN_DUE"}),
        json.dumps({"kind": "goal", "goal": "G-1", "state": "PLAN_SOMETHING"}),
        json.dumps({"kind": "plan", "number": "20", "state": "PLAN_OPEN", "author": BOT}),
        json.dumps({"kind": "plan", "number": True, "state": "PLAN_OPEN", "author": BOT}),
        json.dumps({"kind": "plan", "number": 20, "state": "PLAN_OPEN", "author": None}),
    ],
)
def test_a_malformed_plan_line_is_refused(ws: ModuleType, line: str) -> None:
    with pytest.raises(ws.Refused):
        ws.plans_rows(intake_lines(line), "o/r", BOT)


def completed(code: int, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, out, err)


def test_s028_13_the_watch_runs_intake_state_in_the_checkout(ws: ModuleType, tmp_path: Path) -> None:
    asked: list[tuple[list[str], Path | None]] = []

    def execute(cmd: list[str], cwd: Path | None, env: dict[str, str] | None) -> subprocess.CompletedProcess[str]:
        asked.append((cmd, cwd))
        return completed(1, intake_lines(goal_row("G-1", "PLAN_DUE")))

    text = ws.plans_run("o/r", tmp_path, "shipmill==1.2.3", BOT, 3, execute)
    assert ws.plans_rows(text, "o/r").rows[0].detail == "PLAN_DUE G-1"
    ((cmd, cwd),) = asked
    assert cwd == tmp_path
    assert cmd[1:] == [
        str(ws.INTAKE_STATE),
        "o/r",
        "--plans",
        "--json",
        "--tool",
        "shipmill==1.2.3",
        "--wip",
        "3",
        "--bot-login",
        BOT,
    ]
    ws.plans_run("o/r", tmp_path, "t", None, None, execute)
    assert "--wip" not in asked[-1][0] and "--bot-login" not in asked[-1][0]
    # without --tool (the watch's default since spec 031) intake_state.py runs the plugin's pin
    ws.plans_run("o/r", tmp_path, None, None, None, execute)
    assert asked[-1][0][1:] == [str(ws.INTAKE_STATE), "o/r", "--plans", "--json"]
    with pytest.raises(ws.Refused, match="exit 2: boom"):
        ws.plans_run("o/r", tmp_path, "t", execute=lambda cmd, cwd, env: completed(2, err="boom"))


def test_s028_13_the_plans_wait_under_agents_wip(ws: ModuleType) -> None:
    policy = Path(".github/shipmill.toml")
    assert ws.plan_wip(None, policy) is None
    assert ws.plan_wip({"prompt": '"x"'}, policy) is None
    assert ws.plan_wip(ws.agents_table("[agents]\nwip = 3\n", policy), policy) == 3
    for bad in ('"3"', "0", "-1", "2.5"):
        with pytest.raises(ws.Refused, match="wip"):
            ws.plan_wip({"wip": bad}, policy)


def test_s028_13_a_plan_row_names_its_opener(ist: ModuleType) -> None:
    by_bot, by_hand = plan(20, "G-1"), plan(21, "G-2", author="maintainer", bot=False)
    intake = ist.fetch(
        "o/r",
        label="opportunity",
        accepted="planned",
        marker="Triage:",
        skip=set(ist.SKIP_LABELS),
        categories=None,
        autonomy="propose",
        run=Fake(plans=[by_bot, by_hand]),
    )
    found = ist.fetch_plans(
        "o/r",
        intake,
        goals=lambda: [ist.Goal("G-1", "a"), ist.Goal("G-2", "b"), ist.Goal("G-3", "c")],
        marker="Triage:",
        bot_login=BOT,
        wip=None,
        room=lambda limit: 1,
        run=Fake(plans=[by_bot, by_hand]),
        filing=lambda issue, body: ("PLAN_FILED", ""),
    )
    assert {r.number: r.author for r in found if r.kind == "plan"} == {20: BOT, 21: "maintainer"}
    assert {r.author for r in found if r.kind == "goal"} == {None}


def test_s028_14_intake_never_reads_a_goal_plan_issue_as_feedback(ist: ModuleType) -> None:
    request = issue(25, title="Plan G-1", labels=("goal-plan",), association="OWNER")
    open_plan = plan(20, "G-1")
    other = issue(26, title="Dark mode")
    intake = ist.fetch(
        "o/r",
        label="opportunity",
        accepted="planned",
        marker="Triage:",
        skip=ist.skip_labels([]),
        categories=None,
        autonomy="propose",
        run=Fake([request, open_plan, other], plans=[open_plan]),
    )
    assert [i.number for i in intake.feedback] == [26]
    assert "goal-plan" in ist.SKIP_LABELS


def triage_item(*comments: str, labels: tuple[str, ...] = ("goal-plan",)) -> dict[str, Any]:
    return {
        "number": 20,
        "body": "<!-- shipmill:plan goal=G-1 rev=1 -->\n## Goal\n",
        "labels": {"nodes": [{"name": n} for n in labels]},
        "comments": {
            "nodes": [{"createdAt": f"2026-10-0{i + 1}T10:00:00Z", "body": b} for i, b in enumerate(comments)]
        },
        "timelineItems": {"nodes": []},
    }


def test_s028_14_triage_reads_a_plan_with_intakes_comment_as_triaged(ts: ModuleType) -> None:
    def state(item: dict[str, Any]) -> str:
        found: str = ts.classify_open(item, "Triage:", "postponed", {}, None, ("o", "r"))[0]
        return found

    assert state(triage_item()) == "NEW"
    assert state(triage_item("Triage: **plan**. A plan for G-1, waiting for the maintainer's answer.")) == "TRIAGED"
    # whatever the rest says: the maintainer's answer moves a plan, never an implement verdict
    assert state(triage_item("Triage: **plan**. Accepted items implement G-1 once filed.")) == "TRIAGED"
    assert state(triage_item("Triage: **Plan**. Implement nothing yet.")) == "TRIAGED"
    # a newer verdict of triage's own still counts, and only a goal-plan issue reads intake's verdict
    assert state(triage_item("Triage: **plan**. x", "Triage: **implement**. y")) == "NEEDS_PR"
    assert state(triage_item("Triage: **plan**. We implement it.", labels=())) == "NEEDS_PR"
