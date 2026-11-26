"""Spec 098 (#1734): `shipmill status`, `shipmill status --item N`, its record, and the summary
for a held goal plan, read from intake_state.py's own lines through watch_state.py's rows, as
`shipmill status` reads them, without gh or the network"""

import json
from types import ModuleType

import pytest

from shipmill import queue
from shipmill.item_status import PullDetail, Ref, Who, explain
from shipmill.status import Facts, Issue, Verdict, parse_rows, report
from shipmill.status_summary import Holder, split

from .test_status_picture import REPO, facts
from .test_watch_plans import BOT, INTAKE_STATE, WATCH_STATE, intake_lines, load

NONE = PullDetail((), "", ())
URL = f"https://github.com/{REPO}"
MET_AT = "2026-10-02T00:00:00Z"
UNANSWERED = ("triaged as plan: waits on the maintainer's answer to the plan", Who.MAINTAINER)
RECHECK = ("triaged as plan, its hold met: waits on product intake to re-check it", Who.AGENT)


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load(WATCH_STATE, "watch_state_status_hold")


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    return load(INTAKE_STATE, "intake_state_status_hold")


def held_line(ist: ModuleType, number: int, state: str, note: str, until: str, met_at: str | None) -> str:
    """intake_state.py's own --plans --json line for a plan held until `until`"""
    row = ist.PlanRow("G-1", state, "Plan for G-1", note, number, "plan", BOT, "NONE", hold=(until, met_at))
    return json.dumps(ist.plan_json(row), sort_keys=True)


def held(ist: ModuleType) -> str:
    return held_line(ist, 27, "PLAN_HELD", "until 2026-12-15", "2026-12-15", None)


def hold_met(ist: ModuleType) -> str:
    return held_line(ist, 27, "PLAN_HOLD_MET", "hold met: 2026-10-02; re-check due", "2026-10-02", MET_AT)


def rechecked(ist: ModuleType) -> str:
    return held_line(ist, 27, "PLAN_OPEN", "hold met: 2026-10-02", "2026-10-02", MET_AT)


def picture(ws: ModuleType, line: str) -> Facts:
    """The facts `shipmill status` builds for one plan, #27, triaged as a plan: watch_state.py's
    PLANS and PLAN_OPEN rows from intake_state.py's line, through their --json, as it reads them"""
    text = intake_lines(line)
    rows = [*ws.plans_rows(text, REPO, BOT).rows, *ws.plans_waiting(text, REPO, BOT)]
    read = parse_rows("".join(json.dumps(r.json(), sort_keys=True) + "\n" for r in rows))
    return facts(*read, issues=[Issue(27, "TRIAGED", verdict="plan", proposal=True)])


def whos(found: Facts) -> list[tuple[str, Who]]:
    return [(c.reason, c.who) for c in explain(found, Ref("27", 27, None), lambda _: NONE, None).conditions]


def test_s098_12_status_adds_no_reason_for_a_held_or_hold_met_plan(ws: ModuleType, ist: ModuleType) -> None:
    for line in (held(ist), hold_met(ist)):
        found = report(picture(ws, line))
        assert not any("goal plan" in r.text for r in found.reasons)
        assert found.verdict is not Verdict.WAITS


def test_s098_12_status_waits_on_you_again_for_a_rechecked_plan(ws: ModuleType, ist: ModuleType) -> None:
    found = report(picture(ws, rechecked(ist)))
    assert found.verdict is Verdict.WAITS
    # #1680's reason, word for word, as for a plan that was never held
    assert [(r.text, r.fix) for r in found.reasons] == [
        (f"goal plan #27 {URL}/issues/27 waits on your answer", "answer the goal plan")
    ]


def test_s098_13_a_hold_met_plan_is_the_agents_until_it_is_rechecked(ws: ModuleType, ist: ModuleType) -> None:
    found = picture(ws, hold_met(ist))
    assert whos(found) == [RECHECK]
    record = queue.items(found, lambda _: NONE, None, [27])[27]
    assert (record.holder.value, record.why) == ("agent", RECHECK[0])
    assert split(found, lambda _: NONE, None).issues[Holder.AGENT] == (27,)


def test_s098_13_a_rechecked_plan_is_the_maintainers_as_an_unanswered_one(ws: ModuleType, ist: ModuleType) -> None:
    found = picture(ws, rechecked(ist))
    never_held = facts(issues=[Issue(27, "TRIAGED", verdict="plan", proposal=True)])
    assert whos(found) == whos(never_held) == [UNANSWERED]
    record = queue.items(found, lambda _: NONE, None, [27])[27]
    assert record.record() == queue.items(never_held, lambda _: NONE, None, [27])[27].record()
    assert record.holder.value == "maintainer"
    assert split(found, lambda _: NONE, None).issues[Holder.MAINTAINER] == (27,)
