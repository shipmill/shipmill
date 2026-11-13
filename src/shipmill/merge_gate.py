"""Spec 055: the merge runs the gate (S-055-1 to S-055-3).

`shipmill gh pr merge <n>` and the merge API's `PUT repos/<o>/<r>/pulls/<n>/merge`, as the App,
run the `pr_gate.py` the wheel ships on pull request n before gh runs, and merge only the head
it read READY: an unpinned merge is pinned to it, a merge pinned elsewhere is refused. Any other
outcome, a gate that can't start or prints no verdict included, refuses the merge: it fails
closed. Every rule that decides whether a pull request may land is a verdict of pr_gate.py;
nothing here judges the pull request itself.
"""

import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from shipmill.app_gh import Merge, merge_pins, pinned
from shipmill.bundle import skills_dir
from shipmill.errors import ReleaseError

_GATE = ("github-pr-triage", "scripts", "pr_gate.py")
_READY = "READY"
_HEAD = re.compile(r"[0-9a-fA-F]{40}")

# the command and gh's env in, its exit code, stdout, and stderr out; OSError when it can't start
GateRun = Callable[[Sequence[str], Mapping[str, str]], subprocess.CompletedProcess[str]]


def run_gate(cmd: Sequence[str], env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), capture_output=True, text=True, env=dict(env), check=False)


def gate_command(number: int, repo: str, top: Path, bot: str) -> list[str]:
    """The wheel's pr_gate.py on pull request number of repo, reading the checkout top's default
    branch, with the App's bot login as the login agents write as"""
    script = skills_dir().joinpath(*_GATE)
    return [sys.executable, str(script), str(number), "-R", repo, "--checkout", str(top), "--bot-login", bot]


def _verdict(stdout: str, number: int) -> tuple[str, str, list[str]] | None:
    """pr_gate.py's verdict line for #number, its verdict, and the lines below it; None when it
    printed none"""
    lines = stdout.splitlines()
    for at, line in enumerate(lines):
        words = line.split()
        if len(words) >= 2 and words[0] == f"#{number}":
            reasons = [reason for reason in lines[at + 1 :] if reason.startswith("  ")]
            return line, words[1], reasons
    return None


def _head(line: str) -> str | None:
    """The full head SHA the verdict line names as head=<sha>; None without one"""
    for word in line.split():
        name, equals, value = word.partition("=")
        if name == "head" and equals and _HEAD.fullmatch(value):
            return value.lower()
    return None


def hold_gate(
    merge: Merge, number: int, repo: str, top: Path, bot: str, gh_args: list[str], env: Mapping[str, str], run: GateRun
) -> list[str]:
    """S-055-1 to S-055-3: gh's args for the merge once pr_gate.py, run with the App's env,
    reads pull request number READY at head H: pinned to H when they pin nothing, as given when
    they pin H. Raises, so gh never runs, for any other exit, a gate that can't start, one that
    prints no verdict line for number, a READY that names no full head, and a pin to another SHA"""
    pins = merge_pins(gh_args)  # before the gate: a pin that can't be read refuses the merge
    cmd = gate_command(number, repo, top, bot)
    refused = f"{merge.command} is refused"
    try:
        proc = run(cmd, env)
    except OSError as exc:
        raise ReleaseError(
            f"{refused}: pr_gate.py can't be started ({exc}), so the merge fails closed (spec 055)"
        ) from None
    found = _verdict(proc.stdout, number)
    if found is None:
        said = proc.stderr.strip() or proc.stdout.strip() or "nothing"
        raise ReleaseError(
            f"{refused}: pr_gate.py printed no verdict for #{number} (exit {proc.returncode}), so the merge fails "
            f"closed (spec 055); it said:\n{said}"
        )
    line, verdict, reasons = found
    shown = "\n".join([line, *reasons])
    if proc.returncode != 0 or verdict != _READY:
        raise ReleaseError(f"{refused}: pr_gate.py reads #{number} {verdict} (exit {proc.returncode})\n{shown}")
    head = _head(line)
    if head is None:
        raise ReleaseError(
            f"{refused}: pr_gate.py reads #{number} READY but names no full head SHA, so the head it judged can't "
            f"be pinned and the merge fails closed (spec 055)\n{shown}"
        )
    other = next((pin for pin in pins if pin.lower() != head), None)
    if other is not None:
        raise ReleaseError(
            f"{refused}: it pins #{number}'s head to {other}, and pr_gate.py reads #{number} READY at {head}: the "
            "head moved since it was read; read the pull request again, and merge the head the gate judged (spec 055)"
        )
    return gh_args if pins else pinned(gh_args, head)
