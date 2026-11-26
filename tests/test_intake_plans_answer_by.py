"""A goal plan's answer date (spec 106, #1738): seven days after its newest revision, or what a
trusted `answer by YYYY-MM-DD` reply sets, and PLAN_OVERDUE once it has ended in UTC; without
the network"""

import datetime as dt
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_fleet_queue import FakeGh, intake_line, load_script, run_queue
from .test_fleet_queue_plan_hold import plan_item
from .test_intake_plans import BOT, MAINTAINERS, comment, ist, open_plan, owner, relay
from .test_watch_plans import WATCH_STATE, load

__all__ = ["ist"]  # the module fixture

# open_plan's plans are opened on 2026-10-01 at 09:00 UTC: their answer is due by 2026-10-08
DUE = "2026-10-08"


def read(ist: ModuleType, issue: dict[str, Any], now: dt.datetime, **kwargs: Any) -> Any:
    """The plan issue's row, read at now"""
    (row,) = ist.plan_issue_rows(
        [issue],
        goals=frozenset({"G-1"}),
        marker="Triage:",
        bot_login=BOT,
        filing=lambda issue, plan: ("PLAN_FILED", ""),
        maintainers=kwargs.get("maintainers", frozenset()),
        holds=kwargs.get("holds"),
        now=now,
    )
    return row


def dates(ist: ModuleType, now: dt.datetime) -> Any:
    """spec 098's hold reader for a date hold, which reads nothing from GitHub"""
    return ist.gh_holds("o/r", lambda query, variables: {}, now)


def on(day: str, hour: int = 12) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00")


# -- S-106-7 --------------------------------------------------------------------------------


def test_s106_7_an_open_plans_answer_is_due_seven_days_after_its_revision(ist: ModuleType) -> None:
    row = read(ist, open_plan(20), on("2026-10-02"))
    assert (row.state, row.note, row.answer_by) == ("PLAN_OPEN", f"answer by {DUE}", DUE)
    assert ist.plan_json(row)["answer_by"] == DUE
    # a revision moves it: seven days after the App's plan-revised comment
    revised = comment("<!-- shipmill:plan-revised rev=2 -->\nRevised.", 0, author="shipmill-app", bot=True)
    revised["createdAt"] = "2026-10-05T10:00:00Z"
    assert read(ist, open_plan(20, revised), on("2026-10-06")).answer_by == "2026-10-12"
    # rows that wait on no answer carry no date
    accepted = read(ist, open_plan(20, owner("accept", 10)), on("2026-10-02"))
    assert accepted.state == "PLAN_FILED" and accepted.answer_by is None
    assert "answer_by" not in ist.plan_json(accepted)


def test_s106_7_a_trusted_answer_by_reply_sets_the_date_and_answers_nothing(ist: ModuleType) -> None:
    later = read(ist, open_plan(20, owner("answer by 2026-10-30", 10)), on("2026-10-20"))
    assert (later.state, later.note, later.answer_by) == ("PLAN_OPEN", "answer by 2026-10-30", "2026-10-30")
    newest = open_plan(20, owner("Answer by 2026-10-30.", 10), owner("answer by 2026-10-04", 11))
    assert read(ist, newest, on("2026-10-02")).answer_by == "2026-10-04"  # the newest counts
    # a relay naming a maintainer counts (D-68)
    relayed = read(ist, open_plan(20, relay("answer by 2026-11-01", 10)), on("2026-10-20"), maintainers=MAINTAINERS)
    assert relayed.answer_by == "2026-11-01"
    # it is no answer: an accept before it still counts, and so does one after it
    before = read(ist, open_plan(20, owner("accept", 10), owner("answer by 2026-10-30", 11)), on("2026-10-02"))
    after = read(ist, open_plan(20, owner("answer by 2026-10-30", 10), owner("accept", 11)), on("2026-10-02"))
    assert before.state == after.state == "PLAN_FILED"


def test_s106_7_an_untrusted_answer_by_changes_nothing(ist: ModuleType) -> None:
    outsider = comment("answer by 2026-12-31", 10, association="NONE", author="drive-by")
    assert read(ist, open_plan(20, outsider), on("2026-10-02")).answer_by == DUE
    by_bot = comment("answer by 2026-12-31", 10, author="shipmill-app", bot=True)
    assert read(ist, open_plan(20, by_bot), on("2026-10-02")).answer_by == DUE
    bad_date = owner("answer by 2026-02-30", 10)
    assert read(ist, open_plan(20, bad_date), on("2026-10-02")).answer_by == DUE


# -- S-106-8 --------------------------------------------------------------------------------


def test_s106_8_past_its_answer_date_a_plan_reads_overdue_no_action(ist: ModuleType) -> None:
    assert read(ist, open_plan(20), on(DUE, 23)).state == "PLAN_OPEN"  # the date itself hasn't ended
    overdue = read(ist, open_plan(20), on("2026-10-09", 0))
    assert (overdue.state, overdue.note, overdue.answer_by) == ("PLAN_OVERDUE", f"answer by {DUE}", DUE)
    assert "PLAN_OVERDUE" not in ist.PLAN_ACTION  # exit 0 when it is the only row


def test_s106_8_a_held_plan_has_no_date_until_it_reads_open_from_its_recheck(ist: ModuleType) -> None:
    hold = owner("hold until 2026-10-20", 10)
    held = read(ist, open_plan(20, hold), on("2026-10-15"), holds=dates(ist, on("2026-10-15")))
    assert (held.state, held.answer_by) == ("PLAN_HELD", None)
    recheck = comment(
        "<!-- shipmill:plan-recheck -->\nNothing in this plan is done or stale.", 0, author="shipmill-app", bot=True
    )
    recheck["createdAt"] = "2026-10-21T10:00:00Z"
    rechecked = read(ist, open_plan(20, hold, recheck), on("2026-10-22"), holds=dates(ist, on("2026-10-22")))
    assert (rechecked.state, rechecked.answer_by) == ("PLAN_OPEN", "2026-10-28")  # seven days from the re-check
    assert rechecked.note == "hold met: 2026-10-20; answer by 2026-10-28"


def test_s106_8_the_watch_reads_an_overdue_plan_as_waiting_on_the_maintainer() -> None:
    ws = load(WATCH_STATE, "watch_state_answer_by")
    line = {"goal": "G-1", "kind": "plan", "number": 20, "state": "PLAN_OVERDUE", "title": "t"}
    line |= {"note": f"answer by {DUE}", "author": BOT, "association": "NONE", "answer_by": DUE}
    text = "\n".join([json.dumps({"autonomy": "propose"}), json.dumps(line)]) + "\n"
    assert ws.plans_rows(text, "o/r", BOT).rows == []  # no action, no session
    (row,) = ws.plans_waiting(text, "o/r", BOT)
    assert (row.state, row.detail) == ("PLAN_OPEN", "#20")
    asked = {**line, "state": "PLAN_OPEN", "note": f"unclear accept asked; answer by {DUE}"}
    asked_text = "\n".join([json.dumps({"autonomy": "propose"}), json.dumps(asked)]) + "\n"
    assert ws.plans_waiting(asked_text, "o/r", BOT) == []  # its question is NEEDS_DECISION's


def test_s106_8_the_queue_still_lists_an_overdue_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """fleet.py queue lists a PLAN_OVERDUE plan as a PLAN row, as it did while it read PLAN_OPEN;
    its overdue look is #1743's (S-106-26)"""
    queue = load_script("fleet")
    lines = [{"autonomy": "propose"}, intake_line(32, "PLAN_OVERDUE", "plan")]
    github = {"o/r": {32: plan_item(32, 9)}}
    code, out = run_queue(queue, tmp_path, capsys, FakeGh(intake={"o/r": lines}, github=github), "--bot-login", BOT)
    assert code == 1 and out.splitlines() == ["o/r PLAN          #32    answer the goal plan: Plan 32 (9d 0h)"]
