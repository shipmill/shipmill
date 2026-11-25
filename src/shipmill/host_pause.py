"""Spec 095: the host's pause, beside the credential's (spec 089). A headless session that ended
ok in its result but whose failed tool calls read GitHub's rate limit (`github_limit`) or a full
disk (`disk`) writes a record for the host, `$XDG_STATE_HOME/shipmill/host/<cause>.json`; every
gate on the host reads both records before it launches and, while one holds, starts no session.
A `github_limit` pause lifts once `gh api rate_limit` shows room in `core` and `graphql`, else at
the reset it recorded, or GitHub's hour after the end without one; a `disk` pause once the file
system holding the gate's checkout has DISK_FLOOR free (D-112)"""

import datetime as dt
import json
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from shipmill.claude_pause import pauses_dir
from shipmill.walk import End, malformed, moment, write

CAUSES = (End.GITHUB_LIMIT, End.DISK)
KEYS = frozenset({"cause", "session", "at", "resets_at", "lifted"})
DISK_FLOOR = 2 * 1024**3  # bytes free on the checkout's file system a disk pause lifts at (S-095-6)
GITHUB_WINDOW = dt.timedelta(hours=1)  # GitHub's rate limit window: a limit with no reset read lifts after it
RESOURCES = ("core", "graphql")  # the budgets `gh` spends that a gate's sessions read through
RATE_LIMIT = ("api", "rate_limit")  # `gh api rate_limit`, which spends no request of the budget


def host_dir(environ: Mapping[str, str], home: Path) -> Path:
    """`$XDG_STATE_HOME/shipmill/host`, beside spec 089's `claude` folder"""
    return pauses_dir(environ, home).parent / "host"


@dataclass(frozen=True, slots=True)
class HostPause:
    """The host's pause for one cause: the session whose end wrote it, when it ended, for a
    github_limit the reset gh api rate_limit read then (None when no budget was spent), and when
    it lifted, None while it holds. A lifted pause stays on disk, so the same session's end, which
    gate.json keeps naming until the next launch, never writes it again"""

    cause: End
    session: str
    at: dt.datetime
    resets_at: dt.datetime | None = None
    lifted: dt.datetime | None = None

    def __post_init__(self) -> None:
        if self.cause not in CAUSES:
            raise ValueError(f"a host pause's cause is github_limit or disk, got {self.cause!r}")
        if self.resets_at is not None and self.cause is not End.GITHUB_LIMIT:
            raise ValueError("only a github_limit pause has resets_at")
        if not self.session:
            raise ValueError("a host pause names the session whose end wrote it")

    @property
    def holds(self) -> bool:
        return self.lifted is None

    def record(self) -> dict[str, object]:
        found: dict[str, object] = {"cause": self.cause.value, "session": self.session, "at": self.at.isoformat()}
        if self.resets_at is not None:
            found["resets_at"] = self.resets_at.isoformat()
        if self.lifted is not None:
            found["lifted"] = self.lifted.isoformat()
        return found

    def lifts_at(self) -> dt.datetime:
        """When a github_limit pause lifts by the clock, the probe unread: its reset, else GitHub's
        hour after the end (S-095-5)"""
        return self.resets_at if self.resets_at is not None else self.at + GITHUB_WINDOW

    def lifting(self, at: dt.datetime) -> HostPause:
        return replace(self, lifted=at)


def pause_path(folder: Path, cause: End) -> Path:
    if cause not in CAUSES:
        raise ValueError(f"a host pause's cause is github_limit or disk, got {cause!r}")
    return folder / f"{cause.value}.json"


def load_host_pause(folder: Path, cause: End) -> HostPause | None:
    """The host's pause for cause, lifted or not, None without one; a file shipmill doesn't write
    is refused"""
    path = pause_path(folder, cause)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not {"cause", "session", "at"} <= set(data) <= KEYS:
            raise ValueError("expected cause, session, at, and resets_at and lifted or not")
        if data["cause"] != cause.value:
            raise ValueError(f"cause must be {cause.value}, got {data['cause']!r}")
        if not isinstance(data["session"], str):
            raise ValueError("session must be a string")
        resets = moment(data["resets_at"], "resets_at") if "resets_at" in data else None
        lifted = moment(data["lifted"], "lifted") if "lifted" in data else None
        return HostPause(cause, data["session"], moment(data["at"], "at"), resets, lifted)
    except ValueError as exc:
        raise malformed(path, exc) from None


def save_host_pause(folder: Path, pause: HostPause) -> None:
    write(pause_path(folder, pause.cause), pause.record())


@dataclass(frozen=True, slots=True)
class Rate:
    """`gh api rate_limit` as a github_limit pause reads it: room, every resource of RESOURCES
    has some remaining; resets, the latest reset of those with none remaining, None when none is
    spent"""

    room: bool
    resets: dt.datetime | None


RateProbe = Callable[[], Rate | None]  # None: the probe failed or its output can't be read
FreeSpace = Callable[[Path], int]  # the bytes free on the file system holding a folder


def rate_of(text: str) -> Rate | None:
    """`gh api rate_limit`'s JSON read for RESOURCES' `remaining` and `reset` (epoch seconds);
    None when it isn't that shape"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    resources = data.get("resources") if isinstance(data, dict) else None
    if not isinstance(resources, dict):
        return None
    spent: list[dt.datetime] = []
    for name in RESOURCES:
        found = resources.get(name)
        if not isinstance(found, dict):
            return None
        remaining, reset = found.get("remaining"), found.get("reset")
        if not isinstance(remaining, int) or isinstance(remaining, bool):
            return None
        if not isinstance(reset, int) or isinstance(reset, bool):
            return None
        if remaining <= 0:
            spent.append(dt.datetime.fromtimestamp(reset, tz=dt.UTC))
    return Rate(not spent, max(spent, default=None))


def rate_probe(environ: Mapping[str, str], program: str | None) -> RateProbe:
    """Spec 095 (S-095-5): `gh api rate_limit` as the host's gh login, which the sessions read
    with; None when gh is missing, doesn't answer in 60 s, exits non-zero, or prints no rate"""

    def probe() -> Rate | None:
        if program is None:
            return None
        try:
            proc = subprocess.run(
                [program, *RATE_LIMIT],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
                env=dict(environ),
                check=False,
            )
        except FileNotFoundError, subprocess.TimeoutExpired:
            return None
        return rate_of(proc.stdout) if proc.returncode == 0 else None

    return probe


def free_space(folder: Path) -> int:
    return shutil.disk_usage(folder).free


@dataclass(frozen=True, slots=True)
class HostSeams:
    """What the host's pause reads: its folder, the rate probe, and the free space reader"""

    folder: Path
    rate: RateProbe
    free: FreeSpace = free_space


def gib(size: int) -> str:
    return f"{size / 1024**3:.1f} GiB"


def noted_host(
    seams: HostSeams, cause: End | None, session: str | None, ended: dt.datetime, dry_run: bool
) -> HostPause | None:
    """Spec 095 (S-095-3): the last headless session ended github_limit or disk, so the host
    pauses: the cause, the session, when it ended, and for github_limit the reset the rate probe
    reads now. Written once per session, as spec 089's credential pause is: while gate.json keeps
    naming it, a later tick finds the record, lifted or not, and writes nothing; a pause of the
    cause that holds is kept. A dry run writes nothing and returns the pause it would write. None
    when nothing is written"""
    if cause not in CAUSES or session is None:
        return None
    found = load_host_pause(seams.folder, cause)
    if found is not None and (found.session == session or found.holds):
        return None
    resets = None
    if cause is End.GITHUB_LIMIT:
        rate = seams.rate()
        resets = None if rate is None else rate.resets
    pause = HostPause(cause, session, ended, resets)
    if not dry_run:
        save_host_pause(seams.folder, pause)
    return pause


@dataclass(frozen=True, slots=True)
class HostHeld:
    """A host pause that holds on this tick: the PAUSED reason, and the fix a person can act on"""

    reason: str
    fix: str | None = None


def host_paused(
    seams: HostSeams, noted: HostPause | None, checkout: Path, now: dt.datetime, dry_run: bool
) -> HostHeld | None:
    """Spec 095 (S-095-4 to S-095-6): a tick of any gate on the host reads both host pauses
    before it launches. A github_limit pause lifts on the first tick the rate probe shows room,
    else, the probe unread, at its reset or GitHub's hour after the end; a disk pause on the
    first tick the checkout's file system has DISK_FLOOR free. A lifted pause is kept, marked
    lifted (a dry run marks nothing). noted is the pause this tick wrote, which a dry run didn't.
    The first that still holds is the tick's PAUSED; None when none holds"""
    for cause in CAUSES:
        found = noted if noted is not None and noted.cause is cause else load_host_pause(seams.folder, cause)
        if found is None or not found.holds:
            continue
        held = still_held(seams, found, checkout, now)
        if held is None:
            if not dry_run:
                save_host_pause(seams.folder, found.lifting(now))
            continue
        return held
    return None


def still_held(seams: HostSeams, found: HostPause, checkout: Path, now: dt.datetime) -> HostHeld | None:
    if found.cause is End.GITHUB_LIMIT:
        rate = seams.rate()
        if (rate is not None and rate.room) or (rate is None and now >= found.lifts_at()):
            return None
        until = "gh api rate_limit shows room" if rate is not None else found.lifts_at().isoformat(timespec="minutes")
        return HostHeld(
            f"github_limit: GitHub's rate limit stopped session {found.session}; no session starts until {until}"
        )
    free = seams.free(checkout)
    if free >= DISK_FLOOR:
        return None
    fix = f"free space on the file system holding {checkout}: the gate launches again at {gib(DISK_FLOOR)} free"
    reason = (
        f"disk: no space left on device stopped session {found.session}; no session starts until {checkout} "
        f"has {gib(DISK_FLOOR)} free, it has {gib(free)}; fix: {fix}"
    )
    return HostHeld(reason, fix)
