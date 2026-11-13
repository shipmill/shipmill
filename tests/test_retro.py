"""The github-ship-watch retro's comparison, PR classification, proposal dedupe, and report
per goal (spec 027), from fixtures"""

import argparse
import datetime as dt
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "github-ship-watch" / "scripts"
SCRIPT = SCRIPTS / "retro.py"
END = dt.datetime(2026, 10, 4, tzinfo=dt.timezone.utc)  # noqa: UP017 (runs under 3.10 too, as the script does)
START = END - dt.timedelta(days=7)
SHA = "a" * 40


@pytest.fixture(scope="module")
def rt() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))  # retro imports metrics, as when run from its folder
    try:
        spec = importlib.util.spec_from_file_location("retro", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # dataclasses look their module up by name
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


def day(n: float) -> str:
    return (END - dt.timedelta(days=n)).isoformat().replace("+00:00", "Z")


def pull(number: int, merged: str | None, closed: str, *reviews: tuple[str, str]) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"PR {number}",
        "url": f"https://github.com/o/r/pull/{number}",
        "mergedAt": merged,
        "closedAt": closed,
        "reviews": [{"author": {"login": login}, "state": state} for login, state in reviews],
    }


def test_proposals_matching_an_open_issue_are_duplicates(rt: ModuleType) -> None:
    issues = [{"number": 12, "title": "Add a check: CHANGELOG entries end with (#N)"}, {"number": 3, "title": "Other"}]
    titles = ["add a check  changelog entries end with #N.", "Teach the watch about stuck lanes"]
    verdicts = rt.dedupe(titles, issues)
    assert [(v.duplicate, v.existing) for v in verdicts] == [
        (12, "Add a check: CHANGELOG entries end with (#N)"),
        (None, ""),
    ]


def test_an_empty_proposal_title_is_refused(rt: ModuleType) -> None:
    with pytest.raises(SystemExit) as refused:
        rt.dedupe(["  ...  "], [])
    assert refused.value.code == 2


def test_two_proposals_with_one_title_are_refused(rt: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as refused:
        rt.dedupe(["Add a lint", "add a LINT."], [])
    assert refused.value.code == 2
    assert "two proposals share a title" in capsys.readouterr().err


def test_refused_and_reworked_pulls_are_the_windows(rt: ModuleType) -> None:
    pulls = [
        pull(1, None, day(2)),  # refused
        pull(2, None, day(9)),  # refused before the window
        pull(3, day(1), day(1), ("bob", "CHANGES_REQUESTED"), ("bob", "APPROVED"), ("amy", "CHANGES_REQUESTED")),
        pull(4, day(1), day(1), ("bob", "APPROVED")),  # merged as first reviewed
        pull(5, day(8), day(8), ("bob", "CHANGES_REQUESTED")),  # merged before the window
    ]
    refused, reworked = rt.classify(pulls, START, END)
    assert [(p.number, p.why) for p in refused] == [(1, "closed without a merge")]
    assert [(p.number, p.why) for p in reworked] == [(3, "changes requested by @amy, @bob")]


def measures(*pairs: tuple[str, str]) -> dict[str, Any]:
    return {"measures": [{"measure": name, "text": text} for name, text in pairs]}


def test_the_windows_compare_measure_by_measure(rt: ModuleType) -> None:
    previous = measures(("Lead time for changes", "median 2.0 d"), ("Deploy frequency", "no data"))
    current = measures(("Deploy frequency", "1.0 per week"), ("Lead time for changes", "median 1.0 d"))
    assert [(c.measure, c.previous, c.current) for c in rt.compare(previous, current)] == [
        ("Deploy frequency", "no data", "1.0 per week"),
        ("Lead time for changes", "median 2.0 d", "median 1.0 d"),
    ]
    with pytest.raises(SystemExit):
        rt.compare(measures(), current)


# -- the report per goal (spec 027) -------------------------------------------------------------


def iso(moment: dt.datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def report(end: dt.datetime, *found: dict[str, Any]) -> dict[str, Any]:
    """metrics.py's --json for the 7 days to end"""
    return {"start": iso(end - dt.timedelta(days=7)), "end": iso(end), "measures": list(found)}


def hours_measure(name: str, median: float | None, p90: float | None = None) -> dict[str, Any]:
    if median is None:
        return {"measure": name, "value": None, "unit": "hours", "text": "no data"}
    text = f"median {median:.1f} h, p90 {(p90 or median):.1f} h"
    return {"measure": name, "value": median, "unit": "hours", "text": text, "p90": p90 or median}


def ratio_measure(name: str, value: float | None) -> dict[str, Any]:
    text = "no data" if value is None else f"{value:.0%}"
    return {"measure": name, "value": value, "unit": "ratio", "text": text}


def measure(metric: str, comparison: str, target: float, unit: str, text: str) -> dict[str, Any]:
    return {"metric": metric, "comparison": comparison, "target": target, "unit": unit, "text": text}


def comment(body: str, when: str, association: str = "OWNER", login: str = "amy", kind: str = "User") -> dict[str, Any]:
    return {
        "body": body,
        "createdAt": when,
        "authorAssociation": association,
        "author": {"__typename": kind, "login": login},
    }


def issue(number: int, closed: str | None, *comments: dict[str, Any], reason: str = "COMPLETED") -> dict[str, Any]:
    return {
        "number": number,
        "state": "CLOSED" if closed else "OPEN",
        "stateReason": reason if closed else None,
        "closedAt": closed,
        "comments": {"pageInfo": {"hasPreviousPage": False, "startCursor": None}, "nodes": list(comments)},
    }


def merged(number: int, when: str, body: str, *messages: str) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"PR {number}",
        "url": f"https://github.com/o/r/pull/{number}",
        "body": body,
        "updatedAt": when,
        "mergedAt": when,
        "commits": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [{"commit": {"message": m}} for m in messages],
        },
    }


def plan(serves: str) -> str:
    return f"## Plan\n\n- Serves: {serves}\n- Files: a\n- Order: b\n- Proof: c\n\nSummary"


def connection(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}


def graphql(rt: ModuleType, issues: list[dict[str, Any]], pulls: list[dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def run(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if query == rt.ISSUES:
            return {"data": {"repository": {"issues": connection(issues)}}}
        assert query == rt.MERGED, query
        return {"data": {"repository": {"pullRequests": connection(pulls)}}}

    return run


def done(stdout: str = "", code: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


def commands(
    heads: str = f"{SHA}\n{SHA}\n", product: subprocess.CompletedProcess[str] | None = None, entered: str = ""
) -> tuple[list[list[str]], Callable[[list[str]], subprocess.CompletedProcess[str]]]:
    """A fake command run: git rev-parse prints heads, shipmill product show gives product,
    git log prints entered; every command is recorded"""
    ran: list[list[str]] = []

    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        ran.append(cmd)
        if cmd[0] == "git" and "rev-parse" in cmd:
            return done(heads)
        if cmd[0] == "git" and "log" in cmd:
            return done(entered)
        assert cmd[:3] == ["shipmill", "product", "show"], cmd
        assert product is not None
        return product

    return ran, run


def arguments(checkout: Path, **overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "repo": "o/r",
        "days": 7,
        "bot": ["shipmill-app[bot]"],
        "json": True,
        "goals": True,
        "checkout": checkout,
        "stalled_weeks": 3,
        "met_weeks": 4,
        "decisions": False,
        "raise_at": 2,
        "lower_after": 4,
        "role": [],
    }
    return argparse.Namespace(**{**values, **overrides})


def sources(rt: ModuleType, run: Callable[[list[str]], Any], **kw: Any) -> Any:
    reports: list[dict[str, Any]] = kw.pop("reports", [report(END), report(START)])
    asked: list[str | None] = kw.pop("asked", [])

    def metrics(until: str | None) -> dict[str, Any]:
        asked.append(until)
        return reports.pop(0)

    return rt.Sources(lambda cmd: [], metrics, command=run, shipmill=("shipmill",), **kw)


def test_s027_7_no_direction_reports_false_and_exits_0(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, run = commands()
    assert rt.gather(arguments(tmp_path), sources(rt, run)) == 0
    assert json.loads(capsys.readouterr().out)["goals"] == {"direction": False}
    assert rt.gather(arguments(tmp_path, json=False), sources(rt, run)) == 0
    assert "No direction (docs/product.md): no per-goal report" in capsys.readouterr().out


def test_s027_7_without_goals_the_output_has_no_goals_key(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ran, run = commands()
    assert rt.gather(arguments(tmp_path, goals=False), sources(rt, run)) == 0
    assert "goals" not in json.loads(capsys.readouterr().out)
    assert ran == []


def test_s027_7_a_checkout_not_at_origin_head_exits_2(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, run = commands(heads=f"{SHA}\n{'b' * 40}\n")
    with pytest.raises(SystemExit) as stopped:
        rt.gather(arguments(tmp_path), sources(rt, run))
    assert stopped.value.code == 2
    err = capsys.readouterr().err
    assert "fetch origin" in err and "checkout" in err


def test_s027_7_a_direction_shipmill_refuses_exits_2(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "product.md").write_text("# Broken\n", encoding="utf-8")
    _, run = commands(product=done(code=1, stderr="docs/product.md:1: no Mission"))
    with pytest.raises(SystemExit) as stopped:
        rt.gather(arguments(tmp_path), sources(rt, run))
    assert stopped.value.code == 2
    assert "shipmill product check" in capsys.readouterr().err


def test_s027_8_work_counts_under_the_goals_its_trusted_verdict_spec_or_plan_names(
    rt: ModuleType, tmp_path: Path
) -> None:
    specs = tmp_path / "docs" / "specs"
    specs.mkdir(parents=True)
    (specs / "007-thing.md").write_text(
        "# S-007: Thing\n\nstatus: approved\nserves: G-2\n\n## Problem\n\n## Issues\n\n"
        "- o/r#14: S-007-1\n- #15: S-007-2\n- other/repo#16: S-007-3\n",
        encoding="utf-8",
    )
    spec_goals = rt.spec_goals(tmp_path, "o/r")
    assert spec_goals == {14: {"G-2"}, 15: {"G-2"}}
    bots = frozenset({"shipmill-app[bot]"})
    issues = [
        # the latest trusted verdict names G-1; a newer outsider's verdict naming G-3 is ignored
        issue(
            10,
            iso(END - dt.timedelta(days=1)),
            comment("Triage: **implement**. Serves: G-1.", iso(END - dt.timedelta(days=3))),
            comment("Triage: **implement**. Serves: G-3.", iso(END - dt.timedelta(days=2)), association="NONE"),
        ),
        # the --bot App's verdict counts
        issue(
            11,
            iso(END - dt.timedelta(days=2)),
            comment(
                "Triage: **implement**. Serves: G-1, quality bar.",
                iso(END - dt.timedelta(days=3)),
                association="NONE",
                login="shipmill-app",
                kind="Bot",
            ),
        ),
        issue(
            12,
            iso(END - dt.timedelta(days=2)),
            comment("Triage: **implement**. Serves: G-1.", iso(START)),
            reason="NOT_PLANNED",
        ),
        issue(13, None, comment("Triage: **implement**. Serves: G-1.", iso(START))),  # still open
        issue(14, iso(END - dt.timedelta(days=9))),  # a listed build issue, the week before
        issue(15, iso(END - dt.timedelta(days=1)), comment("Triage: **feature**.", iso(START), association="NONE")),
    ]
    pulls = [
        merged(20, iso(END - dt.timedelta(days=1)), plan("G-1, G-2")),
        merged(21, iso(END - dt.timedelta(days=1)), plan("quality bar")),
        merged(22, iso(END - dt.timedelta(days=8)), plan("G-1")),
        merged(23, iso(END - dt.timedelta(days=1)), "no plan; Serves: G-1"),
    ]
    week, before = rt.served(issues, pulls, rt.weeks(END, 7, 2), spec_goals, bots)
    assert week.row("G-1") == {"issues": [10, 11], "pulls": [20]}
    assert week.row("G-2") == {"issues": [15], "pulls": [20]}
    assert week.row("G-3") == {"issues": [], "pulls": []}
    assert week.row("quality bar") == {"issues": [11], "pulls": [21]}
    assert before.counts("G-1") == {"issues": 0, "pulls": 1}
    assert before.counts("G-2") == {"issues": 1, "pulls": 0}


def test_s027_8_a_plan_is_read_as_the_gate_reads_it(rt: ModuleType) -> None:
    assert rt.plan_serves(plan("G-1, quality bar")) == {"G-1", "quality bar"}
    assert rt.plan_serves("```\n## Plan\n- Serves: G-1\n```") == set()  # in a fence
    assert rt.plan_serves(plan("G-1") + "\n" + plan("G-2")) == set()  # two plans
    assert rt.plan_serves(None) == set()


def test_a_plan_serving_quality_bar_ids_counts_as_the_quality_bar(rt: ModuleType) -> None:
    """#1016: the gate passes `Q-6` and `quality bar (Q-4, Q-6)`; the retro rows them as the quality bar"""
    assert rt.plan_serves(plan("Q-6")) == {"quality bar"}
    assert rt.plan_serves(plan("G-1, quality bar (Q-4, Q-6)")) == {"G-1", "quality bar"}


def test_s027_9_status_compares_in_the_metrics_unit(rt: ModuleType) -> None:
    week = report(
        END,
        hours_measure("Issue to release", 20.0, 40.0),
        ratio_measure("Human touch", 0.2),
        hours_measure("Time to restore", None),
    )
    fast = measure("issue_to_release_median", "<", 24.0, "hours", "issue_to_release_median < 1d")
    slow_p90 = measure("issue_to_release_p90", "<", 24.0, "hours", "issue_to_release_p90 < 1d")
    touch = measure("human_touch", "<=", 0.2, "ratio", "human_touch <= 20%")
    restore = measure("time_to_restore_median", "<", 4.0, "hours", "time_to_restore_median < 4h")
    assert rt.status(fast, week) == ("met", 20.0, "median 20.0 h")
    assert rt.status(slow_p90, week) == ("not met", 40.0, "p90 40.0 h")
    assert rt.status(touch, week) == ("met", 0.2, "20%")
    assert rt.status(restore, week) == ("no data", None, "no data")
    assert rt.status(None, week) == ("no measure", None, None)


def test_s027_9_met_weeks_counts_back_and_asks_only_while_a_goal_is_met(rt: ModuleType) -> None:
    touch = measure("human_touch", "<=", 0.2, "ratio", "human_touch <= 20%")
    goals = [{"id": "G-1", "text": "a", "measure": touch}, {"id": "G-2", "text": "b", "measure": None}]
    values = [0.1, 0.2, 0.5, 0.1, 0.1]
    asked: list[int] = []

    def back(k: int) -> dict[str, Any]:
        asked.append(k)
        return report(END - dt.timedelta(days=7 * k), ratio_measure("Human touch", values[k]))

    assert rt.met_streaks(goals, back, 5) == {"G-1": 2}
    assert asked == [0, 1, 2]
    asked.clear()
    assert rt.met_streaks(goals[1:], back, 5) == {}
    assert asked == []


def test_s027_9_no_measure_runs_no_extra_week_and_a_measure_does(rt: ModuleType, tmp_path: Path) -> None:
    def direction(m: dict[str, Any] | None) -> dict[str, Any]:
        return {"goals": [{"id": "G-1", "text": "a", "measure": m}]}

    met = [report(END - dt.timedelta(days=7 * k), ratio_measure("Human touch", 0.1)) for k in range(4)]
    _, run = commands(entered=iso(END - dt.timedelta(days=100)))
    asked: list[str | None] = []
    src = sources(rt, run, graphql=graphql(rt, [], []), reports=met[2:], asked=asked)
    rt.goals_report(arguments(tmp_path), src, direction(None), met[:2])
    assert asked == []
    touch = measure("human_touch", "<=", 0.2, "ratio", "human_touch <= 20%")
    found = rt.goals_report(arguments(tmp_path), src, direction(touch), met[:2])
    assert asked == [met[1]["start"], met[2]["start"]]  # each earlier week ends where the later starts
    assert (found["goals"][0]["status"], found["goals"][0]["met_weeks"]) == ("met", 4)


def test_s027_10_a_goal_unserved_for_the_weeks_is_stalled_unless_it_is_new(rt: ModuleType, tmp_path: Path) -> None:
    direction = {"goals": [{"id": "G-1", "text": "a"}, {"id": "G-2", "text": "b", "measure": None}]}
    pulls = [merged(30, iso(END - dt.timedelta(days=16)), plan("G-2"))]  # G-2 served three weeks back
    for entered, stalled in ((END - dt.timedelta(days=30), True), (END - dt.timedelta(days=10), False)):
        ran, run = commands(entered=iso(entered) + "\n" + iso(END))
        src = sources(rt, run, graphql=graphql(rt, [], pulls))
        found = rt.goals_report(arguments(tmp_path), src, direction, [report(END), report(START)])
        rows = {g["id"]: g for g in found["goals"]}
        assert (rows["G-1"]["stalled"], rows["G-1"]["weeks_unserved"]) == (stalled, 3)
        assert (rows["G-2"]["stalled"], rows["G-2"]["weeks_unserved"]) == (False, 2)
        assert rows["G-1"]["status"] == "no measure"
        assert [c for c in ran if "log" in c] == [
            [
                "git",
                "-C",
                str(tmp_path),
                "log",
                "--reverse",
                "--format=%cI",
                "-G",
                "^- G-1: ",
                "--",
                "docs/product.md",
                "docs/product",
            ]
        ]


def test_s027_11_off_direction_verdicts_and_unlinked_agent_pulls(rt: ModuleType, tmp_path: Path) -> None:
    direction = {"goals": [{"id": "G-1", "text": "a", "measure": None}]}
    day1, day9 = iso(END - dt.timedelta(days=1)), iso(END - dt.timedelta(days=9))
    hits = 'Triage: **won\'t fix**: it hits {}, "words". Why.'
    issues = [
        issue(40, None, comment("Triage: **postponed**: it serves no goal of the direction. It asks for x.", day1)),
        issue(41, day1, comment(hits.format("N-3"), day1), reason="NOT_PLANNED"),
        issue(42, day1, comment(hits.format("N-2"), day1), reason="NOT_PLANNED"),
        issue(43, day1, comment(hits.format("N-3"), day1), reason="NOT_PLANNED"),
        issue(44, day1, comment(hits.format("N-2"), day1), reason="NOT_PLANNED"),
        issue(45, day1, comment(hits.format("N-9"), day1, association="NONE"), reason="NOT_PLANNED"),  # untrusted
        issue(46, None, comment(hits.format("N-4"), day9)),  # the week before
        # postponed, then implemented: its latest verdict is not off direction
        issue(
            47,
            None,
            comment("Triage: **postponed**: it serves no goal of the direction.", day9),
            comment("Triage: **implement**.", day1),
        ),
    ]
    agent = "\n\nGenerated with [Claude Code](https://claude.com/claude-code)"
    pulls = [
        merged(50, day1, "Fix it" + agent),  # agent-made, no plan: unlinked
        merged(51, day1, plan("G-9") + agent),  # names a goal the direction doesn't list
        merged(52, day1, plan("G-1") + agent),
        merged(53, day1, plan("quality bar") + agent),
        merged(54, day1, "A person's change"),
        merged(55, day1, "Trailer only", "Fix\n\nCo-Authored-By: Claude Opus <noreply@anthropic.com>"),
    ]
    _, run = commands()
    src = sources(rt, run, graphql=graphql(rt, issues, pulls))
    found = rt.goals_report(arguments(tmp_path), src, direction, [report(END), report(START)])
    off = found["off_direction"]
    assert off["postponed"] == [40]
    assert off["wont_fix"] == [
        {"number": 41, "non_goal": "N-3"},
        {"number": 42, "non_goal": "N-2"},
        {"number": 43, "non_goal": "N-3"},
        {"number": 44, "non_goal": "N-2"},
    ]
    assert off["top_non_goal"] == "N-2"  # two each: the lowest id
    assert off["previous"] == {"postponed": 0, "wont_fix": 1, "top_non_goal": "N-4"}
    assert [u["number"] for u in found["unlinked"]] == [50, 51, 55]
    assert found["quality_bar"] == {"issues": [], "pulls": [53], "previous": {"issues": 0, "pulls": 0}}
    text = "\n".join(rt.goals_text(found))
    assert "most cited N-2" in text and "#50 PR 50" in text


def test_s027_12_the_weekly_retro_reports_goals_and_proposes_but_never_edits_the_direction() -> None:
    skill = (SCRIPTS.parent / "SKILL.md").read_text(encoding="utf-8")
    retro = " ".join(skill.split("## Weekly retro\n", 1)[1].split("\n## ", 1)[0].split())
    flags = subprocess.run(
        [sys.executable, str(SCRIPT), "gather", "--help"], capture_output=True, text=True, check=True
    ).stdout
    for flag in ("--goals", "--checkout", "--met-weeks", "--stalled-weeks", "--bot"):
        assert f"{flag} " in flags and flag in retro, flag  # the skill names only flags gather has
    assert "Always pass `--goals --checkout <dir>`, a checkout of the repo fetched and at `origin/<default>`" in retro
    assert "with `[agents] app_id` also pass `--bot <slug>[bot]`, the App that posts triage's verdicts" in retro
    assert "a section **Goals**: a row per goal (id, served this week and the week before, measure status" in retro
    assert "the quality-bar row, the off-direction counts with the most-cited non-goal, and the unlinked" in retro
    assert "Without a direction it says so in one line" in retro
    assert "`met_weeks` reached `--met-weeks`: `Direction: G-n met for N weeks`" in retro
    assert "`stalled` is true: `Direction: G-n stalled for N weeks`" in retro
    assert "`scripts/retro.py dedupe <owner/repo> --title" in retro
    assert "At most one is open per goal: dedupe passes both of the goal's titles" in retro
    assert (
        "It never edits `docs/product.md` or `docs/product/`, never runs a `shipmill product` edit command"
        " (`add`, `edit`, `retire`, `measure`), and never opens a pull request that changes the direction"
    ) in retro


# -- issue to release by stage (spec 066) --------------------------------------------------------

STAGE_NAMES = ("Issue to PR opened", "PR opened to merged", "Merged to release")


def staged_week(
    end: dt.datetime,
    release: tuple[float, float] | None,
    lead: tuple[float, float] | None,
    stages: Mapping[str, tuple[float, float] | None],
    touch: float = 0.5,
) -> dict[str, Any]:
    """metrics.py's JSON with Issue to release, Lead time, Human touch, and the three stages
    after an issue's opening, each (median, p90) or None for no data"""
    found = [
        hours_measure("Lead time for changes", *(lead or (None,))),
        hours_measure("Issue to release", *(release or (None,))),
        *(hours_measure(name, *(stages.get(name) or (None,))) for name in STAGE_NAMES),
        ratio_measure("Human touch", touch),
    ]
    return report(end, *found)


def goal(n: int, metric: str, comparison: str, target: float, unit: str = "hours") -> dict[str, Any]:
    return {"id": f"G-{n}", "text": f"goal {n}", "measure": measure(metric, comparison, target, unit, f"{metric} x")}


def goal_rows(
    rt: ModuleType, tmp_path: Path, goals: list[dict[str, Any]], weeks: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    _, run = commands(entered=iso(END - dt.timedelta(days=100)))
    src = sources(rt, run, graphql=graphql(rt, [], []), reports=[])
    found = rt.goals_report(arguments(tmp_path), src, {"goals": goals}, weeks)
    return {g["id"]: g for g in found["goals"]}


def test_s066_8_metric_measures_maps_each_registry_metric_and_reads_metrics_py_json(
    rt: ModuleType, tmp_path: Path
) -> None:
    from shipmill.product import Metric, Unit

    from .test_metrics import data, staged, window

    assert set(rt.METRIC_MEASURES) == {m.value for m in Metric}
    stage_metrics = [m for m in Metric if m.value.startswith(("issue_to_agent_", "issue_to_pr", "pr_to_", "merge_to_"))]
    assert len(stage_metrics) == 12 and all(m.unit is Unit.HOURS for m in stage_metrics)
    mx = sys.modules["metrics"]  # loaded by retro, as when it runs
    w = window(mx)
    full = json.loads(mx.render("o/r", 30, w, mx.measures(staged(mx), w), "json"))
    empty = json.loads(mx.render("o/r", 30, w, mx.measures(data(mx), w), "json"))
    for metric in stage_metrics:
        name, key = rt.METRIC_MEASURES[metric.value]
        assert key == ("p90" if metric.value.endswith("_p90") else "value")
        found = next(m for m in full["measures"] if m["measure"] == name)
        value = float(found[key])
        assert rt.status(measure(metric.value, "<=", value, "hours", "x"), full)[:2] == ("met", value)
        assert rt.status(measure(metric.value, "<", value, "hours", "x"), full)[:2] == ("not met", value)
        assert rt.status(measure(metric.value, "<", value, "hours", "x"), empty)[:2] == ("no data", None)


def test_s066_9_a_missed_lead_time_goal_names_the_stage_that_grew_most(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # medians grow 2, 8, 1 h; p90s grow 15, 2, 9 h
    now = {"Issue to PR opened": (10.0, 20.0), "PR opened to merged": (12.0, 30.0), "Merged to release": (8.0, 10.0)}
    before = {"Issue to PR opened": (8.0, 5.0), "PR opened to merged": (4.0, 28.0), "Merged to release": (7.0, 1.0)}
    weeks = [staged_week(END, (30.0, 60.0), (20.0, 40.0), now), staged_week(START, (19.0, 34.0), (8.0, 29.0), before)]
    goals = [
        goal(1, "issue_to_release_median", "<", 1.0),
        goal(2, "issue_to_release_p90", "<", 1.0),
        goal(3, "lead_time_median", "<", 1.0),
        goal(4, "lead_time_p90", "<", 1.0),  # Issue to PR opened grew most, but isn't a lead-time stage
    ]
    rows = goal_rows(rt, tmp_path, goals, weeks)
    assert {k: r["grew_most"] for k, r in rows.items()} == {
        "G-1": {"measure": "PR opened to merged", "statistic": "median", "value": 12.0, "previous": 4.0, "change": 8.0},
        "G-2": {"measure": "Issue to PR opened", "statistic": "p90", "value": 20.0, "previous": 5.0, "change": 15.0},
        "G-3": {"measure": "PR opened to merged", "statistic": "median", "value": 12.0, "previous": 4.0, "change": 8.0},
        "G-4": {"measure": "Merged to release", "statistic": "p90", "value": 10.0, "previous": 1.0, "change": 9.0},
    }
    text = rt.goals_text({"direction": True, "goals": list(rows.values()), **EMPTY_GOALS_REST})
    assert "    grew most: PR opened to merged, median 4.0 h to 12.0 h" in text
    assert "    grew most: Issue to PR opened, p90 5.0 h to 20.0 h" in text


EMPTY_GOALS_REST: dict[str, Any] = {
    "quality_bar": {"issues": [], "pulls": [], "previous": {"issues": 0, "pulls": 0}},
    "off_direction": {
        "postponed": [],
        "wont_fix": [],
        "top_non_goal": None,
        "previous": {"postponed": 0, "wont_fix": 0, "top_non_goal": None},
    },
    "unlinked": [],
}


def test_s066_10_grew_most_skips_missing_stages_ties_to_the_earlier_and_is_null_when_none_compares(
    rt: ModuleType,
) -> None:
    def week(end: dt.datetime, stages: Mapping[str, tuple[float, float] | None]) -> dict[str, Any]:
        return staged_week(end, (30.0, 60.0), (20.0, 40.0), stages)

    tie = {"Issue to PR opened": (10.0, 1.0), "PR opened to merged": (5.0, 1.0), "Merged to release": (9.0, 1.0)}
    was = {"Issue to PR opened": (4.0, 1.0), "PR opened to merged": (4.0, 1.0), "Merged to release": (3.0, 1.0)}
    assert rt.grew_most("issue_to_release_median", week(END, tie), week(START, was))["measure"] == "Issue to PR opened"
    # Issue to PR opened grew most but has no data the week before; Merged to release none this week
    missing = {**was, "Issue to PR opened": None}
    found = rt.grew_most("issue_to_release_median", week(END, {**tie, "Merged to release": None}), week(START, missing))
    assert found == {
        "measure": "PR opened to merged",
        "statistic": "median",
        "value": 5.0,
        "previous": 4.0,
        "change": 1.0,
    }
    shrunk = rt.grew_most("lead_time_median", week(END, was), week(START, tie))  # every stage shrank: the least
    assert (shrunk["measure"], shrunk["change"]) == ("PR opened to merged", -1.0)
    assert rt.grew_most("issue_to_release_p90", week(END, tie), week(START, {})) is None
    assert rt.grew_most_text(None) == "grew most: no stage to compare"


def test_s066_10_grew_most_is_absent_unless_a_lead_time_goal_is_missed(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = {"Issue to PR opened": (10.0, 20.0), "PR opened to merged": (12.0, 30.0), "Merged to release": (8.0, 10.0)}
    weeks = [staged_week(END, (30.0, 60.0), None, now), staged_week(START, (200.0, 300.0), None, {})]
    goals = [
        goal(1, "issue_to_release_median", "<", 100.0),  # met
        goal(2, "lead_time_median", "<", 1.0),  # no data
        goal(3, "human_touch", "<=", 0.1, "ratio"),  # not met, not a lead-time metric
        goal(4, "pr_to_merge_median", "<", 1.0),  # not met, a stage, not a lead-time metric
        goal(5, "issue_to_release_p90", "<", 1.0),  # not met, no stage the week before
    ]
    rows = goal_rows(rt, tmp_path, goals, weeks)
    assert [r["status"] for r in rows.values()] == ["met", "no data", "not met", "not met", "not met"]
    assert [k for k, r in rows.items() if "grew_most" in r] == ["G-5"]
    assert rows["G-5"]["grew_most"] is None
    text = rt.goals_text({"direction": True, "goals": list(rows.values()), **EMPTY_GOALS_REST})
    assert text.count("    grew most: no stage to compare") == 1
    assert sum("grew most" in line for line in text) == 1


def test_s066_11_the_retro_and_setup_skills_name_the_grew_most_line_and_the_stage_metrics() -> None:
    from shipmill.product import Metric

    skill = (SCRIPTS.parent / "SKILL.md").read_text(encoding="utf-8")
    retro = " ".join(skill.split("## Weekly retro\n", 1)[1].split("\n## ", 1)[0].split())
    goals_row = retro.split("a section **Goals**: a row per goal (", 1)[1].split("), then the quality-bar row", 1)[0]
    assert "`grew most: <measure>, <statistic> <previous> to <value>`" in goals_row
    assert "`grew most: no stage to compare`" in goals_row
    setup = " ".join((SCRIPTS.parents[1] / "shipmill-setup" / "SKILL.md").read_text(encoding="utf-8").split())
    offered = setup.split("offer a measure from the registry", 1)[1].split("Write only the measures", 1)[0]
    stages = [m.value for m in Metric if m.value.startswith(("issue_to_agent_", "issue_to_pr", "pr_to_", "merge_to_"))]
    assert len(stages) == 12
    for metric in stages:
        assert f"`{metric}`" in offered, metric


# -- the report per zone of the decision policy (spec 030) ---------------------------------------

BOT = "shipmill-app"


def bot(body: str, when: str) -> dict[str, Any]:
    return comment(body, when, association="NONE", login=BOT, kind="Bot")


def thread(number: int, *comments: dict[str, Any], cursor: str | None = None) -> dict[str, Any]:
    newest = max((c["createdAt"] for c in comments), default=iso(END))
    page = {"hasPreviousPage": cursor is not None, "startCursor": cursor}
    return {"number": number, "updatedAt": newest, "comments": {"pageInfo": page, "nodes": list(comments)}}


def decided(zone: str) -> str:
    return f"<!-- shipmill:decided zone={zone} until=2026-10-04T00:00:00Z -->\n@amy Decided without waiting: x"


def asked(zone: str, answer: str = "") -> str:
    line = f"<!-- shipmill:zone {zone} answer={answer} -->" if answer else f"<!-- shipmill:zone {zone} -->"
    return f"<!-- shipmill:needs-decision -->\n{line}\n@amy Decision needed: x"


def handled(zone: str) -> str:
    return f"<!-- shipmill:veto-handled zone={zone} -->\nReverted in #9."


def thread_graphql(
    rt: ModuleType,
    issues: list[dict[str, Any]],
    pulls: list[dict[str, Any]],
    older: dict[int, list[dict[str, Any]]] | None = None,
) -> Callable[..., dict[str, Any]]:
    def run(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if query == rt.ISSUE_THREADS:
            return {"data": {"repository": {"issues": connection(issues)}}}
        if query == rt.PULL_THREADS:
            return {"data": {"repository": {"pullRequests": connection(pulls)}}}
        assert query == rt.PULL_COMMENTS, query
        page = {
            "pageInfo": {"hasPreviousPage": False, "startCursor": None},
            "nodes": (older or {})[variables["number"]],
        }
        return {"data": {"repository": {"pullRequest": {"comments": page}}}}

    return run


def policy_args(checkout: Path, **overrides: Any) -> argparse.Namespace:
    values = {"goals": False, "decisions": True, "bot": [f"{BOT}[bot]"], **overrides}
    return arguments(checkout, **values)


def test_s030_18_gather_counts_each_zones_markers_in_the_window(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    day1, day3, day9 = iso(END - dt.timedelta(days=1)), iso(END - dt.timedelta(days=3)), iso(END - dt.timedelta(days=9))
    issues = [
        thread(
            60,
            bot(decided("interpretation"), day3),
            bot(handled("interpretation"), day1),
            comment(handled("interpretation"), day1, association="NONE", login="outsider"),  # untrusted
            bot("See above.\n" + decided("interpretation"), day1),  # a marker mid-comment
            bot(decided("interpretations"), day1),  # no zone id
        ),
    ]
    pulls = [
        thread(
            70,
            bot(asked("scope", "recommended"), day1),
            bot(asked("contract-change", "recommended"), day1),
            bot("<!-- shipmill:needs-decision -->\n@amy Decision needed: unzoned", day1),
            cursor="c1",
        ),
    ]
    older = {
        70: [
            bot(asked("scope", "other"), day3),
            bot(decided("triage-verdict"), day9),  # the week before
            bot(asked("contract-change", "recommended"), day9),
        ]
    }
    _, run = commands()
    src = sources(rt, run, graphql=thread_graphql(rt, issues, pulls, older))
    assert rt.gather(policy_args(tmp_path), src) == 0
    report = json.loads(capsys.readouterr().out)["decisions"]
    rows = {z["zone"]: z for z in report["zones"]}
    assert (report["veto_hours"], report["windows"]) == (24, 4)
    assert list(rows) == list(rt.decisions_module().ZONES)
    pick = ("level", "decided", "vetoes", "asks", "recommended", "asks_over_windows", "recommended_over_windows")
    assert [rows["interpretation"][k] for k in pick] == ["notify", 1, 1, 0, 0, 0, 0]
    assert [rows["scope"][k] for k in pick] == ["ask", 0, 0, 2, 1, 2, 1]
    assert [rows["contract-change"][k] for k in pick] == ["ask", 0, 0, 1, 1, 2, 2]
    assert [rows["triage-verdict"][k] for k in pick] == ["notify", 0, 0, 0, 0, 0, 0]
    assert rows["scope"]["floor"] == "ask" and rows["contract-change"]["floor"] is None
    assert report["unknown_zones"] == [{"kind": "issue", "number": 60, "zone": "interpretations"}]
    assert report["proposals"] == []
    src = sources(rt, run, graphql=thread_graphql(rt, issues, pulls, older))
    assert rt.gather(policy_args(tmp_path, json=False), src) == 0
    text = capsys.readouterr().out
    assert "Decisions (veto window 24 h; questions over 4 windows):" in text
    assert "  scope (ask): decided 0, vetoes 0, asks 2 (1 recommended); over the windows 2 asks (1 recommended)" in text
    assert "a marker on #60 names no zone id: interpretations" in text and "Proposals: none" in text


def test_s030_18_gather_reads_the_levels_from_the_checkouts_config(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".github").mkdir()
    config = tmp_path / ".github" / "shipmill.toml"
    config.write_text('[decisions]\nveto_hours = 12\ncontract-change = "notify"\n', encoding="utf-8")
    day1 = iso(END - dt.timedelta(days=1))
    issues = [thread(61, bot(handled("contract-change"), day1), bot(handled("contract-change"), day1))]
    _, run = commands()
    src = sources(rt, run, graphql=thread_graphql(rt, issues, []))
    assert rt.gather(policy_args(tmp_path), src) == 0
    report = json.loads(capsys.readouterr().out)["decisions"]
    assert report["veto_hours"] == 12
    assert report["proposals"] == [
        {
            "zone": "contract-change",
            "from": "notify",
            "to": "ask",
            "title": "Decision policy: contract-change from notify to ask",
            "why": "2 vetoes this window, at least 2",
        }
    ]
    config.write_text('[decisions]\nscope = "notify"\n', encoding="utf-8")
    with pytest.raises(SystemExit) as stopped:
        rt.gather(policy_args(tmp_path), sources(rt, run))
    assert stopped.value.code == 2
    assert "scope = 'notify' is below its floor ask" in capsys.readouterr().err
    _, elsewhere = commands(heads=f"{SHA}\n{'b' * 40}\n")
    with pytest.raises(SystemExit) as stopped:
        rt.gather(policy_args(tmp_path), sources(rt, elsewhere))
    assert stopped.value.code == 2
    assert "fetch origin" in capsys.readouterr().err


def test_s030_18_proposals_raise_at_vetoes_and_lower_only_after_every_question_was_recommended(
    rt: ModuleType,
) -> None:
    zones = rt.decisions_module().ZONES
    levels = {zone: default for zone, (default, _) in zones.items()}
    policy = rt.Levels(levels, {zone: floor for zone, (_, floor) in zones.items()}, 24)

    def counts(**per_zone: list[tuple[int, int, int]]) -> list[dict[str, dict[str, int]]]:
        """per zone, per window back from this one: (vetoes, asks, recommended)"""
        windows = [{z: dict.fromkeys(rt.COUNTS, 0) for z in zones} for _ in range(5)]
        for zone, weeks_back in per_zone.items():
            for week, (vetoes, asks, recommended) in zip(windows, weeks_back, strict=False):
                week[zone.replace("_", "-")].update(vetoes=vetoes, asks=asks, recommended=recommended)
        return windows

    def titles(found: list[dict[str, dict[str, int]]], raise_at: int = 2, lower_after: int = 4) -> list[str]:
        return [p["title"] for p in rt.decision_proposals(policy, found, raise_at, lower_after)]

    # notify zones: raised at --raise-at vetoes this window; last week's vetoes don't count
    assert titles(counts(interpretation=[(2, 0, 0)])) == ["Decision policy: interpretation from notify to ask"]
    assert titles(counts(interpretation=[(1, 0, 0), (3, 0, 0)])) == []
    assert titles(counts(interpretation=[(1, 0, 0)]), raise_at=1) == [
        "Decision policy: interpretation from notify to ask"
    ]
    # ask zones: lowered when at least 5 questions over the windows were all answered recommended
    five = [(0, 2, 2), (0, 1, 1), (0, 0, 0), (0, 2, 2)]
    assert titles(counts(contract_change=five)) == ["Decision policy: contract-change from ask to notify"]
    assert titles(counts(contract_change=[(0, 2, 2), (0, 2, 2)])) == []  # only 4
    assert titles(counts(contract_change=[(0, 3, 3), (0, 2, 1)])) == []  # one answered otherwise
    assert titles(counts(contract_change=[(0, 0, 0), (0, 2, 2), (0, 0, 0), (0, 0, 0), (0, 9, 9)])) == []  # too old
    assert titles(counts(contract_change=five), lower_after=3) == []  # 3 in the last 3 windows
    # never below the floor: scope, rule-departure, unknown sit at their floor ask; security's is notify
    assert titles(counts(scope=five, rule_departure=five, unknown=five)) == []
    assert titles(counts(security=five)) == ["Decision policy: security from ask to notify"]
    # a zone at act or never is never proposed
    assert titles(counts(implementation=[(5, 9, 9)] * 4, direction=[(5, 9, 9)] * 4)) == []


# -- an answer read from the thread when the zone line has no answer= (#997) ---------------------

AGENT = "\n\n<!-- shipmill:agent -->"
OPTIONS = (
    "\n\n1. Derive it in `retro.py` (recommended): every answer counts\n"
    "2. Keep the zone line: prose only\n\nReply here with a number or your own answer."
)


def question(answer: str = "") -> str:
    return asked("contract-change", answer) + OPTIONS + AGENT


def relay(answer: str, login: str = "`@amy`") -> str:
    return f"Decision by {login}, relayed by Claude Code\n\n{answer}{AGENT}"


def after(n: float) -> str:
    return iso(END - dt.timedelta(days=3) + dt.timedelta(hours=n))


ASKED = after(0)


@pytest.mark.parametrize(
    ("replies", "recommended"),
    [
        ([comment("1", after(1))], 1),  # a person's bare number
        ([comment("Option 1\n\nThanks.", after(1))], 1),  # its first line, the number alone
        ([comment("Derive it in retro.py", after(1), association="MEMBER")], 1),  # the option's name
        ([bot(relay("1."), after(1))], 1),  # the App's relay, the login in a code span
        ([bot(relay("Answered in the session: 1", "@amy"), after(1))], 1),  # the template, bare login
        ([comment("1, narrowed: only the retro", after(1))], 0),  # narrows the option
        ([bot(relay("1, but only these commands"), after(1))], 0),
        ([comment("2", after(1))], 0),  # another option
        ([comment("sounds good, do whatever", after(1))], 0),  # unreadable
        ([bot(relay(""), after(1))], 0),  # a relay with no answer line
        ([comment("2", after(1)), comment("1", after(2))], 0),  # the first answer counts
        ([comment("1", after(1), association="NONE", login="outsider")], 0),  # no trusted reply
        ([comment("1" + AGENT, after(1))], 0),  # the agent marker: an agent's text (D-62)
        ([bot(relay("1", "`@bob`"), after(1))], 0),  # a relay naming no maintainer
        ([comment("1", after(1), login=BOT, kind="Bot", association="NONE")], 0),  # the App, no relay
        ([bot(question(), after(1)), comment("1", after(2))], 1),  # of 2 asks: the reply answers the newer
        ([bot("Triage: implement." + AGENT, after(1)), comment("1.", after(2))], 1),  # agent text skipped
    ],
)
def test_s030_18_a_question_without_answer_reads_the_first_answer_after_it(
    rt: ModuleType, replies: list[dict[str, Any]], recommended: int
) -> None:
    threads = [{"kind": "issue", "number": 7, "comments": [bot(question(), ASKED), *replies]}]
    bots, maintainers = frozenset({f"{BOT}[bot]"}), frozenset({"amy"})
    counts, _ = rt.decision_counts(threads, rt.weeks(END, 7, 1), ["contract-change"], bots, maintainers)
    assert counts[0]["contract-change"]["asks"] >= 1
    assert counts[0]["contract-change"]["recommended"] == recommended


@pytest.mark.parametrize(("stated", "reply", "recommended"), [("other", "1", 0), ("recommended", "2", 1)])
def test_s030_18_an_explicit_answer_on_the_zone_line_wins_over_the_thread(
    rt: ModuleType, stated: str, reply: str, recommended: int
) -> None:
    threads = [{"kind": "issue", "number": 7, "comments": [bot(question(stated), ASKED), comment(reply, after(1))]}]
    counts, _ = rt.decision_counts(
        threads, rt.weeks(END, 7, 1), ["contract-change"], frozenset({f"{BOT}[bot]"}), frozenset({"amy"})
    )
    assert counts[0]["contract-change"]["recommended"] == recommended


def test_s030_18_gather_reads_a_relay_only_for_the_role_flags_maintainer(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    issues = [thread(62, bot(question(), ASKED), bot(relay("1"), after(1)))]
    _, run = commands()
    for role, recommended in ((["maintainer=amy,@o/team", "qa=bob"], 1), ([], 0)):
        src = sources(rt, run, graphql=thread_graphql(rt, issues, []))
        assert rt.gather(policy_args(tmp_path, role=role), src) == 0
        rows = {z["zone"]: z for z in json.loads(capsys.readouterr().out)["decisions"]["zones"]}
        assert (rows["contract-change"]["asks"], rows["contract-change"]["recommended"]) == (1, recommended)
    with pytest.raises(SystemExit) as stopped:
        rt.gather(policy_args(tmp_path, role=["qa=bob"]), sources(rt, run))
    assert stopped.value.code == 2
    assert "--role flags must include maintainer" in capsys.readouterr().err


def test_s030_18_the_relay_and_agent_marker_patterns_are_triage_states(rt: ModuleType) -> None:
    path = SCRIPTS.parent.parent / "github-issue-triage" / "scripts" / "triage_state.py"
    spec = importlib.util.spec_from_file_location("triage_state_for_retro", path)
    assert spec is not None and spec.loader is not None
    triage = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = triage
    spec.loader.exec_module(triage)
    assert rt.DECISION_BY.pattern == triage.DECISION_BY.pattern
    assert rt.AGENT_MARKER.pattern == triage.AGENT_MARKER.pattern
