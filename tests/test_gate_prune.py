"""`shipmill gate` prunes the repository's landed worktrees (spec 002, S-002-15 and S-002-16)
after its decision, when a prune is due, and a prune that fails never fails the tick (spec
045); each test runs the gate from a detached linked gate checkout, as tmp/shipmill-gate is
in shipmill-setup, with the real judge and prune"""

import dataclasses
import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig
from shipmill.autonomy import Hold
from shipmill.cli import _gate_exit
from shipmill.config import Table
from shipmill.errors import ReleaseError
from shipmill.gate import (
    PRUNE,
    Action,
    Decision,
    Finding,
    PruneDue,
    PruneRecord,
    PruneRun,
    StateRead,
    Waiting,
    gate,
    load_prune,
    prune_step,
    pruner,
    save_prune,
    state_dir,
    tick_lines,
    tick_record,
)
from shipmill.status import Verdict as StatusVerdict
from shipmill.status import host_checks, report
from shipmill.worktrees import Judged, LiveSession, Verdict

from .test_factory import fake_host, run_checks, tree
from .test_gate import ISSUES, FakeClaude, FakeNotifier, bg, cfg, host, on_hold
from .test_status_picture import facts
from .test_status_picture import gate as status_gate
from .test_worktrees import CHANGELOG, Checkout, branches, run

REPO = "romamo/demo"
DONE = ".claude/worktrees/done"
GATE = "tmp/shipmill-gate"
KEYS = {
    "walk",  # spec 046
    "item",
    "running",  # S-048-16
    "action",
    "reason",
    "work",
    "stopped",
    "launched",
    "identity",
    "waiting",
    "pruned",
    "mode",
    "decisions",  # "plugin", the daily plugin update, went with plugin_update (S-031-21)
    "loaded",
    "pypi",  # spec 031's PyPI answer for the version sessions load
    "plugin_notice",  # spec 031's once-per-release notification
    "detached",
    "hooks",
    "auth",  # spec 035's kind: token-file or login
    "preflight",  # #500's Claude Code login preflight
    "dead",  # #500's dead session
    "prune",  # spec 045's prune: whether it ran, and its error
}

Tick = tuple[Decision, str | None, tuple[Waiting, ...], tuple[Judged, ...]]


@pytest.fixture
def repo(tmp_path: Path) -> Checkout:
    """A main checkout whose origin's path ends in romamo/demo.git, so the gate's origin
    check passes, with the gate's detached checkout and one landed worktree beside it"""
    origin = tmp_path / "romamo" / "demo.git"
    run("git", "init", "-q", "--bare", "-b", "main", str(origin))
    root = tmp_path / "work"
    run("git", "clone", "-q", str(origin), str(root))
    c = Checkout(root)
    c.git().run("checkout", "-q", "-b", "main")
    c.commit(root, {"CHANGELOG.md": CHANGELOG, "app.py": "VALUE = 1\n"}, "Start")
    c.push_main()
    c.add(GATE, "--detach")
    c.add(DONE, "-b", "feat/done")
    return c


def tick(
    c: Checkout,
    claude: FakeClaude,
    hold: Callable[[], Hold] = Hold,
    findings: tuple[Finding, ...] = (ISSUES,),
    dry_run: bool = False,
    refresh: bool = False,
    prune_hours: int | None = None,
    later: dt.timedelta = dt.timedelta(),
    rows: Callable[[StateRead], list[Finding]] | None = None,
) -> Tick:
    git = c.git(c.root / GATE)
    now = dt.datetime.now(dt.UTC) + later  # the worktrees' ages count from the real clock
    return gate(
        git,
        REPO,
        lambda: cfg(),
        claude,
        rows or (lambda _: list(findings)),
        now,
        hold,
        FakeNotifier(),
        pruner(git, c.github, c.sessions),
        refresh_checkout=refresh,
        dry_run=dry_run,
        login=host,
        prune_hours=None if prune_hours is None else (lambda: prune_hours),
    )


def prune_file(c: Checkout) -> Path:
    return state_dir(c.git(c.root / GATE)) / PRUNE


def head(path: Path) -> str:
    return run("git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def test_a_refresh_tick_detaches_the_gate_worktree_a_session_left_on_a_branch(repo: Checkout) -> None:
    """#247: a session switched tmp/shipmill-gate to its branch; the next tick detaches it,
    says so, and launches, where it used to fail every tick"""
    gate_root = repo.root / GATE
    repo.git(gate_root).run("switch", "-q", "-c", "fix/1-thing")
    claude = FakeClaude()
    decision, launched, waiting, pruned = tick(repo, claude, refresh=True)
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    assert head(gate_root) == "HEAD"
    assert "fix/1-thing" in branches(repo)  # the branch stays
    lines = tick_lines(decision, launched, waiting, pruned, dry_run=False)
    assert lines[1] == f"  detached {gate_root} from fix/1-thing"
    record = json.loads(json.dumps(tick_record(decision, launched, waiting, pruned, dry_run=False)))
    assert record["detached"] == {"path": str(gate_root), "branch": "fix/1-thing"}


def test_a_refresh_tick_on_a_detached_gate_worktree_reports_no_detach(repo: Checkout) -> None:
    decision, launched, waiting, pruned = tick(repo, FakeClaude(), refresh=True)
    assert decision.detached is None
    assert not any("detached" in line for line in tick_lines(decision, launched, waiting, pruned, dry_run=False))
    assert tick_record(decision, launched, waiting, pruned, dry_run=False)["detached"] is None


def test_a_dry_run_refresh_tick_leaves_the_gate_worktree_on_its_branch(repo: Checkout) -> None:
    gate_root = repo.root / GATE
    repo.git(gate_root).run("switch", "-q", "-c", "fix/1-thing")
    decision, launched, waiting, pruned = tick(repo, FakeClaude(), dry_run=True, refresh=True)
    assert (decision.action, decision.detached) == (Action.LAUNCH, None)
    assert head(gate_root) == "fix/1-thing"
    assert tick_record(decision, launched, waiting, pruned, dry_run=True)["detached"] is None


def test_s002_15_a_tick_prunes_the_landed_worktrees_and_reports_them(repo: Checkout) -> None:
    young = repo.add("tmp/wt-young", "-b", "feat/young", hours=5)
    claude = FakeClaude()
    decision, launched, waiting, pruned = tick(repo, claude)
    assert (decision.action, launched) == (Action.LAUNCH, "s1")
    assert [(j.path, j.worktree.branch) for j in pruned] == [(DONE, "feat/done")]
    assert not (repo.root / DONE).exists()
    assert (repo.root / GATE).is_dir() and young.is_dir()  # the gate's own checkout is never a candidate
    assert branches(repo) == {"main", "feat/young"}
    lines = tick_lines(decision, launched, waiting, pruned, dry_run=False)
    assert f"  pruned {DONE} (feat/done)" in lines
    record = json.loads(json.dumps(tick_record(decision, launched, waiting, pruned, dry_run=False)))
    assert set(record) == KEYS  # every key the gate printed before, and pruned
    assert record["pruned"] == [DONE]


def test_s002_15_a_held_tick_still_prunes(repo: Checkout) -> None:
    claude = FakeClaude()
    decision, launched, waiting, pruned = tick(repo, claude, hold=on_hold)
    assert (decision.action, launched, claude.launched) == (Action.HELD, None, [])
    assert [j.path for j in pruned] == [DONE] and not (repo.root / DONE).exists()
    assert tick_lines(decision, launched, waiting, pruned, dry_run=False)[1:] == [f"  pruned {DONE} (feat/done)"]
    assert tick_record(decision, launched, waiting, pruned, dry_run=False)["pruned"] == [DONE]


def test_s002_15_a_tick_with_nothing_landed_prunes_nothing(repo: Checkout) -> None:
    """A worktree a live session works in stays, as does one with work not landed"""
    open_ = repo.add("tmp/wt-open", "-b", "feat/open")
    repo.commit(open_, {"feature.py": "A = 1\n"}, "Unlanded")
    repo.sessions.rows = [LiveSession("shipmill romamo/demo 2026-10-06 09:00", repo.root / DONE)]
    decision, launched, waiting, pruned = tick(repo, FakeClaude(), findings=())
    assert (decision.action, pruned) == (Action.QUIET, ())
    assert (repo.root / DONE).is_dir() and open_.is_dir()
    assert tick_record(decision, launched, waiting, pruned, dry_run=False)["pruned"] == []
    assert tick_lines(decision, launched, waiting, pruned, dry_run=False) == [
        "QUIET: nothing needs an agent; read tiers 1-8"
    ]


def test_s002_16_a_dry_run_lists_what_it_would_prune_and_removes_nothing(repo: Checkout) -> None:
    before = repo.state()
    claude = FakeClaude()
    decision, launched, waiting, pruned = tick(repo, claude, dry_run=True)
    assert (decision.action, launched, claude.launched) == (Action.LAUNCH, None, [])
    assert repo.state() == before and (repo.root / DONE).is_dir()
    assert f"  would prune {DONE} (feat/done)" in tick_lines(decision, launched, waiting, pruned, dry_run=True)
    assert tick_record(decision, launched, waiting, pruned, dry_run=True)["pruned"] == [DONE]


def test_s045_1_a_held_waiting_or_running_tick_prunes_after_its_decision(repo: Checkout) -> None:
    """The hold check, then the busy one, end the tick, and the prune still runs after them,
    its pruned line after the decision's lines"""
    held_tick = tick(repo, FakeClaude(), hold=on_hold)
    assert held_tick[0].action is Action.HELD and [j.path for j in held_tick[3]] == [DONE]
    lines = tick_lines(*held_tick, dry_run=False)
    assert lines[-1] == f"  pruned {DONE} (feat/done)" and lines[0].startswith("HELD: ")
    for listed, action in ((bg("a", "idle", "blocked"), Action.WAITING), (bg("a", "busy", "working"), Action.RUNNING)):
        name = action.value.lower()
        repo.add(f"tmp/wt-{name}", "-b", f"feat/{name}")
        decision, launched, waiting, pruned = tick(repo, FakeClaude([listed]))
        assert decision.action is action
        assert [j.path for j in pruned] == [f"tmp/wt-{name}"] and not (repo.root / f"tmp/wt-{name}").exists()
        lines = tick_lines(decision, launched, waiting, pruned, dry_run=False)
        assert lines[0].startswith(f"{action.value}: ") and lines[-1] == f"  pruned tmp/wt-{name} (feat/{name})"


def test_s045_1_a_launch_prints_its_pruned_line_after_the_launch(repo: Checkout) -> None:
    decision, launched, waiting, pruned = tick(repo, FakeClaude())
    lines = tick_lines(decision, launched, waiting, pruned, dry_run=False)
    assert lines[-2:] == ["  launched s1: claude attach s1", f"  pruned {DONE} (feat/done)"]


def test_s045_2_a_launch_tick_whose_prune_fails_still_launches(repo: Checkout) -> None:
    repo.github.pulls_error = "HTTP 502"
    claude = FakeClaude()
    decision, launched, _, pruned = tick(repo, claude)
    assert (decision.action, launched, pruned) == (Action.LAUNCH, "s1", ())
    assert [name for name, _ in claude.launched] != []
    assert decision.prune == PruneRun(True, "gh pr list failed: HTTP 502")
    assert (repo.root / DONE).is_dir()


def test_s045_3_a_tick_that_fails_before_its_decision_prunes_nothing(repo: Checkout) -> None:
    before = repo.state()

    def unreadable(_: StateRead) -> list[Finding]:
        raise ReleaseError("watch_state.py failed (exit 2)")

    with pytest.raises(ReleaseError, match="watch_state.py failed"):
        tick(repo, FakeClaude(), rows=unreadable)
    assert repo.state() == before and (repo.root / DONE).is_dir()
    assert not prune_file(repo).exists()


def test_s045_4_a_tick_prunes_only_when_prune_hours_have_passed(repo: Checkout) -> None:
    first = tick(repo, FakeClaude(), hold=on_hold, prune_hours=6)
    assert [j.path for j in first[3]] == [DONE]
    at = load_prune(prune_file(repo))
    assert at is not None
    later = repo.add("tmp/wt-later", "-b", "feat/later")
    soon = tick(repo, FakeClaude(), hold=on_hold, prune_hours=6, later=dt.timedelta(hours=5, minutes=59))
    assert (soon[0].prune, soon[3]) == (PruneRun(False), ()) and later.is_dir()
    assert tick_lines(*soon, dry_run=False) == [soon[0].action.value + ": " + soon[0].reason]
    assert load_prune(prune_file(repo)) == at  # an attempt not due writes nothing
    due = tick(repo, FakeClaude(), hold=on_hold, prune_hours=6, later=dt.timedelta(hours=6))
    assert due[0].prune == PruneRun(True) and [j.path for j in due[3]] == ["tmp/wt-later"]


def test_s045_4_prune_hours_0_prunes_on_every_tick(repo: Checkout) -> None:
    assert tick(repo, FakeClaude(), hold=on_hold, prune_hours=0)[0].prune == PruneRun(True)
    repo.add("tmp/wt-next", "-b", "feat/next")
    again = tick(repo, FakeClaude(), hold=on_hold, prune_hours=0)
    assert again[0].prune == PruneRun(True) and [j.path for j in again[3]] == ["tmp/wt-next"]


def agents(**keys: object) -> AgentsConfig:
    return AgentsConfig.parse(Table({"agents": {"prompt": "/t", **keys}}, "x").table("agents"))


def test_s045_5_prune_hours_defaults_to_6_and_accepts_0_to_168() -> None:
    assert agents().prune_hours == 6
    assert (agents(prune_hours=0).prune_hours, agents(prune_hours=168).prune_hours) == (0, 168)


@pytest.mark.parametrize("value", [-1, 169, "6", 1.5, True])
def test_s045_5_the_config_refuses_a_prune_hours_that_is_not_an_integer_from_0_to_168(value: object) -> None:
    with pytest.raises(ReleaseError, match="prune_hours"):
        agents(prune_hours=value)


def test_s045_6_a_failing_prune_prints_its_first_line_and_changes_nothing_else(repo: Checkout) -> None:
    clean = tick(repo, FakeClaude(), hold=on_hold)
    assert clean[0].prune == PruneRun(True)
    repo.add("tmp/wt-again", "-b", "feat/again")
    repo.github.pulls_error = "HTTP 502\nmore detail"
    decision, launched, waiting, pruned = tick(repo, FakeClaude(), hold=on_hold)
    assert pruned == () and (repo.root / "tmp/wt-again").is_dir()
    lines = tick_lines(decision, launched, waiting, pruned, dry_run=False)
    assert lines == [*tick_lines(*clean[:3], (), dry_run=False), "  prune failed: gh pr list failed: HTTP 502"]
    assert not any("pruned" in line for line in lines)
    assert dataclasses.replace(decision, prune=None) == dataclasses.replace(clean[0], prune=None)
    assert _gate_exit(decision) == _gate_exit(clean[0]) == 0


def test_s045_6_a_removal_git_refuses_is_the_prunes_error(repo: Checkout) -> None:
    common = Path(repo.git().run("rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    (common / "refs/heads/feat/done.lock").write_text("", encoding="utf-8")  # another git holds the ref
    claude = FakeClaude()
    decision, launched, waiting, pruned = tick(repo, claude)
    assert (decision.action, launched, pruned) == (Action.LAUNCH, "s1", ())
    assert decision.prune is not None and decision.prune.error is not None
    assert decision.prune.error.startswith(f"prune stopped at {DONE} (feat/done): git branch -D feat/done failed")


def test_s045_6_any_other_exception_still_ends_the_tick(repo: Checkout) -> None:
    git = repo.git(repo.root / GATE)

    def buggy(now: dt.datetime, dry_run: bool) -> list[Judged]:
        raise KeyError("a bug")

    with pytest.raises(KeyError):
        gate(git, REPO, lambda: cfg(), FakeClaude(), lambda _: [], dt.datetime.now(dt.UTC), Hold, FakeNotifier(), buggy)


def test_s045_7_json_prints_whether_the_prune_ran_and_its_error(repo: Checkout) -> None:
    ran = tick(repo, FakeClaude(), hold=on_hold, prune_hours=6)
    record = json.loads(json.dumps(tick_record(*ran, dry_run=False)))
    assert set(record) == KEYS and record["prune"] == {"ran": True, "error": None}
    skipped = tick(repo, FakeClaude(), hold=on_hold, prune_hours=6)
    record = tick_record(*skipped, dry_run=False)
    assert (record["prune"], record["pruned"]) == ({"ran": False, "error": None}, [])
    repo.github.pulls_error = "HTTP 502"
    failed = tick(repo, FakeClaude(), hold=on_hold, prune_hours=0)
    record = tick_record(*failed, dry_run=False)
    assert (record["prune"], record["pruned"]) == ({"ran": True, "error": "gh pr list failed: HTTP 502"}, [])


NOW = dt.datetime(2026, 10, 27, 9, 0, tzinfo=dt.UTC)


def test_s045_8_prune_json_records_each_attempt_and_the_first_failure(tmp_path: Path) -> None:
    path = tmp_path / PRUNE
    removed = tree("tmp/wt-x", Verdict.REMOVED, None, 30)

    def works(now: dt.datetime, dry_run: bool) -> list[Judged]:
        return [removed, removed]

    def fails(now: dt.datetime, dry_run: bool) -> list[Judged]:
        raise ReleaseError("gh api graphql -F failed: possible nodes\nmore")

    hour = dt.timedelta(hours=1)
    assert prune_step(path, lambda: 0, fails, NOW, False)[0] == PruneRun(
        True, "gh api graphql -F failed: possible nodes"
    )
    first = json.loads(path.read_text(encoding="utf-8"))
    assert first == {
        "at": NOW.isoformat(),
        "ok": False,
        "error": "gh api graphql -F failed: possible nodes",
        "failing_since": NOW.isoformat(),
        "removed": 0,
    }
    prune_step(path, lambda: 0, fails, NOW + hour, False)
    assert load_prune(path) == PruneRecord(NOW + hour, False, "gh api graphql -F failed: possible nodes", NOW, 0)
    run, pruned = prune_step(path, lambda: 0, works, NOW + 2 * hour, False)
    assert (run, len(pruned)) == (PruneRun(True), 2)
    assert load_prune(path) == PruneRecord(NOW + 2 * hour, True, None, None, 2)
    prune_step(path, lambda: 0, fails, NOW + 3 * hour, False)
    assert load_prune(path) == PruneRecord(
        NOW + 3 * hour, False, "gh api graphql -F failed: possible nodes", NOW + 3 * hour, 0
    )


def test_s045_8_a_malformed_prune_json_is_the_prunes_error_and_stays(tmp_path: Path) -> None:
    path = tmp_path / PRUNE
    path.write_text('{"at": "2026-10-27T09:00:00+00:00", "ok": true}\n', encoding="utf-8")

    def unused(now: dt.datetime, dry_run: bool) -> list[Judged]:
        raise AssertionError("a prune.json it can't read runs no prune")

    run, pruned = prune_step(path, lambda: 0, unused, NOW, False)
    assert (run.ran, pruned) == (False, ()) and run.error is not None and "delete it to start over" in run.error
    assert path.read_text(encoding="utf-8").startswith('{"at"')
    with pytest.raises(ValueError, match="ok must go with"):
        PruneRecord(NOW, True, "boom", None, 0)


def test_s045_9_a_dry_run_whose_prune_is_not_due_judges_nothing_and_says_when_it_is_due(tmp_path: Path) -> None:
    """#763: the injected judge raises, so a not-due dry run that judged would fail here"""
    path = tmp_path / PRUNE
    save_prune(path, PruneRecord(NOW, True, None, None, 0))
    written = path.read_text(encoding="utf-8")

    def unused(now: dt.datetime, dry_run: bool) -> list[Judged]:
        raise AssertionError("a dry run whose prune isn't due judges nothing")

    run, pruned = prune_step(path, lambda: 6, unused, NOW + dt.timedelta(hours=5, minutes=59), True)
    at = NOW + dt.timedelta(hours=6)
    assert (run, pruned) == (PruneRun(False, due=PruneDue(False, at)), ())
    assert path.read_text(encoding="utf-8") == written
    decision = Decision(Action.QUIET, "nothing needs an agent", (), prune=run)
    assert tick_lines(decision, None, (), pruned, dry_run=True)[1:] == ["  prune due at 2026-10-27T15:00+00:00"]
    record = json.loads(json.dumps(tick_record(decision, None, (), pruned, dry_run=True)))
    assert (record["prune"], record["pruned"]) == (
        {"ran": False, "error": None, "due": False, "at": at.isoformat()},
        [],
    )
    path.write_text('{"at": "2026-10-27T09:00:00+00:00"}\n', encoding="utf-8")  # malformed: the prune's error
    broken, _ = prune_step(path, lambda: 6, unused, NOW, True)
    assert broken.error is not None and "delete it to start over" in broken.error and not broken.ran


def test_s045_9_a_dry_run_tick_whose_prune_is_not_due_lists_nothing(repo: Checkout) -> None:
    save_prune(prune_file(repo), PruneRecord(dt.datetime.now(dt.UTC), True, None, None, 0))  # a prune just ran
    decision, launched, waiting, pruned = tick(repo, FakeClaude(), dry_run=True, prune_hours=6)
    assert pruned == () and decision.prune is not None and decision.prune.due is not None
    lines = tick_lines(decision, launched, waiting, pruned, dry_run=True)
    assert not any("would prune" in line for line in lines) and lines[-1].startswith("  prune due at ")
    assert (repo.root / DONE).is_dir()


def test_s045_9_a_dry_run_whose_prune_is_due_lists_what_it_would_prune_and_writes_nothing(repo: Checkout) -> None:
    ran = dt.datetime.now(dt.UTC) - dt.timedelta(hours=6, minutes=1)
    save_prune(prune_file(repo), PruneRecord(ran, True, None, None, 0))  # due since a minute ago
    written = prune_file(repo).read_text(encoding="utf-8")
    before = repo.state()
    decision, launched, waiting, pruned = tick(repo, FakeClaude(), dry_run=True, prune_hours=6)
    assert [j.path for j in pruned] == [DONE]
    assert decision.prune == PruneRun(True, due=PruneDue(True, ran + dt.timedelta(hours=6)))
    assert repo.state() == before and (repo.root / DONE).is_dir()
    lines = tick_lines(decision, launched, waiting, pruned, dry_run=True)
    assert f"  would prune {DONE} (feat/done)" in lines and not any("prune due at" in line for line in lines)
    assert tick_record(decision, launched, waiting, pruned, dry_run=True)["prune"]["due"] is True  # type: ignore[index]
    assert prune_file(repo).read_text(encoding="utf-8") == written
    prune_file(repo).unlink()  # no prune.json: due, and the dry run writes none
    fresh = tick(repo, FakeClaude(), dry_run=True, prune_hours=6)
    assert fresh[0].prune == PruneRun(True, due=PruneDue(True, None)) and [j.path for j in fresh[3]] == [DONE]
    assert tick_record(*fresh, dry_run=True)["prune"] == {"ran": True, "error": None, "due": True, "at": None}
    assert not prune_file(repo).exists()
    save_prune(prune_file(repo), PruneRecord(dt.datetime.now(dt.UTC), True, None, None, 0))  # a prune just ran
    written = prune_file(repo).read_text(encoding="utf-8")
    every = tick(repo, FakeClaude(), dry_run=True, prune_hours=0)  # prune_hours = 0: due on every run
    assert every[0].prune is not None and every[0].prune.ran and [j.path for j in every[3]] == [DONE]
    assert prune_file(repo).read_text(encoding="utf-8") == written


FAILING = PruneRecord(NOW, False, "gh pr list failed: HTTP 502", NOW - dt.timedelta(hours=12), 0)


def test_s045_10_factory_prints_a_prune_line_after_worktrees() -> None:
    def line(record: PruneRecord | None) -> tuple[bool, list[str]]:
        found = run_checks(dataclasses.replace(fake_host(), prune=lambda: record))
        assert [c.check for c in found][-2:] == ["worktrees", "prune"]
        return found[-1].ok, found[-1].lines()

    assert line(None) == (True, ["  prune          never ran here"])
    assert line(PruneRecord(NOW, True, None, None, 3)) == (
        True,
        ["  prune          last ran 2026-10-27T09:00+00:00, removed 3"],
    )
    assert line(FAILING) == (
        False,
        [
            "  prune          failing since 2026-10-26T21:00+00:00: gh pr list failed: HTTP 502",
            "                 fix: shipmill worktrees --prune",
        ],
    )

    def unreadable() -> PruneRecord | None:
        raise ReleaseError("/x/prune.json is malformed (expected exactly at, error); delete it to start over\nmore")

    (check,) = [c for c in run_checks(dataclasses.replace(fake_host(), prune=unreadable)) if c.check == "prune"]
    assert check.lines() == [
        "  prune          ERROR: /x/prune.json is malformed (expected exactly at, error); delete it to start over"
    ]


def test_s045_11_a_failing_prune_counts_on_the_factory_line_and_keeps_the_verdict() -> None:
    clean, failing = facts(), facts(gate=status_gate(prune=FAILING))
    assert "  factory        OK" in report(clean).text(REPO).splitlines()
    text = report(failing).text(REPO).splitlines()
    assert (
        "  factory        1 problem(s): prune failing since 2026-10-26T21:00+00:00: gh pr list failed: HTTP 502;"
        " shipmill factory"
    ) in text
    assert "                 fix: shipmill worktrees --prune" not in text  # no reason of the verdict's
    assert report(failing).verdict is report(clean).verdict is not StatusVerdict.STUCK
    assert report(failing).reasons == report(clean).reasons
    assert [c.check for c in host_checks(failing)][-1] == "prune"
