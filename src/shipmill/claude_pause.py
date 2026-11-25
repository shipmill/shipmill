"""Spec 089: a credential's pause, shared by every gate on the host. A headless session that
ended on a usage limit (`limit`) or a refused credential (`auth`) writes a record for the
credential it ran with, `$XDG_STATE_HOME/shipmill/claude/<credential>.json`; every gate reads
the record for its own credential before it launches and, while it holds, starts no session.
`<credential>` names the credential without holding it: the first 16 hex digits of the SHA-256
of the token file's content (spec 035), or `login` for a gate with no token file (D-100)"""

import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from shipmill.claude_token import Token
from shipmill.errors import ReleaseError
from shipmill.walk import End, malformed, moment, write

LOGIN = "login"  # the credential of a gate with no token file: the host's Claude Code login
CAUSES = (End.LIMIT, End.AUTH)
KEYS = frozenset({"cause", "session", "at", "resets_at", "notified", "lifted"})
NAMED = re.compile(r"login|[0-9a-f]{16}")  # what credential_id returns, and so a pause file's name


def credential_id(token: Token | None) -> str:
    """The credential a gate's sessions run with, as its pause is named: `login` without a
    token file, else the first 16 hex digits of the SHA-256 of the file's content, read again
    here, so replacing the file's content names another credential (S-089-5, S-089-9)"""
    if token is None:
        return LOGIN
    return hashlib.sha256(token.path.read_bytes()).hexdigest()[:16]


def pauses_dir(environ: Mapping[str, str], home: Path) -> Path:
    """`$XDG_STATE_HOME/shipmill/claude`, `~/.local/state` when XDG_STATE_HOME is unset or empty;
    a relative one is refused, as the XDG spec says"""
    base = environ.get("XDG_STATE_HOME", "")
    folder = Path(base) if base else home / ".local" / "state"
    if not folder.is_absolute():
        raise ReleaseError(
            f"XDG_STATE_HOME must be an absolute path, got {base!r}", "unset XDG_STATE_HOME, or make it absolute"
        )
    return folder / "shipmill" / "claude"


@dataclass(frozen=True, slots=True)
class Pause:
    """A credential's pause: why (limit or auth), the session whose end wrote it, when, for a
    limit the newest resetsAt its log carried (None when it carried none), when its one
    notification went out (an auth pause's, S-089-10), None before, and when it lifted, None
    while it holds. A lifted pause stays on disk, so the same session's end, which gate.json
    keeps naming until the next launch, never writes it again"""

    cause: End
    session: str
    at: dt.datetime
    resets_at: dt.datetime | None = None
    notified: dt.datetime | None = None
    lifted: dt.datetime | None = None

    @property
    def holds(self) -> bool:
        return self.lifted is None

    def __post_init__(self) -> None:
        if self.cause not in CAUSES:
            raise ValueError(f"a pause's cause is limit or auth, got {self.cause!r}")
        if self.resets_at is not None and self.cause is not End.LIMIT:
            raise ValueError("only a limit pause has resets_at")
        if not self.session:
            raise ValueError("a pause names the session whose end wrote it")

    def record(self) -> dict[str, object]:
        found: dict[str, object] = {"cause": self.cause.value, "session": self.session, "at": self.at.isoformat()}
        if self.resets_at is not None:
            found["resets_at"] = self.resets_at.isoformat()
        if self.notified is not None:
            found["notified"] = self.notified.isoformat()
        if self.lifted is not None:
            found["lifted"] = self.lifted.isoformat()
        return found

    def lifts_at(self, retry: dt.timedelta) -> dt.datetime | None:
        """When a limit pause lifts by the clock: its resetsAt, else retry_hours after it was
        written (S-089-8); an auth pause lifts on no clock (S-089-9)"""
        if self.cause is not End.LIMIT:
            return None
        return self.resets_at if self.resets_at is not None else self.at + retry

    def until(self, credential: str, retry: dt.timedelta) -> str:
        """When it ends, as PAUSED and the watch name it"""
        lifts = self.lifts_at(retry)
        if lifts is not None:
            return lifts.isoformat(timespec="minutes")
        return "claude auth status reports a login" if credential == LOGIN else "the token changes"

    def noticed(self, at: dt.datetime) -> Pause:
        return replace(self, notified=at)

    def lifting(self, at: dt.datetime) -> Pause:
        return replace(self, lifted=at)


def pause_path(folder: Path, credential: str) -> Path:
    if NAMED.fullmatch(credential) is None:
        raise ValueError(f"a credential is login or 16 hex digits, got {credential!r}")
    return folder / f"{credential}.json"


def load_pause(folder: Path, credential: str) -> Pause | None:
    """The credential's pause record, lifted or not, None without one; a file shipmill doesn't
    write is refused"""
    path = pause_path(folder, credential)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not {"cause", "session", "at"} <= set(data) <= KEYS:
            raise ValueError("expected cause, session, at, and resets_at, notified, and lifted or not")
        if not isinstance(data["session"], str):
            raise ValueError("session must be a string")
        if data["cause"] not in {c.value for c in CAUSES}:
            raise ValueError(f"cause must be limit or auth, got {data['cause']!r}")
        resets = moment(data["resets_at"], "resets_at") if "resets_at" in data else None
        notified = moment(data["notified"], "notified") if "notified" in data else None
        lifted = moment(data["lifted"], "lifted") if "lifted" in data else None
        return Pause(End(data["cause"]), data["session"], moment(data["at"], "at"), resets, notified, lifted)
    except ValueError as exc:
        raise malformed(path, exc) from None


def save_pause(folder: Path, credential: str, pause: Pause) -> None:
    write(pause_path(folder, credential), pause.record())


def newest_reset(events: list[Mapping[str, object]]) -> dt.datetime | None:
    """The newest `resetsAt` a session's `rate_limit_event`s carry, epoch seconds in their
    rate_limit_info, as a time: of the rejected ones, the limit that stopped it, when it has
    any, so an allowed warning about a later window doesn't stretch the pause; else of every
    one. None when none carries one"""
    rejected: list[dt.datetime] = []
    every: list[dt.datetime] = []
    for event in events:
        info = event.get("rate_limit_info")
        if event.get("type") != "rate_limit_event" or not isinstance(info, dict) or "resetsAt" not in info:
            continue
        resets = info["resetsAt"]
        if isinstance(resets, bool) or not isinstance(resets, int | float):
            raise ValueError(f"a rate_limit_event's resetsAt must be a number, got {resets!r}")
        at = dt.datetime.fromtimestamp(resets, tz=dt.UTC)
        every.append(at)
        if info.get("status") == "rejected":
            rejected.append(at)
    return max(rejected or every, default=None)
