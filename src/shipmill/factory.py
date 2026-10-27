"""Spec 044: `shipmill factory`, this host's machinery for the repo, one line per check: the
gate's launchd job and log, its live sessions, the GitHub App, the shipmill installs, the
local checkout, the worktrees, and the gate's last prune (spec 045). Each check runs on its
own: one that fails to run prints `ERROR: <its first line>` and the checks after it still
run (D-55). Read-only"""

import datetime as dt
import json
import shlex
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from shipmill.errors import ReleaseError
from shipmill.gate import PruneRecord, StateRunner, skills_dir, state_failed
from shipmill.plugin import GateCli
from shipmill.status import (
    CHECK_FAILURES,
    Check,
    Detail,
    Gate,
    Main,
    Row,
    checkout_check,
    failed_check,
    first_line,
    gate_check,
    github_app_check,
    guarded,
    parse_rows,
    prune_check,
    sessions_check,
    shipmill_check,
)
from shipmill.worktrees import Judged, Verdict

STALE = dt.timedelta(days=7)  # a kept shipmill worktree older than this gets its own line
# the reasons `shipmill worktrees` keeps a worktree that isn't a shipmill worktree at all
NOT_SHIPMILL = frozenset({"main checkout", "current checkout", "not a shipmill worktree"})


@dataclass(frozen=True, slots=True)
class Worktrees:
    """`shipmill worktrees`'s judging, the main checkout its paths are relative to, and the
    branch releases land on, which the stale ones' fix compares with"""

    judged: Sequence[Judged]
    main: Path
    branch: str


@dataclass(frozen=True, slots=True)
class Host:
    """What the checks read, each on its own, as tests pass fakes: the gate's job and App
    check, the gate's own CLI, a section of watch_state.py's host rows, the checkout's branch
    against GitHub's after a fetch, the worktrees, and the gate's prune.json"""

    gate: Callable[[], Gate]
    gate_cli: Callable[[], GateCli | None]
    rows: Callable[[str], Sequence[Row]]
    main: Callable[[], Main]
    worktrees: Callable[[], Worktrees]
    prune: Callable[[], PruneRecord | None]


def host_command(repo: str, workspace: Path, section: str) -> list[str]:
    """watch_state.py's rows of one host section, reading nothing of the pipeline (S-044-5)"""
    script = skills_dir() / "github-ship-watch" / "scripts" / "watch_state.py"
    return [sys.executable, str(script), repo, "--repo-dir", str(workspace), "--host", section, "--json"]


@dataclass(frozen=True, slots=True)
class Section:
    """A host section's rows, and watch_state.py's exit code for them: 1 when one is an
    action row, else 0"""

    rows: list[Row]
    code: int


def read_section(repo: str, workspace: Path, section: str, run: StateRunner) -> Section:
    proc = run(host_command(repo, workspace, section))
    if state_failed(proc):
        said = proc.stderr.strip().splitlines()
        error = said[-1] if said else "no error printed"
        raise ReleaseError(f"watch_state.py --host {section} failed (exit {proc.returncode}): {error}")
    return Section(parse_rows(proc.stdout), proc.returncode)


def read_rows(repo: str, workspace: Path, section: str, run: StateRunner) -> list[Row]:
    return read_section(repo, workspace, section, run).rows


def stale_fix(main: Path, path: str, branch: str) -> str:
    """D-24: a person finishes or removes kept work; WORKTREE_STALE's fix, moved here"""
    where = shlex.quote(str(main / path))
    see = f"git -C {where} log origin/{branch}..HEAD"
    remove = f"git -C {shlex.quote(str(main))} worktree remove {where}"
    return f"see the work not landed: {see}; then push it and open a pull request, or remove it: {remove}"


def worktrees_check(found: Worktrees) -> Check:
    """S-044-7: the removable and kept worktrees counted, then a line per kept shipmill
    worktree created over 7 days ago, with why it is kept and its fix; those are the problem"""
    judged = found.judged
    removable = sum(1 for j in judged if j.verdict is Verdict.REMOVABLE)
    kept = sum(1 for j in judged if j.verdict is Verdict.KEPT)
    stale = [
        j
        for j in judged
        if j.verdict is Verdict.KEPT
        and j.reason not in NOT_SHIPMILL
        and j.age_hours is not None
        and dt.timedelta(hours=j.age_hours) > STALE
    ]
    details = tuple(
        Detail(
            "",
            f"{j.path}: {j.reason}; created {(j.age_hours or 0) // 24}d ago",
            stale_fix(found.main, j.path, found.branch),
        )
        for j in stale
    )
    return Check("worktrees", not stale, f"{removable} removable, {kept} kept", details=details)


def checks(repo: str, host: Host, cli: str, checkout: Path, now: dt.datetime, command: str) -> list[Check]:
    """S-044-6: every check in its order, each on its own (S-044-8); the gate and the App
    checks share the gate's read, so its failure is both checks' error"""
    gate: Gate | None = None
    error = ""
    try:
        gate = host.gate()
    except CHECK_FAILURES as exc:
        error = first_line(exc)

    def with_gate(check: str, build: Callable[[Gate], Check]) -> Check:
        if gate is None:
            return failed_check(check, error, command)
        found = gate
        return guarded(check, command, lambda: build(found))

    def shipmill() -> Check:
        rows = host.rows("shipmill")
        try:
            gate_cli, cli_error = host.gate_cli(), None
        except CHECK_FAILURES as exc:
            gate_cli, cli_error = None, first_line(exc)
        return shipmill_check(rows, cli, gate_cli, cli_error, repo, command)

    return [
        with_gate("gate", lambda g: gate_check(g, repo, now, command)),
        guarded("sessions", command, lambda: sessions_check(host.rows("sessions"), gate)),
        with_gate("github app", lambda g: github_app_check(g, repo, command)),
        guarded("shipmill", command, shipmill),
        guarded("checkout", command, lambda: checkout_check(host.main(), checkout)),
        guarded("worktrees", command, lambda: worktrees_check(host.worktrees())),
        guarded("prune", command, lambda: prune_check(host.prune(), command)),
    ]


def text(found: Sequence[Check]) -> str:
    return "".join(f"{line}\n" for c in found for line in c.lines())


def as_json(found: Sequence[Check]) -> str:
    """S-044-10: one object, the checks in the printed order"""
    return json.dumps({"checks": [c.record() for c in found]}, indent=2) + "\n"


def exit_code(found: Sequence[Check]) -> int:
    """S-044-9: 0 when every check passes, 1 when one finds a problem or fails to run"""
    return 0 if all(c.ok for c in found) else 1
