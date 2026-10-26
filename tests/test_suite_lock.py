"""The suite lock of the github-issue-triage skill: full test suites queue for a machine-wide slot"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "github-issue-triage" / "scripts" / "suite_lock.py"

# Writes "start" to a file, holds its slot a moment, then writes "end"
HOLD = (
    "import pathlib, sys, time; p = pathlib.Path(sys.argv[1]); "
    "p.write_text('start'); time.sleep(1.5); p.write_text('end')"
)
# Records what the holder's file said when this command started
PEEK = "import pathlib, sys; pathlib.Path(sys.argv[2]).write_text(pathlib.Path(sys.argv[1]).read_text())"


def lock(locks: Path, *args: str) -> list[str]:
    return [sys.executable, str(SCRIPT), "--dir", str(locks), *args]


def hold(locks: Path, marker: Path, *args: str) -> subprocess.Popen[str]:
    holder = subprocess.Popen(lock(locks, *args, "--", sys.executable, "-c", HOLD, str(marker)), text=True)
    deadline = time.monotonic() + 10
    while not marker.exists():
        assert time.monotonic() < deadline, "the holder never started"
        time.sleep(0.02)
    return holder


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
    locks, marker, seen = tmp_path / "locks", tmp_path / "marker", tmp_path / "seen"
    holder = hold(locks, marker)
    out = subprocess.run(
        lock(locks, "--", sys.executable, "-c", PEEK, str(marker), str(seen)), capture_output=True, text=True
    )
    assert holder.wait() == 0
    assert out.returncode == 0
    assert seen.read_text() == "end"
    assert "suite_lock: waiting for a free slot" in out.stderr
    assert "held by pid" in out.stderr


def test_two_slots_let_two_runs_overlap(tmp_path: Path) -> None:
    locks, marker, seen = tmp_path / "locks", tmp_path / "marker", tmp_path / "seen"
    holder = hold(locks, marker, "--slots", "2")
    out = subprocess.run(
        lock(locks, "--slots", "2", "--", sys.executable, "-c", PEEK, str(marker), str(seen)),
        capture_output=True,
        text=True,
    )
    assert holder.wait() == 0
    assert out.returncode == 0
    assert seen.read_text() == "start"
    assert out.stderr == ""


def test_a_killed_holder_frees_its_slot(tmp_path: Path) -> None:
    locks, marker = tmp_path / "locks", tmp_path / "marker"
    holder = hold(locks, marker)
    holder.kill()
    holder.wait()
    out = subprocess.run(lock(locks, "--", sys.executable, "-c", "pass"), capture_output=True, text=True, timeout=10)
    assert out.returncode == 0


def test_no_command_or_no_slot_is_a_usage_error(tmp_path: Path) -> None:
    for args in (["--"], [], ["--slots", "0", "--", "true"]):
        out = subprocess.run(lock(tmp_path, *args), capture_output=True, text=True)
        assert out.returncode == 2, args
