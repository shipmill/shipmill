"""Spec 079's watch and gate (#1292): watch_state.py's BASE_RED row from base_red.py's reading,
first in tier 2, and the gate's change check reading the default head's check rollup, so a check
failing on an unchanged head makes the tick walk"""

import argparse
import datetime as dt
import importlib.util
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.errors import ReleaseError
from shipmill.findings import Finding, parse_findings
from shipmill.gate import Action, state_dir
from shipmill.gitrepo import Git
from shipmill.walk import BASE_READ, CURSOR, TIERS, Changes, Cursor, base_read, base_reading, change_query, check

from .test_gate import checkout
from .test_gate_walk import LATER, NOW, REPO, Gh, Source, cfg, graphql_answer, runs, tick

__all__ = ["checkout"]  # the fixture, imported for the tests below

ROOT = Path(__file__).resolve().parents[1]
WATCH = ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
BASE_RED = ROOT / "skills" / "github-pr-triage" / "scripts" / "base_red.py"
SHA = "c" * 40
RUN = "https://github.com/o/r/actions/runs/5"
POLICY = Path(".github/shipmill.toml")


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("watch_state_base_red", WATCH)


@pytest.fixture(scope="module")
def br() -> ModuleType:
    return load("base_red_row", BASE_RED)


def reading(
    ws: ModuleType,
    state: str,
    candidates: Sequence[tuple[str, int | None]] = (),
    repair: Sequence[int] = (),
    asked: Sequence[int] = (),
) -> Any:
    rerun = (RUN,) if state == "RERUN_DUE" else ()
    pending = (RUN,) if state == "PENDING" else ()
    return ws.BaseReading(state, "main", SHA, pending, rerun, tuple(candidates), tuple(repair), tuple(asked))


def shown(row: Any) -> tuple[str, str, str, bool, str]:
    line = row.json()
    return line["state"], line["subject"], line["detail"], line["agent"], line["fix"]


# -- S-079-6: the row, its fix, and whether it needs an agent

ROWS = [
    ("PENDING", (), "rerun running", f"wait for the rerun: {RUN}", False),
    ("RERUN_DUE", (), "rerun due", "gh run rerun 5 --failed -R o/r", True),
    ("CULPRIT", (("d" * 40, 12),), "culprit #12", "/shipmill:github-pr-triage o/r", True),
    (
        "CANDIDATES",
        (("d" * 40, 12), ("e" * 40, None)),
        "candidates #12 eeeeeee",
        "/shipmill:github-pr-triage o/r",
        True,
    ),
    ("NO_GREEN", (), "no green in the last 30 commits", "/shipmill:github-pr-triage o/r", True),
]


@pytest.mark.parametrize(("state", "candidates", "detail", "fix", "acts"), ROWS)
@pytest.mark.parametrize("level", ["observe", "propose", "act"])
def test_s079_6_every_reading_but_green_is_a_base_red_row_with_a_fix(
    ws: ModuleType,
    state: str,
    candidates: tuple[tuple[str, int | None], ...],
    detail: str,
    fix: str,
    acts: bool,
    level: str,
) -> None:
    row = ws.base_row(reading(ws, state, candidates), level, "o/r")
    # an agent's row only under propose or act; never under observe, the default
    assert shown(row) == ("BASE_RED", "main@ccccccc", detail, acts and level != "observe", fix)
    assert row.action  # the watch exits 1 on it


@pytest.mark.parametrize("level", ["observe", "propose", "act"])
def test_s079_6_a_repair_or_a_question_open_is_no_agents_row(ws: ModuleType, level: str) -> None:
    repaired = ws.base_row(reading(ws, "CULPRIT", (("d" * 40, 12),), repair=(40,)), level, "o/r")
    assert shown(repaired) == (
        "BASE_RED",
        "main@ccccccc",
        "culprit #12; repair open: #40",
        False,  # tier 3 lands the repair
        "/shipmill:github-pr-triage o/r",
    )
    asked = ws.base_row(reading(ws, "NO_GREEN", asked=(41,)), level, "o/r")
    assert shown(asked) == (
        "BASE_RED",
        "main@ccccccc",
        "no green in the last 30 commits; asked in #41",
        False,  # tier 4 takes up the answer
        "answer the needs-decision question on o/r #41",
    )


@pytest.mark.parametrize("level", ["observe", "propose", "act"])
def test_s079_6_green_again_closes_the_question_and_green_alone_is_no_row(ws: ModuleType, level: str) -> None:
    assert ws.base_row(reading(ws, "GREEN"), level, "o/r") is None
    again = ws.base_row(reading(ws, "GREEN", asked=(41,)), level, "o/r")
    assert shown(again) == (
        "BASE_RED",
        "main@ccccccc",
        "green again, close #41",
        level != "observe",
        "shipmill gh issue close 41 -R o/r --comment 'main@ccccccc is green again'",
    )


def test_s079_6_the_row_reads_as_the_gates_finding(ws: ModuleType) -> None:
    rows = [ws.base_row(reading(ws, "CULPRIT", (("d" * 40, 12),)), level, "o/r") for level in ("observe", "act")]
    found = parse_findings("\n".join(json.dumps(r.json(), sort_keys=True) for r in rows))
    assert [(f.kind, f.subject, f.agent) for f in found] == [
        ("BASE_RED", "main@ccccccc", False),
        ("BASE_RED", "main@ccccccc", True),
    ]
    with pytest.raises(ValueError, match="only a BASE_RED row"):
        ws.Row("BOT_FAILED", "release.yml", "d", "fix", needs_agent=True)


def test_s079_6_the_watch_reads_base_red_pys_json_as_it_prints_it(ws: ModuleType, br: ModuleType) -> None:
    """base_red.py's own --json object, as its Reading writes it, read by the watch: the two
    scripts agree on the shape"""
    found = br.Reading("CANDIDATES", "main", SHA)
    found.candidates = [br.Candidate("d" * 40, 3, pull=12, reason=None), br.Candidate("e" * 40, 2, reason="x")]
    found.repair, found.asked = [40], []
    calls: list[tuple[list[str], Path | None]] = []

    def execute(cmd: list[str], cwd: Path | None, env: object) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, cwd))
        return subprocess.CompletedProcess(cmd, 0, json.dumps(found.record()), "")

    rows = ws.base_red_rows("o/r", Path("/work/r"), "main", "app[bot]", "act", execute)
    assert [(r.detail, r.json()["agent"]) for r in rows] == [("candidates #12 eeeeeee; repair open: #40", False)]
    (cmd, cwd), *_ = calls
    assert cmd[1:] == [str(ws.BASE_RED_SCRIPT), "o/r", "--branch", "main", "--limit", "30", "--bot-login"] + [
        "app[bot]",
        "--json",
    ]
    assert cwd == Path("/work/r") and ws.BASE_RED_SCRIPT == BASE_RED


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [
        (2, ""),  # a read that fails: base_red.py prints nothing
        (0, "not json"),
        (0, json.dumps({"state": "GREEN"})),
        (0, json.dumps({"state": "RED", "branch": "main", "sha": SHA, "failed": [], "pending": [], "rerun": []})),
    ],
)
def test_s079_6_a_failed_or_malformed_reading_stops_the_watch(ws: ModuleType, returncode: int, stdout: str) -> None:
    def execute(cmd: list[str], cwd: Path | None, env: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, returncode, stdout, "base_red: gh api failed")

    with pytest.raises(ws.Refused):
        ws.base_red_rows("o/r", Path("."), "main", None, "observe", execute)


@pytest.mark.parametrize(
    ("autonomy", "level"),
    [("", "observe"), ('\n[autonomy]\nrevert = "propose"\n', "propose"), ('\n[autonomy]\nrevert = "act"\n', "act")],
)
def test_s079_6_the_level_is_the_configs_autonomy_revert(ws: ModuleType, autonomy: str, level: str) -> None:
    text = 'mode = "off"\n' + autonomy
    assert ws.config(text, POLICY).revert == level
    assert (ws.autonomy_string_310(text, POLICY, "revert") or "observe") == level


def test_s079_6_any_other_revert_level_stops_the_watch(ws: ModuleType) -> None:
    with pytest.raises(ws.Refused, match=r"\[autonomy\] revert must be one of \['observe', 'propose', 'act'\]"):
        ws.config('mode = "off"\n[autonomy]\nrevert = "yes"\n', POLICY)


def args_of(ws: ModuleType) -> argparse.Namespace:
    found: argparse.Namespace = ws.arguments().parse_args(["o/r", "--bot-login", "app[bot]"])
    return found


def test_s079_7_tier_2_reads_base_red_py_only_when_known_asks(ws: ModuleType, tmp_path: Path) -> None:
    ran: list[list[str]] = []

    def execute(cmd: list[str], cwd: Path | None, env: object) -> subprocess.CompletedProcess[str]:
        ran.append(cmd)
        record = {"state": "RERUN_DUE", "branch": "trunk", "sha": SHA, "failed": [], "pending": [], "rerun": [RUN]}
        return subprocess.CompletedProcess(
            cmd, 0, json.dumps(record | {"candidates": [], "repair": [], "asked": []}), ""
        )

    config = 'mode = "off"\n[autonomy]\nrevert = "act"\n'
    skipped = ws.Known("trunk", False, [], [], [], False)
    assert ws.tier_base_rows(args_of(ws), tmp_path, config, skipped, execute) == [] and ran == []
    asked = ws.Known("trunk", False, [], [], [])  # a known.json without base_read reads it
    (row,) = ws.tier_base_rows(args_of(ws), tmp_path, config, asked, execute)
    assert (row.subject, row.detail, row.json()["agent"]) == ("trunk@ccccccc", "rerun due", True)
    assert ran[0][4] == "trunk"  # GitHub's default branch, as the change check read it


@pytest.mark.parametrize(("given", "read"), [({}, True), ({BASE_READ: True}, True), ({BASE_READ: False}, False)])
def test_s079_7_known_json_holds_base_read_or_not(
    ws: ModuleType, tmp_path: Path, given: dict[str, object], read: bool
) -> None:
    path = tmp_path / "known.json"
    data = {"default_branch": "main", "held": False, "prs": [], "incidents": [], "runs": []}
    path.write_text(json.dumps(data | given), encoding="utf-8")
    assert ws.read_known(path).base_read is read
    path.write_text(json.dumps(data | {BASE_READ: "yes"}), encoding="utf-8")
    with pytest.raises(ws.Refused, match="base_read must be true or false"):
        ws.read_known(path)


# -- S-079-7: tier 2's order and the change check


def test_s079_7_base_red_comes_first_in_tier_2_in_both_tables(ws: ModuleType) -> None:
    assert ws.TIERS[2][:2] == ("BASE_RED", "BOT_FAILED")
    assert ws.TIERS[2] == TIERS[2]
    assert "BASE_RED" in ws.ACTION and "BASE_RED" not in ws.AGENT  # the row says it itself


def answer(base: str | None, head: str = "h1") -> Changes:
    gh = Gh([graphql_answer(head=head, base=base)], runs())
    found = check(REPO, NOW, "incident", (), gh.graphql, gh.read, NOW)
    assert len(gh.queries) == 1  # still the one query (D-58)
    assert "defaultBranchRef { name target { oid ... on Commit { statusCheckRollup { state } }" in gh.queries[0]
    return found


def test_s079_7_the_change_check_reads_the_default_heads_rollup_in_its_one_query() -> None:
    assert "statusCheckRollup { state }" in change_query(("updated",)).split("latestRelease")[0]
    assert "statusCheckRollup" not in change_query(("pulls",), {"pulls": "c1"}, first=False).split("pullRequests")[0]
    green, red, running = answer("SUCCESS"), answer("FAILURE"), answer("PENDING")
    # a check failing, or starting, on an unchanged head moves the signature; a green head or
    # one with no checks signs as before, so a cursor written before spec 079 still matches it
    assert len({green.signature, red.signature, running.signature}) == 3
    assert answer(None).signature == green.signature
    assert [c.known[BASE_READ] for c in (green, red, running, answer("ERROR"))] == [False, True, False, True]


def test_s079_7_an_answer_without_the_heads_rollup_is_refused() -> None:
    data = graphql_answer()
    del data["data"]["repository"]["defaultBranchRef"]["target"]["statusCheckRollup"]
    gh = Gh([data], runs())
    with pytest.raises(ReleaseError, match="no check rollup for the default head"):
        check(REPO, NOW, "incident", (), gh.graphql, gh.read, NOW)


def test_s079_7_the_last_reading_asks_for_another(tmp_path: Path) -> None:
    quiet = Changes("s", known={BASE_READ: False})
    at = NOW
    assert base_read(quiet, None).known[BASE_READ] is True  # no cursor: unknown
    assert base_read(quiet, Cursor(at, "s")).known[BASE_READ] is True  # a cursor from before spec 079
    assert base_read(quiet, Cursor(at, "s", True)).known[BASE_READ] is True  # the last reading wasn't GREEN
    assert base_read(quiet, Cursor(at, "s", False)) == quiet
    assert base_read(Changes("rows", forced=True), None) == Changes("rows", forced=True)  # no key, as rows a test hands
    red = Finding("BASE_RED", "main@ccccccc", "rerun due", False, (), "gh run rerun 5")
    assert base_reading((1, 2, 3), [red], None) is True
    assert base_reading((1, 2, 3), [], Cursor(at, "s", True)) is False
    assert base_reading((1,), [], Cursor(at, "s", True)) is True  # tier 2 unread: the last reading stands
    assert base_reading((1,), [], None) is None


def test_s079_7_a_cursor_keeps_the_last_reading_and_an_old_one_still_loads(tmp_path: Path) -> None:
    path = tmp_path / CURSOR
    path.write_text(json.dumps({"at": NOW.isoformat(), "signature": "s"}), encoding="utf-8")
    assert Cursor.load(path) == Cursor(NOW, "s", None)
    Cursor(NOW, "s", True).save(path)
    assert Cursor.load(path) == Cursor(NOW, "s", True)
    Cursor(NOW, "s").save(path)
    assert set(json.loads(path.read_text())) == {"at", "signature"}
    path.write_text(json.dumps({"at": NOW.isoformat(), "signature": "s", "base_red": "no"}), encoding="utf-8")
    with pytest.raises(ReleaseError, match="base_red must be true, false, or null"):
        Cursor.load(path)


@dataclass
class Checked(Source):
    """A state read whose change check runs the real one against a fake GitHub answering the
    default head's rollup as base says, and whose tier 2 returns rows2, logging each read and
    each known tier 2 was given"""

    base: str = "SUCCESS"
    rows2: list[Finding] = field(default_factory=list)
    known: list[bool] = field(default_factory=list)

    def changes(self, since: dt.datetime | None) -> Changes:
        self.reads.append("changes")
        gh = Gh([graphql_answer(head="h1", base=self.base)], runs())
        return check(REPO, since, "incident", (), gh.graphql, gh.read, NOW)

    def tier(self, number: int, changes: Changes) -> list[Finding]:
        self.reads.append(f"tier {number}")
        if number != 2:
            return []
        self.known.append(bool(changes.known[BASE_READ]))
        return list(self.rows2)

    def sweep(self, changes: Changes) -> list[Finding]:
        return []

    def issues(self, numbers: Sequence[int]) -> Mapping[int, dt.datetime]:
        return {}


def test_s079_7_a_check_failing_on_an_unchanged_head_makes_the_tick_walk(checkout: Git) -> None:
    agents = cfg(sweep_hours=48)
    source = Checked(base="SUCCESS")
    tick(checkout, source, agents=agents)  # the first tick walks: no cursor, the reading unknown
    assert source.known == [True]
    source.reads.clear()
    quiet = tick(checkout, source, LATER, agents=agents)
    assert quiet.action is Action.QUIET and quiet.reason.startswith("no change since")
    assert source.reads == ["changes"]
    # the same head, its check now failed: a change, so the tick walks to tier 2's base_red.py read
    source.base = "FAILURE"
    source.rows2 = [Finding("BASE_RED", "main@ccccccc", "rerun due", False, (), "gh run rerun 5 --failed -R o/r")]
    decision = tick(checkout, source, LATER + dt.timedelta(minutes=15), agents=agents)
    # under observe the row is no agent's, so the walk reads every tier and hands nothing
    assert decision.walk is not None and decision.walk.change and "tier 2" in source.reads
    assert not decision.reason.startswith("no change since")
    assert source.known == [True, True]
    assert json.loads((state_dir(checkout) / CURSOR).read_text())["base_red"] is True
    # green again on the same head: the last reading wasn't GREEN, so tier 2 reads it once more
    source.base, source.rows2 = "SUCCESS", []
    source.reads.clear()
    tick(checkout, source, LATER + dt.timedelta(minutes=30), agents=agents)
    assert "tier 2" in source.reads and source.known[-1] is True
    assert json.loads((state_dir(checkout) / CURSOR).read_text())["base_red"] is False
