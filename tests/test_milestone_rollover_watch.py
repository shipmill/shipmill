"""Spec 068's milestone rows in github-ship-watch (S-068-9): watch_state.py reads
MILESTONE_RELEASED and MILESTONE_MISSING from `shipmill milestones --json`; the close is an
action a watch pass runs, the create a person's step it never runs"""

import json
from pathlib import Path

import pytest

from shipmill import status as shipmill_status
from shipmill.github import OpenMilestone
from shipmill.status import Row

from .conftest import Repos, at_day
from .test_milestone_rollover_status import CLOSE, CREATE, MISSING, RELEASED
from .test_milestone_status import OVERTAKEN, WAITING, milestones, on_github, printed, stable_released, watch_state
from .test_status_picture import facts, lines

SKILL = Path(__file__).resolve().parents[1] / "skills" / "github-ship-watch" / "SKILL.md"
RELEASED_ITEM = {
    "state": "MILESTONE_RELEASED",
    "milestone": "1.1.0",
    "detail": "d",
    "number": 3,
    "next": None,
    "fix": "close",
}
MISSING_ITEM = {
    "state": "MILESTONE_MISSING",
    "milestone": "1.1.1",
    "detail": "d",
    "number": None,
    "next": "1.1.1",
    "fix": "create",
}


def test_s068_9_the_watch_lists_the_released_and_missing_rows_from_shipmill_milestones(
    repos: Repos, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = repos.after(tmp_path, stable_released)
    repo.github.open = [OpenMilestone(3, "1.1.0", 0)]
    on_github(repo)
    ws = watch_state()
    released, missing = ws.milestone_rows(milestones(repo, at_day(6), capsys, "--json"))
    assert released.json() == {
        "state": "MILESTONE_RELEASED",
        "subject": "1.1.0",
        "detail": RELEASED.detail,
        "agent": False,
        "fix": CLOSE,
    }
    assert missing.json() == {
        "state": "MILESTONE_MISSING",
        "subject": "1.1.1",
        "detail": MISSING.detail,
        "agent": False,
        "fix": CREATE,
    }
    assert released.text().endswith(f"\n{ws.FIX_INDENT}fix: {CLOSE}")
    assert missing.text().endswith(f"\n{ws.FIX_INDENT}fix: {CREATE}")


def test_s068_9_the_close_is_an_action_and_the_create_a_persons_fix_never_an_agents() -> None:
    ws = watch_state()
    assert "MILESTONE_RELEASED" in ws.ACTION and "MILESTONE_RELEASED" not in ws.AGENT
    assert "MILESTONE_MISSING" in ws.FIXED  # it carries the create, for the maintainer
    assert "MILESTONE_MISSING" not in ws.ACTION | ws.AGENT  # a watch exits 0 on it alone


def test_s068_9_the_skill_runs_the_close_under_watch_and_never_the_create() -> None:
    text = " ".join(SKILL.read_text(encoding="utf-8").split())
    released = text.split("| MILESTONE_RELEASED |", 1)[1].split(" | ", 1)[0]
    missing = text.split("| MILESTONE_MISSING |", 1)[1].split(" | ", 1)[0]
    assert 'Under "watch", run the fix once (as the App, hard rule 7)' in released
    assert "-f state=closed" in released
    assert "no watch pass runs this fix" in missing and "run the fix" not in missing
    assert "-X POST" in missing


def test_s068_9_status_says_the_close_waits_and_lists_the_create_on_its_milestone_line() -> None:
    ws = watch_state()
    rows = ws.milestone_rows(printed(RELEASED_ITEM | {"fix": CLOSE}, MISSING_ITEM | {"fix": CREATE}))
    parsed = shipmill_status.parse_rows("\n".join(json.dumps(r.json()) for r in rows))
    assert parsed == [
        Row("MILESTONE_RELEASED", "1.1.0", "d", False, CLOSE),
        Row("MILESTONE_MISSING", "1.1.1", "d", False, CREATE),
    ]
    assert "MILESTONE_RELEASED" in shipmill_status.YOURS_ROWS  # the verdict waits on the close
    assert "MILESTONE_MISSING" not in shipmill_status.YOURS_ROWS  # the create is no reason for it
    shown = lines(facts(*parsed))
    assert "  milestone      MILESTONE_RELEASED 1.1.0: d" in shown
    assert "  milestone      MILESTONE_MISSING 1.1.1: d" not in shown  # the label is on the first only
    under = " " * len("  milestone      ")  # the value column, under the label
    assert f"{under}MILESTONE_MISSING 1.1.1: d" in shown
    assert f"{under}fix: {CLOSE}" in shown and f"{under}fix: {CREATE}" in shown


def test_s068_9_the_readable_rows_differ_from_the_malformed_ones() -> None:
    found = watch_state().milestone_rows(printed(WAITING, OVERTAKEN, RELEASED_ITEM, MISSING_ITEM))
    assert [r.state for r in found] == [
        "MILESTONE_WAITING",
        "MILESTONE_OVERTAKEN",
        "MILESTONE_RELEASED",
        "MILESTONE_MISSING",
    ]


@pytest.mark.parametrize(
    "item",
    [
        RELEASED_ITEM | {"number": None},  # a close names its milestone's number
        RELEASED_ITEM | {"number": True},
        RELEASED_ITEM | {"next": "1.1.1"},  # a close renames nothing
        RELEASED_ITEM | {"fix": None},
        RELEASED_ITEM | {"fix": ""},
        MISSING_ITEM | {"number": 3},  # no milestone to number yet
        MISSING_ITEM | {"next": None},
        MISSING_ITEM | {"next": "1.2.0"},  # the subject is the version it creates
        MISSING_ITEM | {"fix": None},
    ],
)
def test_s068_9_a_released_or_missing_row_the_watch_cannot_read_stops_it(item: dict[str, object]) -> None:
    with pytest.raises(SystemExit) as refused:
        watch_state().milestone_rows(printed(item))
    assert refused.value.code == 2
