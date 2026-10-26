"""The long-lived Claude token a gate's sessions authenticate with (spec 035).

`claude setup-token` prints a token for a Claude subscription. Saved to a file only the gate's
user can read, `~/.config/shipmill/claude-token` unless `--claude-token` names another, it goes
into the environment of each session the gate starts as CLAUDE_CODE_OAUTH_TOKEN, never into a
command line, a plist, a log, or the repo. Without the file the gate uses the interactive
login; a file that is there but wrong is refused (TokenRefused), never a fallback (D-14).

The checks run in order, the file's mode before its bytes are read, so a file others can read
is refused without its content ever entering the gate's memory. No message names a byte of
the file: each names the path and the rule that failed.
"""

import datetime as dt
import enum
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from shipmill.errors import ReleaseError

FLAG = "--claude-token"
DEFAULT = Path(".config") / "shipmill" / "claude-token"  # under the user's home, next to the App's key
SETUP = "claude setup-token"
PREFIX = "sk-ant-oat"  # what `claude setup-token` prints; an API key starts sk-ant-api
API_KEY = "sk-ant-api"
OAUTH = "CLAUDE_CODE_OAUTH_TOKEN"
SCRUB = "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"  # Claude Code strips its credentials from its tools' env
# Claude Code ranks both above CLAUDE_CODE_OAUTH_TOKEN, so a session with a token goes without them
OUTRANKING = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
MAX_AGE = dt.timedelta(days=330)  # a setup-token token lasts a year; doctor warns before it ends
# the fixes the gate writes after "; fix: " for a token, which status and the watch pass on:
# REJECTED_SHAPE a token's authentication failure (the preflight's, a dead session's), and
# FIX_SHAPE every CLAUDE_AUTH fix a token file brings
REJECTED_SHAPE = r"the token in (?P<path>.+) was not accepted; run claude setup-token and save it to (?P=path)"
REJECTED = re.compile(REJECTED_SHAPE)
FIX_SHAPE = re.compile(
    rf"(?:{REJECTED_SHAPE}|run claude setup-token and save the token to .+|chmod 600 .+"
    r"|chown \d+ .+, or save a new token there with claude setup-token|create .+, or drop --claude-token)"
)


class Kind(enum.StrEnum):
    TOKEN_FILE = "token-file"
    LOGIN = "login"


def setup_fix(path: Path) -> str:
    """The fix for a file that holds no usable token"""
    return f"run claude setup-token and save the token to {path}"


def rejected_fix(path: Path) -> str:
    """The fix for a token Claude Code didn't accept: the preflight's and a dead session's"""
    return f"the token in {path} was not accepted; run claude setup-token and save it to {path}"


@dataclass(frozen=True, slots=True)
class TokenSource:
    """Where the gate looks: named when --claude-token gave the path, so a missing file is an
    error rather than the login"""

    path: Path
    named: bool = False

    @classmethod
    def of(cls, given: Path | None, home: Path) -> TokenSource:
        """--claude-token's path, made absolute, else the default under home"""
        if given is None:
            return cls(home / DEFAULT)
        return cls(given.expanduser().resolve(), named=True)

    @classmethod
    def of_job(cls, args: Sequence[str] | None, home: Path) -> TokenSource:
        """The gate's source as its launchd job's arguments name it; the default without a job"""
        if args is not None and FLAG in args[:-1]:
            return cls(Path(args[args.index(FLAG) + 1]), named=True)
        return cls(home / DEFAULT)


@dataclass(frozen=True, slots=True)
class Token:
    """A token read from its file; value never shows in a repr, a message, or a record"""

    path: Path
    value: str = field(repr=False)
    written: dt.datetime  # the file's last write, for doctor's age warning

    def env(self, environ: Mapping[str, str]) -> dict[str, str]:
        """A session's process env: the gate's own without the keys that outrank the token,
        with the token and the scrub that keeps it from the session's tools"""
        kept = {k: v for k, v in environ.items() if k not in OUTRANKING}
        return {**kept, OAUTH: self.value, SCRUB: "1"}


def session_env(environ: Mapping[str, str], token: Token | None) -> dict[str, str]:
    """The env a session start, or the preflight, runs in: the gate's own, unchanged without a
    token (S-035-1)"""
    return dict(environ) if token is None else token.env(environ)


class TokenRefused(ReleaseError):
    """A token file the gate refuses: the reason names the path and the rule, never its bytes"""

    def __init__(self, path: Path, reason: str, fix: str) -> None:
        super().__init__(f"{reason}; fix: {fix}")
        self.path = path
        self.reason = reason
        self.fix = fix


class TokenFs(Protocol):
    def stat(self, path: Path) -> os.stat_result: ...
    def read(self, path: Path) -> bytes: ...


class HostFs:
    def stat(self, path: Path) -> os.stat_result:
        return os.stat(path)

    def read(self, path: Path) -> bytes:
        return path.read_bytes()


HOST = HostFs()


def read_token(source: TokenSource, fs: TokenFs = HOST, uid: int | None = None) -> Token | None:
    """The token, None when the default file isn't there (the login), or TokenRefused. The
    checks run in spec 035's order; the file is opened only once its kind, owner, and mode
    passed. uid is the gate's user, os.getuid() when None"""
    path = source.path
    try:
        found = fs.stat(path)
    except FileNotFoundError:
        if source.named:
            raise TokenRefused(
                path, f"{path}, named by {FLAG}, doesn't exist", f"create {path}, or drop {FLAG}"
            ) from None
        return None
    except OSError as exc:
        raise TokenRefused(path, f"{path} can't be read ({exc.strerror})", setup_fix(path)) from None
    if not stat.S_ISREG(found.st_mode):
        raise TokenRefused(path, f"{path} is not a regular file", setup_fix(path))
    user = os.getuid() if uid is None else uid
    if found.st_uid != user:
        reason = f"{path} is owned by uid {found.st_uid}, not the gate's user (uid {user})"
        raise TokenRefused(path, reason, f"chown {user} {path}, or save a new token there with {SETUP}")
    if found.st_mode & 0o077:
        mode = stat.S_IMODE(found.st_mode)
        raise TokenRefused(path, f"{path} has mode {mode:03o}, which group or others can read", f"chmod 600 {path}")
    written = dt.datetime.fromtimestamp(found.st_mtime, tz=dt.UTC)
    return Token(path, checked(path, fs.read(path)), written)


def checked(path: Path, data: bytes) -> str:
    """The token in data with one trailing newline stripped, or TokenRefused naming the rule"""
    if not data.strip():
        raise TokenRefused(path, f"{path} is empty", setup_fix(path))
    if any(b > 0x7E or (b < 0x20 and b not in b"\t\n\r") for b in data):
        raise TokenRefused(path, f"{path} holds a non-ASCII or control byte", setup_fix(path))
    text = data.decode("ascii")
    if len([line for line in text.splitlines() if line.strip()]) > 1:
        raise TokenRefused(path, f"{path} holds more than one non-empty line", setup_fix(path))
    value = text.removesuffix("\n")
    if any(c.isspace() for c in value):
        raise TokenRefused(path, f"{path} has whitespace in the token", setup_fix(path))
    if not value.startswith(PREFIX):
        # never the key's own prefix: the message holds no 8 bytes of the file (S-035-7)
        api = "; it holds an API key, which goes nowhere here" if value.startswith(API_KEY) else ""
        raise TokenRefused(path, f"{path} doesn't start with {PREFIX}", f"{setup_fix(path)}{api}")
    return value


@dataclass(frozen=True, slots=True)
class Credential:
    """What the gate authenticates its sessions with: a token, the login, or a refused file"""

    source: TokenSource
    token: Token | None
    refused: TokenRefused | None = None

    @property
    def kind(self) -> Kind:
        return Kind.LOGIN if self.token is None and self.refused is None else Kind.TOKEN_FILE


def inspect(source: TokenSource, fs: TokenFs = HOST, uid: int | None = None) -> Credential:
    """read_token's answer, a refusal kept rather than raised, for the gate, status, and doctor"""
    try:
        return Credential(source, read_token(source, fs, uid))
    except TokenRefused as refused:
        return Credential(source, None, refused)


def shown(path: Path, home: Path) -> str:
    """A path as status prints it: ~/... under home"""
    return f"~/{path.relative_to(home)}" if path.is_relative_to(home) else str(path)
