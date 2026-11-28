"""Spec 110, the session and the docs: github-ship-watch's SKILL.md gives DIRECTION_DUE's step and
says the watch, not a scheduled retro, opens the direction proposals (S-110-9), and docs/flow.md
gives the GOALS and DIRECTION_DUE rows and the change to spec 027's choice (S-110-10)"""

import re
from pathlib import Path
from types import ModuleType

import pytest

from .test_status_plan_waits import load
from .test_watch_plans import WATCH_STATE

ROOT = Path(__file__).resolve().parents[1]


def folded(*parts: str) -> str:
    """The file's text with every run of whitespace one space, so a wrapped line reads as one"""
    return " ".join(ROOT.joinpath(*parts).read_text(encoding="utf-8").split())


def section(text: str, heading: str) -> str:
    start = text.index(f"{heading} ")
    end = text.find(" ## ", start + len(heading))
    return text[start : end if end != -1 else len(text)]


WATCH = folded("skills", "github-ship-watch", "SKILL.md")
FLOW = folded("docs", "flow.md")
STEP = section(WATCH, "## Direction proposals")
RETRO = section(WATCH, "## Weekly retro")


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load(WATCH_STATE, "watch_state_direction_proposal_docs")


def test_s110_9_the_step_dedupes_both_titles_the_watch_reads_before_opening(ws: ModuleType) -> None:
    met, stalled = ws.direction_titles("G-n")  # the titles the watch's DIRECTION_DUE reads as proposed
    assert (met, stalled) == ("Direction: G-n met for 4 weeks", "Direction: G-n stalled for 3 weeks")
    dedupe = f'`scripts/retro.py dedupe <owner/repo> --title "{met}" --title "{stalled}"`'
    assert dedupe in STEP
    opened = "Open the issue as the App (hard rule 7)"
    assert opened in STEP and STEP.index(dedupe) < STEP.index(opened)
    assert "On a DUPLICATE or a DECLINED for either title, open nothing for that goal" in STEP
    assert "only when both read NEW" in STEP
    # the row hands the session this step, not the retro's step 4
    lines = ROOT.joinpath("skills", "github-ship-watch", "SKILL.md").read_text(encoding="utf-8").splitlines()
    (row,) = [line for line in lines if line.startswith("| DIRECTION_DUE | From the same run")]
    assert 'Follow [Direction proposals](#direction-proposals) under "watch"' in row
    assert "step 4 says" not in row


def test_s110_9_the_body_cites_the_reading_and_the_maintainers_commands() -> None:
    body = section(STEP, "3. **Open the issue")
    assert "cites the goal's reading from the GOALS row: its status, its value, and the weeks" in body
    for command in (
        "`shipmill product retire G-n`",
        '`shipmill product measure G-n "<metric> <comparison> <target>"`',
        "`shipmill product met G-n`",
    ):
        assert command in body, command
    assert "says the direction changes only by the maintainer" in body
    assert re.search(r"`uvx shipmill==[\d.]+ gh issue create --title \"<title>\" --body-file <file>`", body)


def test_s110_9_the_step_writes_nothing_else() -> None:
    rest = section(STEP, "4. **Write nothing else.**")
    for never in (
        "no comment on a tracking issue",
        "no edit of `docs/product.md` or `docs/product/`",
        "no `shipmill product` edit command (`add`, `edit`, `retire`, `measure`, `met`, `drop`)",
        "no pull request (D-34)",
        "no room under `[agents] wip` (D-32)",
    ):
        assert never in rest, never
    # nothing in the step itself runs a direction edit or opens a pull request
    assert not re.search(r"gh pr (create|edit|merge)", STEP)
    assert "shipmill/direction" not in STEP


def test_s110_9_the_retro_leaves_the_direction_proposals_to_the_watch() -> None:
    for said in (
        "The watch reads the goal report and opens the direction proposals on its own "
        "([Direction proposals](#direction-proposals), spec 110), so a repo needs no scheduled retro for them",
        "The rest of the retro (the metrics beside last week's, the rule proposals, the decision-policy "
        "proposals, the review records) is an option the user schedules, never a default",
        "A scheduled retro still reports the Goals section in its tracking comment, and its step 4 finds "
        "the watch's issue through `retro.py dedupe`",
    ):
        assert said in RETRO, said
    assert "The retro is an option the user schedules" not in RETRO


def test_s110_10_flow_gives_the_goals_and_direction_due_rows() -> None:
    goals = section(FLOW, "## Goals, plans, and projects")
    assert "the GOALS row, report only, gives each goal in the direction's order" in goals
    assert "`G-1 met (p90 1.2 d), 4 weeks; G-3 no measure, written`" in goals
    assert "(`met`, `not met`, `no data`, or `no measure`)" in goals
    assert "The DIRECTION_DUE row names each goal due for a direction proposal" in goals
    assert "`G-1 met for 4 weeks; G-6 stalled for 3 weeks`" in goals
    assert "`Direction: G-n met for 4 weeks` or `Direction: G-n stalled for 3 weeks`" in goals
    assert "in tier 7, right after PLANS" in goals
    assert "opens that issue as the App and nothing else: the direction changes only by you (D-34)" in goals


def test_s110_10_flow_states_the_change_to_spec_027s_choice() -> None:
    goals = section(FLOW, "## Goals, plans, and projects")
    assert (
        "This changes spec 027's choice that the weekly retro is an option you schedule, "
        "for the goal report and the direction proposals only" in goals
    )
    assert "the watch, which the gate runs on every sweep, reads the report and opens the proposals" in goals
    assert "the rest of the retro (the metrics beside last week's, rule proposals" in goals
    assert "stays an option you schedule" in goals
