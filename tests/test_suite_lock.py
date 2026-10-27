"""The suite lock of the github-issue-triage skill: full test suites queue for a machine-wide slot"""

import importlib.util
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "github-issue-triage" / "scripts" / "suite_lock.py"

# Writes "start" to a file, holds its slot until the test creates the release file, then writes "end"
HOLD = (
    "import pathlib, sys, time; p, r = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]); "
    "p.write_text('start'); deadline = time.monotonic() + 60\n"
    "while not r.exists() and time.monotonic() < deadline: time.sleep(0.02)\n"
    "p.write_text('end')"
)
# Writes its own pid to a file, then holds its slot until the release file exists
KEEP = (
    "import os, pathlib, sys, time; r = pathlib.Path(sys.argv[2]); "
    "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); deadline = time.monotonic() + 60\n"
    "while not r.exists() and time.monotonic() < deadline: time.sleep(0.02)"
)
# Records what the holder's file said when this command started
PEEK = "import pathlib, sys; pathlib.Path(sys.argv[2]).write_text(pathlib.Path(sys.argv[1]).read_text())"
TOUCH = "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text('ran')"

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals and flock")


def lock(locks: Path, *args: str) -> list[str]:
    return [sys.executable, str(SCRIPT), "--dir", str(locks), *args]


def wait_for(done: Callable[[], object], what: str) -> None:
    deadline = time.monotonic() + 20
    while not done():
        assert time.monotonic() < deadline, what
        time.sleep(0.02)


def hold(
    locks: Path, marker: Path, release: Path, *args: str, start_new_session: bool = False
) -> subprocess.Popen[str]:
    holder = subprocess.Popen(
        lock(locks, *args, "--", sys.executable, "-c", HOLD, str(marker), str(release)),
        text=True,
        start_new_session=start_new_session,
    )
    wait_for(marker.exists, "the holder never started")
    return holder


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("suite_lock", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_command_runs_and_its_exit_code_is_returned(tmp_path: Path) -> None:
    out = subprocess.run(
        lock(tmp_path, "--", sys.executable, "-c", "print('ran'); raise SystemExit(3)"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 3
    assert out.stdout == "ran\n"


def test_a_second_run_waits_for_the_one_slot(tmp_path: Path) -> None:
    locks, marker, release, seen, err = (tmp_path / n for n in ("locks", "marker", "release", "seen", "err"))
    holder = hold(locks, marker, release)
    with err.open("w") as stderr:
        second = subprocess.Popen(lock(locks, "--", sys.executable, "-c", PEEK, str(marker), str(seen)), stderr=stderr)
    try:
        wait_for(lambda: "waiting for a free slot" in err.read_text(), "the second run never waited")
    finally:
        release.touch()
    assert holder.wait(timeout=20) == 0
    assert second.wait(timeout=20) == 0
    assert seen.read_text() == "end"
    # On Windows the holder's lock on byte 0 keeps the waiter from reading who holds it
    assert "held by pid" in err.read_text() or sys.platform == "win32"


def test_two_slots_let_two_runs_overlap(tmp_path: Path) -> None:
    locks, marker, release, seen = (tmp_path / n for n in ("locks", "marker", "release", "seen"))
    holder = hold(locks, marker, release, "--slots", "2")
    try:
        out = subprocess.run(
            lock(locks, "--slots", "2", "--", sys.executable, "-c", PEEK, str(marker), str(seen)),
            capture_output=True,
            text=True,
            timeout=20,
        )
    finally:
        release.touch()
    assert holder.wait(timeout=20) == 0
    assert out.returncode == 0
    assert seen.read_text() == "start"
    assert out.stderr == ""


@posix_only
def test_a_killed_run_frees_its_slot(tmp_path: Path) -> None:
    locks, marker, release = tmp_path / "locks", tmp_path / "marker", tmp_path / "release"
    holder = hold(locks, marker, release, start_new_session=True)
    os.killpg(holder.pid, signal.SIGKILL)
    holder.wait()
    out = subprocess.run(lock(locks, "--", sys.executable, "-c", "pass"), capture_output=True, text=True, timeout=10)
    assert out.returncode == 0


@posix_only
def test_a_killed_wrapper_keeps_the_slot_until_its_command_exits(tmp_path: Path) -> None:
    locks, pid_file, release, ran = (tmp_path / n for n in ("locks", "pid", "release", "ran"))
    wrapper = subprocess.Popen(lock(locks, "--", sys.executable, "-c", KEEP, str(pid_file), str(release)))
    wait_for(lambda: pid_file.exists() and pid_file.read_text(), "the command never started")
    child = int(pid_file.read_text())
    second = None
    try:
        wrapper.kill()
        wrapper.wait()
        second = subprocess.Popen(lock(locks, "--", sys.executable, "-c", TOUCH, str(ran)), stderr=subprocess.DEVNULL)
        time.sleep(2)
        assert not ran.exists(), "the second run started while the killed wrapper's command still ran"
        release.touch()
        assert second.wait(timeout=20) == 0
        assert ran.read_text() == "ran"
    finally:
        release.touch()
        if second is not None and second.poll() is None:
            second.kill()
            second.wait()
        wait_for(lambda: not alive(child), "the orphaned command never exited")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.skipif(sys.platform != "win32", reason="msvcrt byte locks exist only on Windows")
def test_windows_locks_the_same_byte_whoever_holds_the_slot(tmp_path: Path) -> None:
    locks, marker, release = tmp_path / "locks", tmp_path / "marker", tmp_path / "release"
    holder = hold(locks, marker, release)
    script = load_script()
    try:
        handle = open(locks / "slot-0.lock", "a+")  # noqa: SIM115 - closed below
        try:
            assert not script.try_lock(handle), "a second process locked the slot its holder holds"
            assert script.holder_of(handle) == ""
        finally:
            handle.close()
    finally:
        release.touch()
    assert holder.wait(timeout=20) == 0


def test_no_command_or_no_slot_is_a_usage_error(tmp_path: Path) -> None:
    for args in (["--"], [], ["--slots", "0", "--", "true"]):
        out = subprocess.run(lock(tmp_path, *args), capture_output=True, text=True)
        assert out.returncode == 2, args
