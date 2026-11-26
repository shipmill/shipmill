"""#1680: a goal plan waiting for the maintainer's answer (intake_state.py --plans reads it
PLAN_OPEN) is a WAITS ON YOU reason in `shipmill status`, read as fleet.py queue reads it,
and never an action of the gate's"""

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from shipmill import status
from shipmill.errors import ReleaseError
from shipmill.gate import Action, decide, parse_findings
from shipmill.status import Row, Verdict, report

from .test_intake_plans import Fake, open_plan
from .test_status_picture import REPO, facts, lines

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "github-ship-watch" / "scripts"
INTAKE_STATE = ROOT / "skills" / "product-intake" / "scripts" / "intake_state.py"
BOT = "shipmill-app[bot]"
URL = f"https://github.com/{REPO}"
NOW = dt.datetime(2026, 10, 20, 12, tzinfo=dt.UTC)


def load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fl() -> ModuleType:
    return load(SCRIPTS / "fleet.py", "fleet_plan_waits")


@pytest.fixture(scope="module")
def ws(fl: ModuleType) -> ModuleType:
    module: ModuleType = fl.WS  # the watch_state.py fleet.py itself runs with
    return module


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    return load(INTAKE_STATE, "intake_state_plan_waits")


def plan_line(number: int, state: str, author: str = BOT, association: str | None = "NONE") -> str:
    row = {
        "goal": "G-1",
        "kind": "plan",
        "number": number,
        "state": state,
        "title": "t",
        "note": "",
        "author": author,
        "association": association,
    }
    return json.dumps(row, sort_keys=True)


def intake_lines(*rows: str) -> str:
    return "\n".join([json.dumps({"autonomy": "propose"}), *rows]) + "\n"


def test_an_open_plan_reads_as_the_queue_reads_it(ws: ModuleType, fl: ModuleType) -> None:
    text = intake_lines(
        plan_line(20, "PLAN_OPEN"),  # the --bot-login's
        plan_line(21, "PLAN_OPEN", author="maintainer", association="OWNER"),
        plan_line(22, "PLAN_OPEN", author="drive-by", association="NONE"),  # an outsider's adds nothing
        plan_line(23, "PLAN_ANSWERED"),
        plan_line(24, "PLAN_FILED"),
        plan_line(25, "PLAN_ACCEPTED"),
        plan_line(26, "PLAN_DECLINED"),
    )
    (row,) = ws.plans_waiting(text, "o/r", BOT)
    assert (row.state, row.subject, row.detail) == ("PLAN_OPEN", "o/r", "#20 #21")
    # the queue's own reading: the same intake state, and the same fix it asks the maintainer
    assert fl.INTAKE_KINDS[("plan", "PLAN_OPEN")] == fl.PLAN
    assert row.fix == fl.ASKED[fl.PLAN] == "answer the goal plan"
    # under --trusted-only only the --bot-login's plan is trusted, as PLANS reads it
    (trusted,) = ws.plans_waiting(text, "o/r", BOT, trusted_only=True)
    assert trusted.detail == "#20"
    # without --bot-login only a member's plan is trusted, and no other state adds a row
    assert [r.detail for r in ws.plans_waiting(text, "o/r", None)] == ["#21"]
    assert ws.plans_waiting(intake_lines(plan_line(23, "PLAN_ANSWERED")), "o/r", BOT) == []
    assert ws.plans_waiting(intake_lines(), "o/r", BOT) == []


def test_an_open_plan_is_never_an_action_of_the_gate(ws: ModuleType) -> None:
    (row,) = ws.plans_waiting(intake_lines(plan_line(20, "PLAN_OPEN")), "o/r", BOT)
    assert row.json()["agent"] is False
    assert "PLAN_OPEN" not in ws.ACTION | ws.AGENT and row.json()["fix"] == "answer the goal plan"
    assert all("PLAN_OPEN" not in states for states in ws.TIERS.values()) and "PLAN_OPEN" not in ws.SWEPT
    # the PLANS row is unchanged: an open plan is still in none of it
    assert ws.plans_rows(intake_lines(plan_line(20, "PLAN_OPEN")), "o/r", BOT) == ws.Plans([], frozenset())
    findings = parse_findings(json.dumps(row.json(), sort_keys=True))
    assert decide(findings, [], None, NOW, dt.timedelta(hours=6)).action is Action.QUIET


def test_a_plan_line_with_a_malformed_association_is_refused(ws: ModuleType) -> None:
    line = plan_line(20, "PLAN_OPEN", author="maintainer").replace('"NONE"', "7")
    with pytest.raises(ws.Refused):
        ws.plans_waiting(intake_lines(line), "o/r", BOT)


def test_intake_names_a_plans_openers_association(ist: ModuleType) -> None:
    by_bot, by_hand = open_plan(20), open_plan(21, author="maintainer", bot=False, association="OWNER")
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
        goals=lambda: [ist.Goal("G-1", "a")],
        marker="Triage:",
        bot_login=BOT,
        wip=None,
        room=lambda limit: 1,
        run=Fake(plans=[by_bot, by_hand]),
        filing=lambda issue, body: ("PLAN_FILED", ""),
    )
    shown = {r.number: ist.plan_json(r) for r in found if r.kind == "plan"}
    assert {n: (line["state"], line["association"]) for n, line in shown.items()} == {
        20: ("PLAN_OPEN", "NONE"),
        21: ("PLAN_OPEN", "OWNER"),
    }
    assert {line["author"] for line in shown.values()} == {BOT, "maintainer"}


def plan_row(detail: str = "#23") -> Row:
    return Row("PLAN_OPEN", REPO, detail, False, "answer the goal plan")


def test_status_waits_on_you_for_an_open_plan() -> None:
    assert report(facts()).verdict is Verdict.IDLE  # nothing else open
    found = report(facts(plan_row("#23 #25")))
    assert found.verdict is Verdict.WAITS
    assert [(r.text, r.fix) for r in found.reasons] == [
        (f"goal plan #23 {URL}/issues/23 waits on your answer", "answer the goal plan"),
        (f"goal plan #25 {URL}/issues/25 waits on your answer", "answer the goal plan"),
    ]
    text = lines(facts(plan_row("#23 #25")))
    at = text.index(f"  goal plan      #23 {URL}/issues/23")
    assert text[at + 1 : at + 3] == [
        f"                 #25 {URL}/issues/25",
        "                 fix: answer the goal plan",
    ]
    assert not any(line.startswith("  other") for line in text)  # S-009-13: placed
    assert "PLAN_OPEN" in status.PLACED


def test_status_refuses_an_unreadable_plan_row() -> None:
    with pytest.raises(ReleaseError, match="PLAN_OPEN"):
        report(facts(plan_row("#23 the title")))
