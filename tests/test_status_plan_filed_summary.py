"""#1787: the watch's report-only PLAN_FILED row (#1724) is placed in the plain `shipmill
status` summary, as PLAN_OPEN is (S-009-13): it never shows under "other". Such a plan waits
on its open items, never on the maintainer, so the summary is silent about it and `status
--item` reads it; without gh or the network"""

from types import ModuleType

import pytest

from shipmill import status
from shipmill.status import Issue, Verdict, report

from .test_status_picture import facts, lines
from .test_status_plan_filed import filed_line, rows_for
from .test_status_plan_waits import INTAKE_STATE, intake_lines, load
from .test_watch_plans import WATCH_STATE


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load(WATCH_STATE, "watch_state_status_plan_filed_summary")


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    return load(INTAKE_STATE, "intake_state_status_plan_filed_summary")


def test_1787_a_plan_filed_row_lists_nothing_under_other(ws: ModuleType, ist: ModuleType) -> None:
    rows = rows_for(ws, intake_lines(filed_line(ist)))
    assert [r.state for r in rows] == ["PLAN_FILED"]
    found = facts(*rows, issues=[Issue(40, "TRIAGED", verdict="plan"), Issue(212, "NEEDS_PR")])
    text = lines(found)
    assert not any(line.startswith("  other") for line in text)  # S-009-13: placed
    assert not any("PLAN_FILED" in line for line in text)  # silent: the plan waits on its work
    assert "PLAN_FILED" in status.PLACED
    # not the maintainer's: no WAITS ON YOU reason, as PLAN_OPEN brings
    assert report(facts(*rows)).verdict is Verdict.IDLE
