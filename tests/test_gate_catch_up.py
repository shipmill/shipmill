"""`shipmill gate` catches the local default branch up to origin's by fast-forward only, where
that can't lose work (#886, D-66). Each test runs the gate from a detached linked gate
checkout, as tmp/shipmill-gate is in shipmill-setup, against a real bare origin that a
second clone pushes to"""

import dataclasses
import datetime as dt
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig
from shipmill.autonomy import Hold
from shipmill.catch_up import CatchUp, How
from shipmill.cli import _gate_exit
from shipmill.config import Table
from shipmill.errors import ReleaseError
from shipmill.gate import Action, Decision, Waiting, gate, state_dir, tick_lines, tick_record
from shipmill.gitrepo import Git
from shipmill.worktrees import Judged

from .test_gate import ISSUES, FakeClaude, FakeNotifier, cfg, host, on_hold
from .test_worktrees import run

REPO = "romamo/demo"
GATE = "tmp/shipmill-gate"

Tick = tuple[Decision, str | None, tuple[Waiting, ...], tuple[Judged, ...]]


@dataclass
class Repo:
    """A main checkout on main with the gate's detached worktree under it, and a pusher that
    moves origin's main on"""

    root: Path
    pusher: Path
    pushed: int = 0  # the commits advance made, each writing its own count

    def git(self, where: Path | None = None) -> Git:
        return Git(where or self.root, "t", "t@example.com")

    def commit(self, where: Path, name: str, text: str) -> str:
        (where / name).write_text(text, encoding="utf-8")
        git = self.git(where)
        git.run("add", "--", name)
        git.run("commit", "-q", "-m", f"Write {name}")
        return git.sha()

    def advance(self, n: int) -> str:
        """n commits on origin's main, pushed from the other clone"""
        for _ in range(n):
            self.pushed += 1
            self.commit(self.pusher, "remote.txt", f"{self.pushed}\n")
        self.git(self.pusher).run("push", "-q", "origin", "main")
        return self.git(self.pusher).sha()

    def main(self) -> str:
        return self.git().sha("refs/heads/main")

    def head(self) -> str:
        return self.git().run("rev-parse", "--abbrev-ref", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    origin = tmp_path / "romamo" / "demo.git"  # its path ends in romamo/demo.git: the gate's origin check
    run("git", "init", "-q", "--bare", "-b", "main", str(origin))
    root, pusher = tmp_path / "work", tmp_path / "pusher"
    run("git", "clone", "-q", str(origin), str(root))
    r = Repo(root, pusher)
    r.git().run("checkout", "-q", "-b", "main")
    r.commit(root, ".gitignore", "tmp/\n")  # the gate's worktree lives under tmp/, ignored as in shipmill-setup
    r.git().run("push", "-q", "-u", "origin", "main")
    run("git", "clone", "-q", str(origin), str(pusher))
    r.git().run("worktree", "add", "-q", "--detach", str(root / GATE), "origin/main")
    return r


def no_prune(now: dt.datetime, dry_run: bool) -> list[Judged]:
    return []


def tick(
    r: Repo,
    catch_up: Callable[[], bool] | None = lambda: True,
    dry_run: bool = False,
    hold: Callable[[], Hold] = on_hold,
) -> Tick:
    git = r.git(r.root / GATE)
    return gate(
        git,
        REPO,
        lambda: cfg(),
        FakeClaude(),
        lambda _: [ISSUES],
        dt.datetime.now(dt.UTC),
        hold,
        FakeNotifier(),
        no_prune,
        dry_run=dry_run,
        login=host,
        catch_up=catch_up,
    )


def lines(t: Tick, dry_run: bool = False) -> list[str]:
    return tick_lines(*t, dry_run=dry_run)


def record(t: Tick, dry_run: bool = False) -> object:
    return json.loads(json.dumps(tick_record(*t, dry_run=dry_run)))["catch_up"]


def test_886_a_default_branch_checked_out_nowhere_moves_by_ref_fetch(repo: Repo) -> None:
    repo.git().run("switch", "-q", "-c", "feat/x")
    head = repo.advance(3)
    t = tick(repo)
    assert repo.main() == head and repo.head() == "feat/x"  # the checkout stays on its branch
    assert t[0].catch_up == CatchUp("main", 3, How.FETCH)
    assert lines(t)[-1] == "  catch-up: main 3 commits → origin/main"
    assert record(t) == {"branch": "main", "behind": 3, "how": "fetch", "error": None}


def test_886_a_clean_main_checkout_on_the_default_branch_pulls(repo: Repo) -> None:
    head = repo.advance(1)
    t = tick(repo)
    assert repo.main() == head and repo.git().sha() == head and repo.head() == "main"
    assert (repo.root / "remote.txt").read_text(encoding="utf-8") == "1\n"  # the working tree moved with it
    assert repo.git().run("status", "--porcelain") == ""
    assert lines(t)[-1] == "  catch-up: main 1 commit → origin/main"
    assert record(t) == {"branch": "main", "behind": 1, "how": "pull", "error": None}


def test_886_a_held_tick_still_catches_up_and_a_launch_does_too(repo: Repo) -> None:
    head = repo.advance(1)
    held = tick(repo)
    assert held[0].action is Action.HELD and repo.main() == head
    head = repo.advance(1)
    launch = tick(repo, hold=Hold)
    assert (launch[0].action, launch[1], repo.main()) == (Action.LAUNCH, "s1", head)
    assert lines(launch)[-2:] == ["  launched s1: claude attach s1", "  catch-up: main 1 commit → origin/main"]


@pytest.mark.parametrize("change", ["tracked", "untracked"])
def test_886_a_dirty_checkout_changes_nothing(repo: Repo, change: str) -> None:
    before = repo.main()
    repo.advance(2)
    (repo.root / (".gitignore" if change == "tracked" else "notes.txt")).write_text("x\n", encoding="utf-8")
    t = tick(repo)
    assert repo.main() == before
    assert t[0].catch_up == CatchUp("main", 2) and lines(t) == lines(tick(repo, catch_up=None))
    assert record(t) == {"branch": "main", "behind": 2, "how": None, "error": None}


def test_886_a_branch_ahead_changes_nothing(repo: Repo) -> None:
    ahead = repo.commit(repo.root, "local.txt", "mine\n")
    t = tick(repo)
    assert repo.main() == ahead and t[0].catch_up == CatchUp("main", 0)
    assert not any("catch" in line for line in lines(t))


@pytest.mark.parametrize("checked_out", [True, False])
def test_886_a_diverged_branch_changes_nothing(repo: Repo, checked_out: bool) -> None:
    mine = repo.commit(repo.root, "local.txt", "mine\n")
    if not checked_out:
        repo.git().run("switch", "-q", "-c", "feat/x")
    repo.advance(2)
    t = tick(repo)
    assert repo.main() == mine and t[0].catch_up == CatchUp("main", 2)
    assert not any("catch" in line for line in lines(t))


def test_886_a_default_branch_checked_out_in_another_worktree_changes_nothing(repo: Repo) -> None:
    """The main checkout is on another branch and a linked worktree holds main: neither a ref
    fetch, which would leave that worktree's files behind its branch, nor a failure line"""
    repo.git().run("switch", "-q", "-c", "feat/x")
    other = repo.root / "tmp" / "other"
    repo.git().run("worktree", "add", "-q", str(other), "main")
    before = repo.main()
    repo.advance(2)
    t = tick(repo)
    assert repo.main() == before and t[0].catch_up == CatchUp("main", 2)
    assert not any("catch" in line for line in lines(t))


def test_886_an_up_to_date_branch_prints_nothing(repo: Repo) -> None:
    t = tick(repo)
    assert t[0].catch_up == CatchUp("main", 0)
    assert lines(t) == lines(tick(repo, catch_up=None))
    assert record(t) == {"branch": "main", "behind": 0, "how": None, "error": None}


@pytest.mark.parametrize("checked_out", [True, False])
def test_886_a_dry_run_says_what_it_would_move_and_moves_nothing(repo: Repo, checked_out: bool) -> None:
    if not checked_out:
        repo.git().run("switch", "-q", "-c", "feat/x")
    before = repo.main()
    repo.advance(2)
    t = tick(repo, dry_run=True)
    assert (repo.main(), repo.head()) == (before, "main" if checked_out else "feat/x")
    assert t[0].catch_up == CatchUp("main", 2, How.PULL if checked_out else How.FETCH)
    assert lines(t, dry_run=True)[-1] == "  would catch up: main 2 commits → origin/main"


def test_886_catch_up_false_runs_no_step(repo: Repo) -> None:
    before = repo.main()
    repo.advance(2)
    t = tick(repo, catch_up=lambda: False)
    assert repo.main() == before and t[0].catch_up is None and record(t) is None
    assert not any("catch" in line for line in lines(t))


def test_886_a_failed_catch_up_prints_one_line_and_leaves_the_tick_as_it_was(repo: Repo) -> None:
    repo.git().run("switch", "-q", "-c", "feat/x")
    before = repo.main()
    repo.advance(1)
    common = Path(repo.git().run("rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    (common / "refs/heads/main.lock").write_text("", encoding="utf-8")  # another git holds the ref
    clean = tick(repo, catch_up=None)
    failed = tick(repo)
    assert repo.main() == before
    catch = failed[0].catch_up
    assert catch is not None and catch.error is not None
    assert catch.error.startswith("git fetch -q origin main:main failed: ")
    assert dataclasses.replace(failed[0], catch_up=None) == clean[0]
    assert lines(failed) == [*lines(clean), f"  catch-up failed: {catch.error}"]
    assert record(failed) == {"branch": None, "behind": 0, "how": None, "error": catch.error}
    assert _gate_exit(failed[0]) == _gate_exit(clean[0]) == 0
    assert "catch" not in (state_dir(repo.git(repo.root / GATE)) / "tick.json").read_text(encoding="utf-8")
    launch = tick(repo, hold=Hold)  # a failed catch-up never stops a launch
    assert (launch[0].action, launch[1]) == (Action.LAUNCH, "s1")
    assert launch[0].catch_up is not None and launch[0].catch_up.error == catch.error


def test_886_a_config_read_that_fails_is_the_catch_ups_error(repo: Repo) -> None:
    def unreadable() -> bool:
        raise ReleaseError(".github/shipmill.toml: [agents] catch_up must be true or false\nmore")

    clean = tick(repo, catch_up=None)
    failed = tick(repo, catch_up=unreadable)
    assert dataclasses.replace(failed[0], catch_up=None) == clean[0]
    error = ".github/shipmill.toml: [agents] catch_up must be true or false"
    assert lines(failed) == [*lines(clean), f"  catch-up failed: {error}"]


def agents(**keys: object) -> AgentsConfig:
    return AgentsConfig.parse(Table({"agents": {"prompt": "/t", **keys}}, "x").table("agents"))


def test_886_catch_up_defaults_to_true() -> None:
    assert agents().catch_up is True
    assert (agents(catch_up=False).catch_up, agents(catch_up=True).catch_up) == (False, True)


@pytest.mark.parametrize("value", ["false", 0, 1, "no"])
def test_886_the_config_refuses_a_catch_up_that_is_not_a_boolean(value: object) -> None:
    with pytest.raises(ReleaseError, match="catch_up"):
        agents(catch_up=value)
