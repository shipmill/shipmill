"""Spec 091: `shipmill status --summary`, the gate's state and who holds the open work"""

import dataclasses
import datetime as dt
import json
import subprocess
from pathlib import Path

import pytest

from shipmill.autonomy import Autonomy, AutonomyPolicy
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.gate import LAST_RESULT, RECORD, TICK, LastResult, Launch, Running, TickRecord, save_launch
from shipmill.gitrepo import Git
from shipmill.item_status import Condition, Who
from shipmill.status import Facts, Issue, Pull, Row
from shipmill.status_summary import GateState, Holder, Split, linked, own_holder, read_gate_state, resolve, split
from shipmill.walk import Landed
from tests.test_status_item import NONE, WRITES, Fake
from tests.test_status_picture import REPO, facts, gate, host, repo_with_release

NOW = dt.datetime(2026, 11, 25, 12, 0, tzinfo=dt.UTC)
LANDED_AT = "2026-11-25T11:00:00Z"


def holders(found: Facts) -> Split:
    return split(found, lambda _: NONE, None)


def line_of(found: Split, number: int) -> Holder:
    (holder,) = [h for h in Holder if number in (*found.issues.get(h, ()), *found.pulls.get(h, ()))]
    return holder


class SummaryFake(Fake):
    """Fake's picture, plus the default branch's history, whose newest commit came in by #8"""

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "api", "graphql"] and "defaultBranchRef" in cmd[4]:
            nodes = [{"associatedPullRequests": {"nodes": [{"number": 8, "mergedAt": LANDED_AT}]}}]
            data = {"data": {"repository": {"defaultBranchRef": {"target": {"history": {"nodes": nodes}}}}}}
            self.seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, json.dumps(data), "")
        return super().__call__(cmd)


def configured(root: Path) -> Path:
    (root / ".github").mkdir()
    (root / ".github" / "shipmill.toml").write_text(
        '[agents]\nprompt = "/shipmill:github-issue-triage {repo}"\nmode = "headless"\n\n[autonomy]\nland = "act"\n',
        encoding="utf-8",
    )
    return root


def run_summary(root: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, SummaryFake]:
    fake = SummaryFake()
    code = main(["--repo", str(root), "status", "--summary", *args], state=fake, login=host)
    return code, capsys.readouterr().out, fake


def test_s091_1_summary_prints_totals_gate_and_the_four_lines_in_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo_with_release(tmp_path / "repo")
    code, out, _ = run_summary(root, capsys)
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == f"{REPO}: 1 open issue, 1 pull request"
    assert [line.split("  ")[1] for line in lines[1:]] == [
        "gate",
        "waits on you",
        "agent takes it",
        "needs attention",
        "waits on nobody",
    ]
    assert lines[2] == "  waits on you     1 issue, 1 pull request"  # an opportunity; no [agents] for #9
    assert lines[4] == "  needs attention  none"


@pytest.mark.parametrize("other", [["--rows"], ["--item", "4"]])
def test_s091_1_summary_with_rows_or_item_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], other: list[str]
) -> None:
    root = repo_with_release(tmp_path / "repo")
    fake = SummaryFake()
    with pytest.raises(ReleaseError, match="--summary can't be combined with --rows or --item"):
        main(["--repo", str(root), "status", "--summary", *other], state=fake, login=host)
    assert fake.seen == []  # refused before any read


def write_tick(state: Path, action: str, running: Running | None = None) -> None:
    record = TickRecord(NOW - dt.timedelta(minutes=4), action, "r", None, None, running)
    (state / TICK).write_text(json.dumps(record.record()), encoding="utf-8")


def test_s091_2_the_gate_line_names_tick_session_result_and_landed(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    landed = Landed(1592, NOW - dt.timedelta(hours=1))
    assert read_gate_state(state, True, None).text(NOW) == (
        "no tick recorded; no session runs; no session has ended with a result yet;"
        " no landed pull request in the last 10 commits"
    )
    write_tick(state, "RUNNING", Running("f7a49869-9c91", "ISSUES UNBLOCKED", 3, 0))
    result = LastResult("0b1c2d3e-aaaa", "PRS_OPEN #1599", NOW - dt.timedelta(hours=2))
    (state / LAST_RESULT).write_text(json.dumps(result.record()), encoding="utf-8")
    assert read_gate_state(state, True, landed).text(NOW) == (
        "RUNNING 4 min ago: session f7a49869 on ISSUES UNBLOCKED;"
        " last result 2 h ago (session 0b1c2d3e on PRS_OPEN #1599); last landed #1592 1 h ago"
    )
    write_tick(state, "STALLED", Running("5e5e5e5e-1", "NEW #3", 40, 30))
    assert "STALLED 4 min ago: session 5e5e5e5e on NEW #3;" in read_gate_state(state, True, landed).text(NOW)
    write_tick(state, "LAUNCH")
    save_launch(state / RECORD, Launch("fp", "abcdef1234", NOW, item="NEW #774"))
    assert read_gate_state(state, True, landed).text(NOW).startswith("LAUNCH 4 min ago: session abcdef12 on NEW #774;")
    write_tick(state, "SESSION_DEAD")
    assert read_gate_state(state, True, landed).running is not None
    write_tick(state, "QUIET")
    assert "QUIET 4 min ago: no session runs;" in read_gate_state(state, True, landed).text(NOW)


def test_s091_3_an_unreadable_state_file_is_its_parts_error(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / TICK).write_text("{", encoding="utf-8")
    (state / LAST_RESULT).write_text('{"session": "s"}', encoding="utf-8")
    found = read_gate_state(state, True, None)
    shown = found.text(NOW)
    assert shown.startswith(f"unread {TICK}: ") and f"; unread {LAST_RESULT}: " in shown
    assert found.record()["tick_error"] and found.record()["result_error"]
    write_tick(state, "LAUNCH")
    (state / RECORD).write_text("[]", encoding="utf-8")
    assert f"LAUNCH 4 min ago: unread {RECORD}: " in read_gate_state(state, True, None).text(NOW)
    assert read_gate_state(state, False, None) == GateState(False)
    assert GateState(False).text(NOW) == "none: no [agents] in .github/shipmill.toml"


def test_s091_3_unreadable_tick_still_prints_the_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = configured(repo_with_release(tmp_path / "repo"))
    state = Git(root).root / ".git" / "shipmill"
    state.mkdir()
    (state / TICK).write_text("not json", encoding="utf-8")
    code, out, _ = run_summary(root, capsys)
    assert code == 0
    assert out.splitlines()[1].startswith(f"  gate             unread {TICK}: ")


def test_s091_4_every_open_item_counts_on_exactly_one_line() -> None:
    issues = [
        Issue(1, "NEEDS_DECISION"),
        Issue(2, "NEEDS_PR"),
        Issue(3, "POSTPONED"),
        Issue(4, "TRIAGED", verdict="opportunity"),
        Issue(5, "CLOSED_STATE_IGNORED", closed=True),
    ]
    found = facts(Row("ISSUES", REPO, "NEEDS_PR #2", True), issues=issues, pulls=[Pull(9, False, "CLEAN", "main")])
    got = holders(found)
    counted = [n for h in Holder for n in (*got.issues.get(h, ()), *got.pulls.get(h, ()))]
    assert sorted(counted) == [1, 2, 3, 4, 9]  # each open item once; the closed one never
    assert [line_of(got, n) for n in (1, 2, 3, 4)] == [
        Holder.MAINTAINER,
        Holder.AGENT,
        Holder.NOBODY,
        Holder.MAINTAINER,
    ]


@pytest.mark.parametrize(
    "row",
    [
        Row("GATE_RETRY", "ISSUES NEEDS_PR #2", "after 2026-11-25T12:15:00+00:00 (1 error end in a row)", False),
        Row("GATE_IDLE", "ISSUES NEEDS_PR #2", "idle since 2026-11-24", False),
        Row("GATE_PAUSED", "limit", "until 2026-11-25T14:00:00+00:00: a usage limit", False),
    ],
)
def test_s091_5_a_gate_row_holding_it_counts_as_needs_attention_first(row: Row) -> None:
    gate_row = Row("ISSUES", REPO, "NEEDS_PR #2", True)
    found = facts(gate_row, row, issues=[Issue(2, "NEEDS_PR")])
    assert line_of(holders(found), 2) is Holder.ATTENTION
    # a maintainer's condition beside it doesn't move it off needs attention
    asked = facts(gate_row, row, Row("HOLD", "#7", "h", False), issues=[Issue(2, "NEEDS_PR")])
    if row.state == "GATE_PAUSED":  # a hold stops the gate's turn, so no pause applies to it
        assert line_of(holders(asked), 2) is not Holder.ATTENTION
    assert line_of(holders(facts(gate_row, issues=[Issue(2, "NEEDS_PR")])), 2) is Holder.AGENT


def test_s091_5_held_conditions_win_over_every_who() -> None:
    held = Condition("r", Who.AGENT, "c", held=True)
    assert own_holder([Condition("m", Who.MAINTAINER, "c"), held]) is Holder.ATTENTION


@pytest.mark.parametrize(
    ("whos", "holder"),
    [
        ((Who.EVENT, Who.AGENT, Who.MAINTAINER), Holder.MAINTAINER),
        ((Who.EVENT, Who.AGENT), Holder.AGENT),
        ((Who.EVENT, Who.PERSON), Holder.NOBODY),
        ((Who.PERSON,), Holder.NOBODY),
    ],
)
def test_s091_6_maintainer_then_agent_then_nobody(whos: tuple[Who, ...], holder: Holder) -> None:
    assert own_holder([Condition(str(i), w, "c") for i, w in enumerate(whos)]) is holder


def test_s091_7_an_issue_counts_where_its_pull_request_or_what_it_waits_on_sits() -> None:
    opened = frozenset({2, 3, 9, 11})
    assert linked(REPO, Issue(2, "IN_PROGRESS", note="#9:open #10:merged"), opened) == (9,)
    blocked = Issue(3, "BLOCKED", note=f"waits on {REPO}#11:open, {REPO}#12:closed, acme/other#2:open")
    assert linked(REPO, blocked, opened) == (11,)
    assert linked(REPO, Issue(4, "NEEDS_PR", note="#9:open"), opened) == ()
    in_progress = Issue(2, "IN_PROGRESS", note="#9:open")
    found = facts(
        Row("PRS_OPEN", REPO, "#9", False),
        issues=[in_progress],
        pulls=[Pull(9, False, "CLEAN", "main")],
        autonomy=AutonomyPolicy(land=Autonomy.ACT),
    )
    assert line_of(holders(found), 2) is line_of(holders(found), 9) is Holder.AGENT
    asked = dataclasses.replace(found, rows=[*found.rows, Row("NEEDS_DECISION", REPO, "#9", False)])
    assert line_of(holders(asked), 9) is Holder.MAINTAINER and line_of(holders(asked), 2) is Holder.MAINTAINER


def test_s091_7_the_first_line_among_its_own_and_its_links_and_cycles_end() -> None:
    own = {1: Holder.NOBODY, 2: Holder.AGENT, 3: Holder.MAINTAINER, 4: Holder.NOBODY, 5: Holder.ATTENTION}
    assert resolve(own, {1: (2,), 2: (3,)}) == {**own, 1: Holder.MAINTAINER, 2: Holder.MAINTAINER}
    looped = resolve(own, {1: (2,), 2: (1,), 4: (1,), 3: (5,)})
    assert looped[1] is Holder.NOBODY and looped[2] is Holder.AGENT  # each by its own conditions
    assert looped[4] is Holder.NOBODY  # outside the cycle: its own and #1's, which is #1's own
    assert looped[3] is Holder.ATTENTION


def test_s091_8_json_is_one_object(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = configured(repo_with_release(tmp_path / "repo"))
    code, out, _ = run_summary(root, capsys, "--json")
    assert code == 0 and out.count("\n") == 1
    found = json.loads(out)
    assert set(found) == {"repo", "gate", "totals", "split"}
    assert found["repo"] == REPO
    assert found["totals"] == {"issues": 1, "pulls": 1}
    assert found["gate"] == {
        "configured": True,
        "tick": None,
        "tick_error": None,
        "running": None,
        "running_error": None,
        "result": None,
        "result_error": None,
        "landed": {"number": 8, "at": "2026-11-25T11:00:00+00:00"},
    }
    assert set(found["split"]) == {"maintainer", "agent", "attention", "nobody"}
    assert found["split"]["maintainer"] == {"issues": [4], "pulls": []}
    assert found["split"]["agent"] == {"issues": [], "pulls": [9]}  # its check failed: a session fixes it
    assert not any(found["split"][h] != {"issues": [], "pulls": []} for h in ("attention", "nobody"))
    unconfigured = repo_with_release(tmp_path / "bare")
    _, bare, _ = run_summary(unconfigured, capsys, "--json")
    assert json.loads(bare)["gate"] == {"configured": False}


def test_s091_8_split_numbers_ascend() -> None:
    issues = [Issue(n, "TRIAGED", verdict="opportunity") for n in (30, 4, 17)]
    assert holders(facts(issues=issues)).issues[Holder.MAINTAINER] == (4, 17, 30)


def test_s091_9_summary_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = configured(repo_with_release(tmp_path / "repo"))
    _, _, fake = run_summary(root, capsys)
    gh = [c for c in fake.seen if c[0] == "gh"]
    assert ["gh", "pr", "view", "9", "-R", REPO, "--json", "statusCheckRollup,reviewDecision,labels"] in gh
    assert not any(set(c) & WRITES for c in gh)
    assert not any(Path(c[0]).name == "shipmill" or c[1:2] == ["gh"] for c in fake.seen)  # no shipmill gh


def test_s091_1_a_gate_without_agents_reads_none(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = repo_with_release(tmp_path / "repo")
    _, out, _ = run_summary(root, capsys)
    assert out.splitlines()[1] == "  gate             none: no [agents] in .github/shipmill.toml"
    assert gate().agents is not None  # the unit facts' gate is configured
