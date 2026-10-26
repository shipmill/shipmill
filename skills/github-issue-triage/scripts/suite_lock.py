#!/usr/bin/env python3
"""Run a command, such as a repo's full test suite, once a machine-wide slot is free.

Parallel agents that each run a full suite at once starve each other of CPU: on one
machine, ten suites of five minutes each took ten minutes and hit the agents' tool
timeout. Wrapping the full suite in this script queues them, so each runs at full speed.

    suite_lock.py [--slots N] [--dir DIR] -- <command> [args...]

Exits with the command's exit code, or 2 on bad usage. A slot is a lock file under DIR
(default `$XDG_CACHE_HOME/shipmill/suite-locks`, else `~/.cache/shipmill/suite-locks`),
shared by every repo and worktree of the user; the lock goes with the process, so a
killed run never leaves a slot taken.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import IO

if sys.platform == "win32":
    import msvcrt

    def try_lock(handle: IO[str]) -> bool:
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

else:
    import fcntl

    def try_lock(handle: IO[str]) -> bool:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


POLL_SECONDS = 1.0


def default_dir() -> Path:
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "shipmill" / "suite-locks"


def acquire(directory: Path, slots: int) -> IO[str]:
    """The open handle of the first free slot, waiting until one frees up"""
    directory.mkdir(parents=True, exist_ok=True)
    waiting = False
    while True:
        holders = []
        for slot in range(slots):
            handle = open(directory / f"slot-{slot}.lock", "a+")  # noqa: SIM115 - held until exit
            if try_lock(handle):
                handle.seek(0)
                handle.truncate()
                handle.write(f"pid {os.getpid()} in {os.getcwd()}\n")
                handle.flush()
                return handle
            handle.seek(0)
            holders.append(handle.read().strip() or "another process")
            handle.close()
        if not waiting:
            held = "; ".join(holders)
            print(f"suite_lock: waiting for a free slot of {slots} in {directory}, held by {held}", file=sys.stderr)
            waiting = True
        time.sleep(POLL_SECONDS)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--slots", type=int, default=1, help="how many commands may run at once (default 1)")
    parser.add_argument("--dir", type=Path, default=None, help="the folder of lock files")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="the command, after --")
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("give the command after --")
    if args.slots < 1:
        parser.error("--slots must be at least 1")
    handle = acquire(args.dir or default_dir(), args.slots)
    try:
        return subprocess.run(command, check=False).returncode
    finally:
        handle.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
