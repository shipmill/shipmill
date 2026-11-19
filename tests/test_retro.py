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
        "lower_rate": 90,
        "lower_min": 10,
        "revert_days": 14,
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


def thread(
    number: int,
    *comments: dict[str, Any],
    cursor: str | None = None,
    reopened: tuple[str, ...] = (),
    title: str | None = None,
    body: str = "",
    merged_at: str | None = None,
) -> dict[str, Any]:
    """An issue or pull request node: an issue reads its reopenings, a pull its title, body,
    and merge time"""
    moments = [c["createdAt"] for c in comments] + list(reopened) + ([merged_at] if merged_at else [])
    page = {"hasPreviousPage": cursor is not None, "startCursor": cursor}
    return {
        "number": number,
        "updatedAt": max(moments, default=iso(END)),
        "comments": {"pageInfo": page, "nodes": list(comments)},
        "timelineItems": {"pageInfo": {"hasNextPage": False}, "nodes": [{"createdAt": r} for r in reopened]},
        "title": title or f"PR {number}",
        "body": body,
        "mergedAt": merged_at,
    }


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


def test_s067_10_gather_counts_accepted_spec_in_its_own_row_not_in_scope(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    day1, day3 = iso(END - dt.timedelta(days=1)), iso(END - dt.timedelta(days=3))
    pulls = [
        thread(
            71,
            bot(asked("accepted-spec", "recommended"), day3),
            bot(decided("accepted-spec"), day1),
            bot(asked("scope", "other"), day1),
        ),
    ]
    _, run = commands()
    src = sources(rt, run, graphql=thread_graphql(rt, [], pulls))
    assert rt.gather(policy_args(tmp_path), src) == 0
    report = json.loads(capsys.readouterr().out)["decisions"]
    zones = [z["zone"] for z in report["zones"]]
    assert zones[zones.index("scope") + 1] == "accepted-spec"
    rows = {z["zone"]: z for z in report["zones"]}
    pick = ("level", "floor", "decided", "asks", "answered", "recommended")
    assert [rows["accepted-spec"][k] for k in pick] == ["ask", "notify", 1, 1, 1, 1]
    assert [rows["scope"][k] for k in pick] == ["ask", "ask", 0, 1, 1, 0]
    assert report["unknown_zones"] == []


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


def default_policy(rt: ModuleType, **levels: str) -> Any:
    zones = rt.decisions_module().ZONES
    found = {zone: default for zone, (default, _) in zones.items()}
    found.update({zone.replace("_", "-"): level for zone, level in levels.items()})
    return rt.Levels(found, {zone: floor for zone, (_, floor) in zones.items()}, 24)


def zone_counts(rt: ModuleType, **per_zone: list[tuple[int, int, int]]) -> list[dict[str, dict[str, int]]]:
    """per zone, per window back from this one: (vetoes, answered, recommended); asks as answered"""
    zones = rt.decisions_module().ZONES
    windows = [{z: dict.fromkeys(rt.COUNTS, 0) for z in zones} for _ in range(5)]
    for zone, weeks_back in per_zone.items():
        for week, (vetoes, answered, recommended) in zip(windows, weeks_back, strict=False):
            week[zone.replace("_", "-")].update(
                vetoes=vetoes, asks=answered, answered=answered, recommended=recommended
            )
    return windows


def proposed(
    rt: ModuleType,
    found: list[dict[str, dict[str, int]]],
    policy: Any = None,
    raise_at: int = 2,
    lower_after: int = 4,
    lower_rate: int = 90,
    lower_min: int = 10,
) -> list[dict[str, str]]:
    policy = policy or default_policy(rt)
    result: list[dict[str, str]] = rt.decision_proposals(policy, found, raise_at, lower_after, lower_rate, lower_min)
    return result


def test_s030_18_proposals_raise_at_vetoes_and_lower_on_the_rate(rt: ModuleType) -> None:
    def titles(found: list[dict[str, dict[str, int]]], **kw: Any) -> list[str]:
        return [p["title"] for p in proposed(rt, found, **kw)]

    # notify zones: raised at --raise-at vetoes this window; last week's vetoes don't count
    assert titles(zone_counts(rt, interpretation=[(2, 0, 0)])) == ["Decision policy: interpretation from notify to ask"]
    assert titles(zone_counts(rt, interpretation=[(1, 0, 0), (3, 0, 0)])) == []
    assert titles(zone_counts(rt, interpretation=[(1, 0, 0)]), raise_at=1) == [
        "Decision policy: interpretation from notify to ask"
    ]
    # ask zones: lowered on the rate over the windows (spec 058)
    ten = [(0, 4, 4), (0, 3, 2), (0, 0, 0), (0, 3, 3)]
    assert titles(zone_counts(rt, contract_change=ten)) == ["Decision policy: contract-change from ask to notify"]
    too_old = [(0, 0, 0), (0, 4, 4), (0, 0, 0), (0, 0, 0), (0, 9, 9)]
    assert titles(zone_counts(rt, contract_change=too_old)) == []  # the fifth window is past --lower-after
    assert titles(zone_counts(rt, contract_change=ten), lower_after=3) == []  # 7 in the last 3 windows
    # a zone at act or never is never proposed
    assert titles(zone_counts(rt, implementation=[(5, 9, 9)] * 4, direction=[(5, 9, 9)] * 4)) == []


def test_s058_1_ask_to_notify_at_the_rate_over_the_minimum_sample(rt: ModuleType) -> None:
    nine_of_ten = [(0, 5, 5), (0, 5, 4)]
    assert proposed(rt, zone_counts(rt, contract_change=nine_of_ten)) == [
        {
            "zone": "contract-change",
            "from": "ask",
            "to": "notify",
            "title": "Decision policy: contract-change from ask to notify",
            "why": "9 of 10 answered questions (90%) over 4 windows took the recommended option,"
            " at least 90% of at least 10",
        }
    ]
    assert proposed(rt, zone_counts(rt, contract_change=[(0, 10, 9), (0, 10, 8)])) == []  # 17 of 20, 85%
    assert proposed(rt, zone_counts(rt, contract_change=[(0, 5, 5), (0, 4, 4)])) == []  # 9 of 9, below 10
    # the thresholds are the flags'
    assert proposed(rt, zone_counts(rt, contract_change=[(0, 10, 9), (0, 10, 8)]), lower_rate=85) != []
    assert proposed(rt, zone_counts(rt, contract_change=[(0, 5, 5), (0, 4, 4)]), lower_min=9) != []


def test_s058_3_never_below_a_floor_and_never_notify_to_act(rt: ModuleType) -> None:
    every = [(0, 20, 20)] * 4
    # scope, rule-departure, unknown sit at their floor ask at any rate; security's floor is notify
    assert proposed(rt, zone_counts(rt, scope=every, rule_departure=every, unknown=every)) == []
    assert proposed(rt, zone_counts(rt, scope=every), lower_rate=1, lower_min=1) == []
    assert [p["title"] for p in proposed(rt, zone_counts(rt, security=every))] == [
        "Decision policy: security from ask to notify"
    ]
    # a zone at notify, every question recommended, is never proposed act
    assert (
        proposed(rt, zone_counts(rt, interpretation=every, security=every), default_policy(rt, security="notify")) == []
    )


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
        ([bot(relay("Answered in the session: 1. Derive it in `retro.py`"), after(1))], 1),  # as listed (#1150)
        ([comment("1, narrowed: only the retro", after(1))], 0),  # narrows the option
        ([bot(relay("1, but only these commands"), after(1))], 0),
        ([comment("2", after(1))], 0),  # another option
        ([comment("sounds good, do whatever", after(1))], 0),  # unreadable
        ([bot(relay(""), after(1))], 0),  # a relay with no answer line
        ([bot(relay("1\n\nNote: checked in the session\n\nmore"), after(1))], 1),  # D-93: Note: ends it
        ([bot(relay("1\n\nBasis: round"), after(1))], 1),
        ([bot(relay("1\n\nbut rename it first"), after(1))], 0),  # out of the grammar: not counted
        ([bot(relay("own: Derive it in retro.py"), after(1))], 0),  # the person's own words
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
    counts = rt.decision_counts(threads, rt.weeks(END, 7, 1), ["contract-change"], bots, maintainers).counts
    assert counts[0]["contract-change"]["asks"] >= 1
    assert counts[0]["contract-change"]["recommended"] == recommended


@pytest.mark.parametrize(
    ("answer", "takes"),
    [
        ("1. Derive it in `retro.py`", True),  # the option as listed, number and text (#1150)
        ("1) Derive it in retro.py", True),
        ("1: Derive it in retro.py", True),
        ("Option 1: Derive it in retro.py", True),
        ("Option 1. Derive it in retro.py.", True),
        ("**1. Derive it in `retro.py`**", True),  # bold
        ("**1.** Derive it in retro.py", True),
        ("1. Derive it in `retro.py` (recommended)", True),  # with its mark repeated
        ("2. Derive it in retro.py", False),  # a number and a text naming different options
        ("1. Keep the zone line", False),
        ("2. Keep the zone line", False),  # another option, as listed
        ("1. Derive it in retro.py but rename the count", False),  # extra words after the option
        ("1. Derive it in retro.py, only the asks", False),  # narrows it
        ("1. Derive it", False),  # a prefix of its text
        ("1. Derive it in retro.py (recommended): every answer counts", False),  # past the mark
        ("1.Derive it in retro.py", False),  # no space after the number's stop
        ("1", True),  # the number alone and the text alone stay as they were
        ("Option 1", True),
        ("Derive it in retro.py", True),
        ("Derive it", False),
    ],
)
def test_s055_19_the_option_as_listed_number_and_text_takes_it(rt: ModuleType, answer: str, takes: bool) -> None:
    assert rt.takes_recommended(OPTIONS, answer) is takes


@pytest.mark.parametrize(
    ("answer", "read"),
    [
        ("1", ("1", False, None, None)),  # a header and one line, as before
        ("Answered in the session: 1", ("1", False, None, None)),
        ("Answered in the session:\n\n1", ("1", False, None, None)),
        ("", ("", False, None, None)),
        ("1\n\nNote: approved in chat\n\nwhatever follows", ("1", False, None, None)),
        ("1\n\nBasis: round", ("1", False, "round", None)),
        ("1\n\nBasis: standing\n\nNote: x", ("1", False, "standing", None)),
        ("own: only h2", ("only h2", True, None, None)),
        ("Answered in the session: own: only h2\n\nBasis: item", ("only h2", True, "item", None)),
        ("1\n\nmore words", ("1", False, None, "format")),
        ("1\n\n<!-- shipmill:zone scope -->\n\nNote: x", ("1", False, None, "format")),
        ("1\n\nBasis: sometimes", ("1", False, None, "format")),
        ("own:", ("", True, None, "format")),
        ("1 Note: inline", ("1 Note: inline", False, None, None)),  # Note: inside the answer line
    ],
)
def test_d93_parse_relay_reads_the_relay_grammar(rt: ModuleType, answer: str, read: tuple[Any, ...]) -> None:
    found = rt.parse_relay(relay(answer))
    assert (found.answer, found.own, found.basis, found.refused) == read


@pytest.mark.parametrize(
    ("answer", "why"),
    [
        ("1. Take every recommendation: extra words", "format"),  # names no option of the question
        ("1. Take every recommendation and more", "format"),
        ("1. --", "format"),  # no words past the punctuation
        ("1. Derive it in retro.py: and more", None),  # punctuation stripped: as `... and more` (#1261)
        ("1. Derive it in retro.py and more", None),
        ("1. Derive it in retro.py, only the asks", None),
        ("1. Derive it in `retro.py`", None),
        ("2. Derive it in retro.py", None),  # another option's name: read as listed (S-055-19)
        ("1. Keep the zone line", None),
        ("1. Derive it", None),
        ("1. Derive it in retro.py but rename the count", None),
        ("1", None),
        ("Hold it", None),  # no number: not this check's
        ("own: 1. Something else", None),
    ],
)
def test_d93_relay_refusal_reads_a_number_and_words_against_the_options(
    rt: ModuleType, answer: str, why: str | None
) -> None:
    assert rt.relay_refusal(OPTIONS, rt.parse_relay(relay(answer))) == why


def test_d93_punctuation_after_an_options_name_gives_the_reason_words_give(rt: ModuleType) -> None:
    """#1261: `1. Take every recommendation: more` reads as `1. Take every recommendation and
    more` does, a narrowing the gate holds as not taking the option, not a relay out of format"""
    options = "\n\n1. Take every recommendation (recommended): items 1-7\n2. Hold it: nothing lands"
    for answer in ("1. Take every recommendation: more", "1. Take every recommendation and more"):
        assert rt.relay_refusal(options, rt.parse_relay(relay(answer))) is None
        assert rt.takes_recommended(options, answer) is False


@pytest.mark.parametrize(("stated", "reply", "recommended"), [("other", "1", 0), ("recommended", "2", 1)])
def test_s030_18_an_explicit_answer_on_the_zone_line_wins_over_the_thread(
    rt: ModuleType, stated: str, reply: str, recommended: int
) -> None:
    threads = [{"kind": "issue", "number": 7, "comments": [bot(question(stated), ASKED), comment(reply, after(1))]}]
    counts = rt.decision_counts(
        threads, rt.weeks(END, 7, 1), ["contract-change"], frozenset({f"{BOT}[bot]"}), frozenset({"amy"})
    ).counts
    assert counts[0]["contract-change"]["recommended"] == recommended
    assert counts[0]["contract-change"]["answered"] == 1


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


# -- the rate, the questions with no zone line, and what became of a decided item (spec 058) ------

UNZONED = "<!-- shipmill:needs-decision -->\n@amy Decision needed: x" + OPTIONS + AGENT


def days_ago(n: float) -> str:
    return iso(END - dt.timedelta(days=n))


def asked_thread(number: int, *replies: dict[str, Any], body: str | None = None) -> dict[str, Any]:
    return {"kind": "issue", "number": number, "comments": [bot(body or question(), ASKED), *replies]}


def gathered(
    rt: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    issues: list[dict[str, Any]],
    pulls: list[dict[str, Any]],
    **overrides: Any,
) -> dict[str, Any]:
    _, run = commands()
    src = sources(rt, run, graphql=thread_graphql(rt, issues, pulls))
    assert rt.gather(policy_args(tmp_path, **overrides), src) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)["decisions"]
    return found


def zone_rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {z["zone"]: z for z in report["zones"]}


def test_s058_2_an_unanswered_question_is_left_out_and_an_unreadable_one_is_answered(rt: ModuleType) -> None:
    bots, maintainers = frozenset({f"{BOT}[bot]"}), frozenset({"amy"})
    threads = [
        asked_thread(1),  # no answer yet
        asked_thread(2, comment("sounds good, do whatever", after(1))),  # can't be read as an option
        asked_thread(3, comment("2", after(1))),  # departs from the recommended option
        asked_thread(4, comment("2", after(1)), body=question("recommended")),  # the zone line wins
        asked_thread(5, comment("1", after(1)), body=question("other")),
        asked_thread(6, body=question("recommended")),  # answered with no reply in the thread
    ]
    row = rt.decision_counts(threads, rt.weeks(END, 7, 1), ["contract-change"], bots, maintainers).counts[0]
    assert (row["contract-change"]["asks"], row["contract-change"]["answered"]) == (6, 5)
    assert row["contract-change"]["recommended"] == 2
    # an open question doesn't block a proposal: 9 of 10 answered recommended, 3 more unanswered
    threads = [asked_thread(n, comment("1", after(1))) for n in range(9)]
    threads += [asked_thread(9, comment("2", after(1)))] + [asked_thread(n) for n in range(10, 13)]
    counts = rt.decision_counts(threads, rt.weeks(END, 7, 4), ["contract-change"], bots, maintainers).counts
    full = [{**{z: dict.fromkeys(rt.COUNTS, 0) for z in rt.decisions_module().ZONES}, **week} for week in counts]
    assert [p["title"] for p in proposed(rt, full)] == ["Decision policy: contract-change from ask to notify"]


def test_s058_4_the_new_flags_default_and_refuse_values_out_of_range(rt: ModuleType) -> None:
    args = rt.parse(["gather", "o/r", "--decisions"])
    assert (args.lower_rate, args.lower_min, args.revert_days) == (90, 10, 14)
    assert (
        rt.parse(["gather", "o/r", "--lower-rate", "100", "--lower-min", "1", "--revert-days", "1"]).lower_rate == 100
    )
    for flags in (["--lower-rate", "0"], ["--lower-rate", "101"], ["--lower-min", "0"], ["--revert-days", "0"]):
        with pytest.raises(SystemExit) as stopped:
            rt.parse(["gather", "o/r", "--decisions", *flags])
        assert stopped.value.code == 2, flags


def test_s058_5_each_zone_reports_its_answered_questions_and_rate(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    issues = [
        thread(70, bot(question(), days_ago(3)), comment("1", days_ago(2))),
        thread(71, bot(question(), days_ago(10)), comment("1", days_ago(9))),  # an earlier window
        thread(72, bot(question(), days_ago(3)), comment("2", days_ago(2))),
        thread(73, bot(question(), days_ago(3))),  # unanswered
    ]
    rows = zone_rows(gathered(rt, tmp_path, capsys, issues, []))
    change = rows["contract-change"]
    assert (change["asks_over_windows"], change["answered_over_windows"], change["recommended_over_windows"]) == (
        4,
        3,
        2,
    )
    assert change["rate_over_windows"] == 66  # 2 of 3, rounded down
    assert (rows["security"]["answered_over_windows"], rows["security"]["rate_over_windows"]) == (0, None)


def test_s058_6_questions_with_no_zone_line_are_counted_apart_and_in_all(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    issues = [
        thread(12, bot(UNZONED, days_ago(3)), comment("1", days_ago(2))),
        thread(13, bot(UNZONED, days_ago(10)), comment("2", days_ago(9))),  # an earlier window: no item
        thread(40, comment(UNZONED, days_ago(3), association="NONE", login="outsider"), comment("1", days_ago(2))),
        thread(50, bot(question(), days_ago(3)), comment("1", days_ago(2))),
    ]
    pulls = [thread(34, bot(UNZONED, days_ago(1)))]  # unanswered
    report = gathered(rt, tmp_path, capsys, issues, pulls)
    assert report["unzoned"] == {
        "asks": 2,
        "answered": 1,
        "recommended": 1,
        "asks_over_windows": 3,
        "answered_over_windows": 2,
        "recommended_over_windows": 1,
        "rate_over_windows": 50,
        "items": [{"kind": "issue", "number": 12}, {"kind": "pull", "number": 34}],
    }
    assert report["all"] == {
        "asks": 3,
        "answered": 2,
        "recommended": 2,
        "asks_over_windows": 4,
        "answered_over_windows": 3,
        "recommended_over_windows": 2,
        "rate_over_windows": 66,
    }
    assert sum(z["asks_over_windows"] for z in report["zones"]) == 1  # never part of a zone
    _, run = commands()
    src = sources(rt, run, graphql=thread_graphql(rt, issues, pulls))
    assert rt.gather(policy_args(tmp_path, json=False), src) == 0
    text = capsys.readouterr().out
    assert "  no zone line: asks 2 (1 answered, 1 recommended): #12, #34" in text
    assert "  every question over the windows: asks 4 (3 answered, 2 recommended), rate 66%" in text


def test_s058_7_a_decided_issue_reopened_within_the_days_is_reverted_unless_vetoed(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    issues = [
        thread(80, bot(decided("interpretation"), days_ago(20)), reopened=(days_ago(15),)),  # 5 days after
        thread(81, bot(decided("interpretation"), days_ago(20)), reopened=(days_ago(2),)),  # 18 days after: held
        thread(  # vetoed, though reopened in time
            82,
            bot(decided("interpretation"), days_ago(20)),
            bot(handled("interpretation"), days_ago(19)),
            reopened=(days_ago(18),),
        ),
        thread(  # a veto-handled marker for another zone, or an untrusted one, isn't a veto
            83,
            bot(decided("interpretation"), days_ago(20)),
            bot(handled("triage-verdict"), days_ago(19)),
            comment(handled("interpretation"), days_ago(19), association="NONE", login="outsider"),
            reopened=(days_ago(17),),
        ),
        thread(84, bot(decided("interpretation"), days_ago(20)), reopened=(days_ago(21),)),  # before it: held
        thread(85, comment(decided("interpretation"), days_ago(20), association="NONE", login="outsider")),
    ]
    row = zone_rows(gathered(rt, tmp_path, capsys, issues, []))["interpretation"]
    outcome = [row[f"{k}_over_windows"] for k in ("decided", "vetoed", "reverted", "held")]
    assert outcome == [5, 1, 2, 2]


def test_s058_8_a_merged_pull_request_reverted_by_another_merged_one(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def done_pull(number: int, title: str, when: float = 21) -> dict[str, Any]:
        return thread(number, bot(decided("interpretation"), days_ago(when)), title=title, merged_at=days_ago(when + 1))

    pulls = [
        done_pull(90, "Add x"),
        thread(91, body="Reverts o/r#90\n\nWhy: broke CI", merged_at=days_ago(15)),  # the Revert button's line
        done_pull(92, "Add y"),
        thread(93, title='Revert "Add y"', merged_at=days_ago(16)),  # the Revert button's title
        done_pull(94, "Add z"),
        thread(95, body="Reverts #94", merged_at=days_ago(18)),
        done_pull(96, "Add w"),  # held: its reverts are open or closed unmerged
        thread(97, body="Reverts #96"),
        thread(98, title='Revert "Add w"'),
        done_pull(99, "Add v"),  # held: the revert names another repo's #99
        thread(100, body="Reverts other/repo#99", merged_at=days_ago(15)),
        done_pull(101, "Add u", when=25),  # held: reverted 20 days after its marker
        thread(102, body="Reverts #101", merged_at=days_ago(5)),
        thread(103, bot(decided("interpretation"), days_ago(21)), title="Add t"),  # held: never merged
        thread(104, title='Revert "Add t"', merged_at=days_ago(15)),
    ]
    row = zone_rows(gathered(rt, tmp_path, capsys, [], pulls))["interpretation"]
    outcome = [row[f"{k}_over_windows"] for k in ("decided", "vetoed", "reverted", "held")]
    assert outcome == [7, 0, 3, 4]


def test_s058_9_a_decided_marker_is_held_once_the_days_pass_and_counted_nowhere_before(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    issues = [
        thread(110, bot(decided("interpretation"), days_ago(14))),  # 14 days old: held
        thread(111, bot(decided("interpretation"), days_ago(3))),  # younger: in none of the three
        thread(112, bot(decided("interpretation"), days_ago(30))),  # before the windows: not counted
    ]
    report = gathered(rt, tmp_path, capsys, issues, [])
    row = zone_rows(report)["interpretation"]
    assert [row[f"{k}_over_windows"] for k in ("decided", "vetoed", "reverted", "held")] == [2, 0, 0, 1]
    for z in report["zones"]:
        assert {"decided_over_windows", "vetoed_over_windows", "reverted_over_windows", "held_over_windows"} <= set(z)
    report = gathered(rt, tmp_path, capsys, issues, [], revert_days=2)
    assert zone_rows(report)["interpretation"]["held_over_windows"] == 2
    _, run = commands()
    src = sources(rt, run, graphql=thread_graphql(rt, issues, []))
    assert rt.gather(policy_args(tmp_path, json=False), src) == 0
    assert "decided 2 over the windows: 0 vetoed, 0 reverted, 1 held" in capsys.readouterr().out


def test_s058_10_reverted_items_propose_nothing_and_raise_at_reads_vetoes_alone(
    rt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    issues = [thread(n, bot(decided("interpretation"), days_ago(5)), reopened=(days_ago(4),)) for n in range(120, 125)]
    report = gathered(rt, tmp_path, capsys, issues, [], raise_at=1)
    row = zone_rows(report)["interpretation"]
    assert (row["level"], row["vetoes"], row["reverted_over_windows"]) == ("notify", 0, 5)
    assert report["proposals"] == []
    issues.append(thread(125, bot(handled("interpretation"), days_ago(1))))
    report = gathered(rt, tmp_path, capsys, issues, [], raise_at=1)
    assert [(p["title"], p["why"]) for p in report["proposals"]] == [
        ("Decision policy: interpretation from notify to ask", "1 vetoes this window, at least 1")
    ]


def test_s058_11_the_weekly_retro_and_the_usage_name_the_rate_and_the_outcomes(rt: ModuleType) -> None:
    skill = (SCRIPTS.parent / "SKILL.md").read_text(encoding="utf-8")
    retro = " ".join(skill.split("\n## Weekly retro\n", 1)[1].split("\n## ", 1)[0].split())
    for flag in ("`--lower-rate` (90)", "`--lower-min` (10)", "`--revert-days` (14)"):
        assert flag in retro, flag
    decisions = retro.split("a section **Decisions**", 1)[1]
    for named in ("rate_over_windows", "vetoed", "reverted", "held", "no zone line"):
        assert named in decisions, named
    assert rt.__doc__ is not None
    usage = " ".join(rt.__doc__.split())
    for named in ("--lower-rate (90", "--lower-min (10)", "--revert-days", "rate", "`unzoned`", "reverted", "held"):
        assert named in usage, named
    assert "MIN_ASKS" not in SCRIPT.read_text(encoding="utf-8")


# -- findings (spec 077) ----------------------------------------------------------------------

REPO = "o/r"
APP = "shipmill-app"
SHA_B = "b" * 40
SHA_C = "c" * 40
MARKED = "\n\n<!-- shipmill:agent -->"


def rest(body: str, association: str = "COLLABORATOR", login: str = "amy", kind: str = "User", **extra: Any) -> Any:
    return {"body": body, "author_association": association, "user": {"login": login, "type": kind}, **extra}


def app(body: str, **extra: Any) -> Any:
    return rest(body + MARKED, "NONE", APP + "[bot]", "Bot", **extra)


def node(body: str, association: str = "COLLABORATOR", login: str = "amy", kind: str = "User", **extra: Any) -> Any:
    """A GraphQL review or comment; GraphQL spells an App's login without "[bot]" """
    return {"body": body, "authorAssociation": association, "author": {"__typename": kind, "login": login}, **extra}


def app_node(body: str, **extra: Any) -> Any:
    return node(body + MARKED, "NONE", APP, "Bot", **extra)


def said(body: str, when: str, **who: Any) -> Any:
    """A conversation comment"""
    return node(body, **who, createdAt=when)


def review(body: str, when: str, state: str = "CHANGES_REQUESTED", head: str = SHA, **who: Any) -> Any:
    return node(body, **who, state=state, commit={"oid": head}, submittedAt=when)


def app_review(body: str, when: str, head: str = SHA) -> Any:
    return app_node(body, state="COMMENTED", commit={"oid": head}, submittedAt=when)


COMMENT_IDS = iter(range(2_500_000_000, 3_000_000_000))  # past 2**31, as GitHub's are


def line_comment(
    body: str, when: str, path: str, line: int, head: str = SHA, state: str = "SUBMITTED", **who: Any
) -> Any:
    extra: dict[str, Any] = {
        "fullDatabaseId": str(next(COMMENT_IDS)),
        "state": state,
        "path": path,
        "originalLine": line,
        "line": None,
        "originalCommit": {"oid": head},
        "createdAt": when,
    }
    return node(body, **who, **extra)


def closed_pull(number: int, closed: str, merged: bool = False, head: str = SHA) -> Any:
    return {
        "number": number,
        "title": f"PR {number}",
        "url": f"https://github.com/{REPO}/pull/{number}",
        "mergedAt": closed if merged else None,
        "closedAt": closed,
        "headRefOid": head,
    }


def page(nodes: list[Any], size: int, cursor: Any = None) -> dict[str, Any]:
    """A connection's page after cursor, the index of the next node as a string"""
    start = int(cursor or 0)
    chunk = nodes[start : start + size]
    return {
        "pageInfo": {"hasNextPage": start + size < len(nodes), "endCursor": str(start + len(chunk))},
        "nodes": chunk,
    }


class Forge:
    """A scripted GitHub: the closed pull requests, each one's reviews, review threads, and
    conversation over GraphQL, paged as GitHub pages them, and the repo's rule-proposal issues
    over REST; it records every read and rejects a page past limit for its resource limits"""

    def __init__(
        self,
        pulls: list[Any],
        reviews: Mapping[int, list[Any]],
        threads: Mapping[int, list[list[Any]]],
        talk: Mapping[int, list[Any]],
        issues: list[Any],
        limit: int,
    ) -> None:
        self.pulls, self.reviews, self.threads, self.talk, self.issues = pulls, reviews, threads, talk, issues
        self.limit = limit
        self.calls: list[list[str]] = []
        self.queries: list[tuple[str, dict[str, Any]]] = []

    def read(self, cmd: list[str]) -> Any:
        self.calls.append(cmd)
        if cmd[:2] == ["pr", "list"]:
            return self.pulls
        assert cmd == ["api", "--paginate", f"repos/{REPO}/issues?labels=rule-proposal&state=all&per_page=100"] + [
            "--jq",
            ".[]",
        ], cmd
        return self.issues

    def thread_page(self, number: int, size: int, cursor: Any = None) -> dict[str, Any]:
        threads = self.threads.get(number, [])
        start = int(cursor or 0)
        edges = [
            {"cursor": str(i + 1), "node": {"id": f"T{number}-{i}", "comments": page(threads[i], size)}}
            for i in range(start, min(start + size, len(threads)))
        ]
        found = page(threads, size, cursor)
        return {"pageInfo": found["pageInfo"], "edges": edges}

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.queries.append((query, variables))
        assert (variables["owner"], variables["name"]) == tuple(REPO.split("/"))
        size, cursor = variables["size"], variables.get("cursor")
        if size > self.limit:
            return {"errors": [{"type": "RESOURCE_LIMITS_EXCEEDED", "message": "too costly"}]}
        if "fragment items" in query:
            repository: dict[str, Any] = {}
            for alias, n in variables.items():
                if alias.startswith("p") and alias[1:].isdigit():
                    repository[alias] = {
                        "reviews": page(self.reviews.get(n, []), size),
                        "reviewThreads": self.thread_page(n, size),
                        "comments": page(self.talk.get(n, []), size),
                    }
            return {"data": {"repository": repository}}
        number = int(variables["number"])
        if "reviewThreads(first: 1," in query:
            at = int(variables.get("thread", 0))
            thread = {"id": f"T{number}-{at}", "comments": page(self.threads[number][at], size, cursor)}
            pull: dict[str, Any] = {"reviewThreads": {"nodes": [thread]}}
        elif "reviewThreads(first: $size, after: $cursor)" in query:
            pull = {"reviewThreads": self.thread_page(number, size, cursor)}
        elif "reviews(first: $size, after: $cursor)" in query:
            pull = {"reviews": page(self.reviews[number], size, cursor)}
        else:
            assert "comments(first: $size, after: $cursor)" in query, query
            pull = {"comments": page(self.talk[number], size, cursor)}
        return {"data": {"repository": {"pullRequest": pull}}}


def forge(
    pulls: list[Any],
    reviews: Mapping[int, list[Any]] | None = None,
    comments: Mapping[int, list[Any]] | None = None,
    talk: Mapping[int, list[Any]] | None = None,
    issues: list[Any] | None = None,
    threads: Mapping[int, list[list[Any]]] | None = None,
    limit: int = 1000,
) -> Forge:
    """A Forge where each of comments is a review thread of its own, after threads' threads"""
    grouped = {n: list(found) for n, found in (threads or {}).items()}
    for n, flat in (comments or {}).items():
        grouped.setdefault(n, []).extend([c] for c in flat)
    return Forge(pulls, reviews or {}, grouped, talk or {}, issues or [], limit)


def run_findings(
    rt: ModuleType, capsys: pytest.CaptureFixture[str], github: Forge, *flags: str
) -> tuple[dict[str, Any], str]:
    """findings' --json report and its text, over the same forge"""
    args = rt.parse(["findings", REPO, "--bot", APP, *flags])
    assert rt.findings(args, github.read, END, github.graphql) == 0
    text = capsys.readouterr().out
    args = rt.parse(["findings", REPO, "--bot", APP, "--json", *flags])
    assert rt.findings(args, github.read, END, github.graphql) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report, text


def listed_items(report: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    return {p["number"]: p["items"] for p in report["findings"]}


def test_s077_1_records_reviews_and_inline_comments_of_the_window_are_listed(
    rt: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    record = (
        "<!-- shipmill:review refuse -->\n<!-- shipmill:findings confirmed=1 rejected=0 minor=0 -->\nBreaks I-2, D-16."
    )
    github = forge(
        [closed_pull(57, day(2), merged=True, head=SHA_C), closed_pull(40, day(30), merged=True)],
        reviews={
            57: [
                app_review(record, day(3)),
                review("Use start:dev, see N-3 and Q-1, not XQ-12.", day(2.6), head=SHA_B),
            ],
            40: [review("Outside the window", day(31))],
        },
        comments={
            57: [line_comment("The dev script is start:dev (I-4, I-4).", day(2.5), "apps/api/package.json", 12, SHA_B)]
        },
    )
    report, text = run_findings(rt, capsys, github)
    calls = github.calls
    assert [p["number"] for p in report["findings"]] == [57]
    found = listed_items(report)[57]
    assert [(i["id"], i["kind"], i["author"], i["head"], i["path"], i["line"], i["cites"]) for i in found] == [
        ("F-1", "record", APP + "[bot]", SHA, None, None, ["I-2", "D-16"]),
        ("F-2", "review", "amy", SHA_B, None, None, ["N-3", "Q-1"]),
        ("F-3", "comment", "amy", SHA_B, "apps/api/package.json", 12, ["I-4"]),
    ]
    assert found[0]["text"] == "Breaks I-2, D-16."
    assert f"F-3 comment by amy at {SHA_B} apps/api/package.json:12; cites I-4" in text
    assert "#57 PR 57 (merged" in text and "#40" not in text and "Outside the window" not in text
    assert calls[0][calls[0].index("--search") + 1] == f"closed:>={END - dt.timedelta(days=28):%Y-%m-%d}"


def test_s077_2_an_unmerged_pull_lists_its_newest_trusted_comment_at_the_close_as_a_refusal(
    rt: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    conversation = [
        said("First thoughts", day(3)),
        app_node("Refused: it breaks D-16.", createdAt=day(1.5)),
        said("Outsider's last word", day(1.2), association="NONE", login="zed"),
        said("After the close", day(0.5)),
    ]
    github = forge(
        [closed_pull(60, day(1), head=SHA_B), closed_pull(61, day(1), merged=True), closed_pull(62, day(2))],
        talk={
            60: conversation,
            61: [said("Merged, thanks", day(1.5), association="OWNER")],
            62: [said("No.", day(2), association="MEMBER", login="bo")],
        },
    )
    report, text = run_findings(rt, capsys, github)
    assert [p["number"] for p in report["findings"]] == [60, 62]
    assert [(i["id"], i["kind"], i["author"], i["head"], i["text"], i["cites"]) for i in listed_items(report)[60]] == [
        ("F-1", "refusal", APP + "[bot]", SHA_B, "Refused: it breaks D-16.", ["D-16"])
    ]
    assert [(i["kind"], i["author"]) for i in listed_items(report)[62]] == [("refusal", "bo")]
    assert "#61" not in text and "Merged, thanks" not in text
    assert "#60 PR 60 (closed without a merge" in text


def test_s077_3_outsiders_and_marked_text_are_left_out_and_long_text_is_cut(
    rt: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    github = forge(
        [closed_pull(70, day(1), merged=True), closed_pull(71, day(2)), closed_pull(72, day(3), merged=True)],
        reviews={
            70: [
                review("OUTSIDER-REVIEW", day(1.5), association="CONTRIBUTOR", login="zed"),
                review("AGENT-REVIEW" + MARKED, day(1.4)),
                review("APP-WITHOUT-RECORD", day(1.3), association="NONE", login=APP, kind="Bot"),
                review("Looks good", day(1.2), state="APPROVED"),
                review("PENDING-REVIEW", day(1.1), state="PENDING"),
            ],
            72: [review("x" * 700, day(3.5))],
        },
        comments={
            70: [
                line_comment("OUTSIDER-COMMENT", day(1.5), "a.py", 1, association="NONE", login="zed"),
                line_comment("AGENT-COMMENT" + MARKED, day(1.4), "a.py", 2),
                line_comment("PENDING-COMMENT", day(1.3), "a.py", 3, state="PENDING"),
            ]
        },
        talk={71: [said("OUTSIDER-CLOSE", day(2.5), association="FIRST_TIME_CONTRIBUTOR", login="zed")]},
    )
    report, text = run_findings(rt, capsys, github)
    dumped = json.dumps(report)
    for left_out in ("OUTSIDER", "AGENT-", "APP-WITHOUT-RECORD", "zed", "Looks good", "PENDING-"):
        assert left_out not in dumped and left_out not in text, left_out
    assert [p["number"] for p in report["findings"]] == [72]
    assert "#70" not in text and "#71" not in text
    assert listed_items(report)[72][0]["text"] == "x" * 600 + "…"
    assert "x" * 600 + "…" in text and "x" * 601 not in text


def proposal(number: int, state: str, reason: str | None, body: str, **who: Any) -> Any:
    url = f"https://github.com/{REPO}/issues/{number}"
    return rest(
        body, **who, number=number, title=f"Rule: rule {number}", state=state, state_reason=reason, html_url=url
    )


def test_s077_4_proposed_lists_trusted_marked_rule_proposals_in_any_state(
    rt: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    mark = "<!-- shipmill:rule-proposal pulls=41,57 place=lint -->\n## Rule\n\nx"
    issues = [
        proposal(95, "open", None, mark, pull_request={"url": "x"}),  # a pull request, not an issue
        proposal(94, "open", None, "## Rule\n" + mark),  # the marker isn't the first line
        proposal(93, "open", None, mark, association="NONE", login="zed"),  # an outsider's
        proposal(92, "closed", "not_planned", mark.replace("lint", "prose"), association="OWNER"),
        proposal(91, "closed", "completed", mark.replace("41,57", "3,8,9")),
        app(mark, number=90, title="Rule: rule 90", state="open", state_reason=None, html_url="u90"),
    ]
    report, text = run_findings(rt, capsys, forge([], issues=issues))
    assert [(p["number"], p["title"], p["pulls"], p["place"], p["state"]) for p in report["proposed"]] == [
        (92, "Rule: rule 92", [41, 57], "prose", "declined"),
        (91, "Rule: rule 91", [3, 8, 9], "lint", "accepted"),
        (90, "Rule: rule 90", [41, 57], "lint", "open"),
    ]
    assert "Proposed: 3" in text
    assert "#92 declined: Rule: rule 92 (place prose; pulls #41, #57)" in text
    assert "#93" not in text and "#94" not in text and "#95" not in text


def test_s077_5_json_has_its_three_keys_and_bad_input_or_a_failed_read_exits_2_with_no_list(
    rt: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    report, _ = run_findings(rt, capsys, forge([]), "--days", "7")
    assert set(report) == {"window", "findings", "proposed"}
    assert report["window"] == {"start": "2026-09-27T00:00:00Z", "end": "2026-10-04T00:00:00Z", "days": 7}
    with pytest.raises(SystemExit) as refused:
        rt.parse(["findings", REPO, "--days", "0"])
    assert refused.value.code == 2
    assert "--days must be at least 1" in capsys.readouterr().err
    full = forge([closed_pull(n, day(1)) for n in range(rt.PR_LIMIT)])
    with pytest.raises(SystemExit) as refused:
        rt.findings(rt.parse(["findings", REPO, "--json"]), full.read, END, full.graphql)
    assert refused.value.code == 2
    out, err = capsys.readouterr()
    assert out == "" and "use a shorter --days" in err

    def failing(cmd: list[str]) -> Any:
        return subprocess.CompletedProcess(cmd, 1, "", "HTTP 404: Not Found")

    scripted = forge([closed_pull(57, day(1), merged=True)])

    def read(cmd: list[str]) -> Any:
        return scripted.read(cmd) if cmd[0] == "pr" else rt.gh_read(cmd, failing)

    def graphql(query: str, variables: dict[str, Any]) -> Any:
        return rt.findings_graphql(query, variables, failing)

    for reader, runner in ((read, scripted.graphql), (scripted.read, graphql)):  # a failed REST or GraphQL read
        for flags in ([], ["--json"]):
            with pytest.raises(SystemExit) as refused:
                rt.findings(rt.parse(["findings", REPO, *flags]), reader, END, runner)
            assert refused.value.code == 2
            out, err = capsys.readouterr()
            assert out == "" and "HTTP 404" in err and "gh auth status" in err


def test_findings_reads_120_pull_requests_in_3_queries(rt: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    """#1376: up to 50 pull requests per GraphQL query, not two or three REST reads each"""
    pulls = [closed_pull(n, day(1 + n / 1000), merged=True) for n in range(1, 121)]
    github = forge(pulls, reviews={n: [review(f"Fix {n}", day(2))] for n in range(1, 121)})
    args = rt.parse(["findings", REPO, "--bot", APP, "--json"])
    assert rt.findings(args, github.read, END, github.graphql) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["findings"]) == 120
    assert [(p["number"], [i["text"] for i in p["items"]]) for p in report["findings"]][:2] == [
        (1, ["Fix 1"]),
        (2, ["Fix 2"]),
    ]
    assert [len([k for k in v if k.startswith("p")]) for _, v in github.queries] == [50, 50, 20]
    assert [c[:2] for c in github.calls] == [["pr", "list"], ["api", "--paginate"]]  # the pulls, then the proposals


def test_findings_pages_on_alone_a_connection_longer_than_its_page(
    rt: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """A pull request's reviews, review threads, a thread's comments, and conversation past
    one page are each read on for that pull request alone, and every finding is listed"""
    reviews = [review(f"R{i}", day(5 - i / 1000)) for i in range(120)]
    long_first = [line_comment(f"A{i}", day(4 - i / 1000), "a.py", i + 1) for i in range(120)]
    single = [[line_comment(f"S{i}", day(3 - i / 1000), "b.py", i + 1)] for i in range(54)]
    long_later = [line_comment(f"B{i}", day(2.5 - i / 1000), "c.py", i + 1) for i in range(120)]
    tail = [[line_comment(f"U{i}", day(2.3 - i / 1000), "d.py", i + 1)] for i in range(3)]
    talk = [said(f"T{i}", day(2.4 - i / 1000)) for i in range(130)]
    github = forge(
        [closed_pull(9, day(1)), closed_pull(8, day(1.5), merged=True)],
        reviews={9: reviews},
        threads={9: [long_first, *single, long_later, *tail]},  # long_later is thread 55, on the second page
        talk={9: talk},
    )
    args = rt.parse(["findings", REPO, "--bot", APP, "--json"])
    assert rt.findings(args, github.read, END, github.graphql) == 0
    items = listed_items(json.loads(capsys.readouterr().out))[9]
    expected = [f"{kind}{i}" for kind, count in (("R", 120), ("A", 120), ("S", 54), ("B", 120)) for i in range(count)]
    assert [i["text"] for i in items] == [*expected, "U0", "U1", "U2", "T129"]
    assert [(i["path"], i["line"]) for i in items if i["text"] in ("A119", "B0")] == [("a.py", 120), ("c.py", 1)]
    names = {
        rt.MORE_THREAD_COMMENTS: "thread comments",
        rt.MORE_THREADS: "threads",
        rt.MORE_TALK: "talk",
        rt.MORE_REVIEWS: "reviews",
    }
    paged = [(names[q], v["number"], v.get("thread"), v["cursor"]) for q, v in github.queries[1:]]
    assert paged == [
        ("thread comments", 9, None, "50"),
        ("threads", 9, None, "50"),
        ("thread comments", 9, "55", "100"),
        ("talk", 9, None, "50"),
        ("reviews", 9, None, "50"),
    ]


def test_findings_pages_shrink_while_github_rejects_them_for_their_resource_limits(
    rt: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    github = forge([closed_pull(1, day(1), merged=True)], reviews={1: [review("Fix", day(2))]}, limit=25)
    args = rt.parse(["findings", REPO, "--bot", APP, "--json"])
    assert rt.findings(args, github.read, END, github.graphql) == 0
    assert [p["number"] for p in json.loads(capsys.readouterr().out)["findings"]] == [1]
    assert [v["size"] for _, v in github.queries] == [50, 25]


def test_findings_graphql_sends_typed_variables_and_hands_back_a_resource_limit(rt: ModuleType) -> None:
    sent: list[list[str]] = []
    limited = {"errors": [{"type": "RESOURCE_LIMITS_EXCEEDED"}]}

    def run(cmd: list[str]) -> Any:
        sent.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, json.dumps(limited), "gh: too costly")

    assert rt.findings_graphql("query", {"owner": "o", "name": "123", "p0": 7}, run) == limited
    assert sent == [["gh", "api", "graphql", "-f", "query=query", "-f", "owner=o", "-f", "name=123", "-F", "p0=7"]]


def test_findings_reads_every_page_as_json_lines(rt: ModuleType) -> None:
    def pages(cmd: list[str]) -> Any:
        return subprocess.CompletedProcess(cmd, 0, '{"n": 1}\n{"n": 2}\n', "")

    cmd = ["api", "--paginate", "repos/o/r/pulls/1/reviews?per_page=100", "--jq", ".[]"]
    assert rt.gh_read(cmd, pages) == [{"n": 1}, {"n": 2}]
