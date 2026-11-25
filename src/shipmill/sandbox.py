"""[agents.sandbox] (spec 087): what a repo declares a sandboxed headless session may reach
beyond the default, in .github/shipmill.toml (D-4), read from the default branch as every
[agents] key is (D-16).

- domains: extra hosts a session's commands may reach, each a host name or `*.` and a name,
  with no scheme, port, or path
- read: paths taken out of the deny list; write: extra paths a session may write. Each is
  absolute or starts `~/`, without `..`
- tunnels: tables of exactly ssh (`[user@]host`, no options), local (1024 to 65535, unique),
  and remote (`host:port`); parsed and checked, they open nothing until a probe finds how a
  sandboxed command reaches a local port (D-105, #1589)

A malformed key is refused as D-64 says: the config still loads, the key is dropped, so the
session runs with the narrower default, never a wider one, and doctor, the tick, and every
command that loads the config name it. A key shipmill never knew fails the load (D-63)."""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from shipmill.config import Table
from shipmill.errors import ReleaseError
from shipmill.refused import Refusal

TABLE = "[agents.sandbox]"
SPEC = "087"
DOMAINS = "domains"
READ = "read"
WRITE = "write"
TUNNELS = "tunnels"
KEYS = (DOMAINS, READ, WRITE, TUNNELS)
SSH = "ssh"
LOCAL = "local"
REMOTE = "remote"
TUNNEL_KEYS = (SSH, LOCAL, REMOTE)
WILDCARD = "*."
HOME = "~/"
LOCAL_LOW = 1024  # below it a port is privileged
PORT_HIGH = 65535

_LABEL = r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
_HOST = re.compile(rf"{_LABEL}(?:\.{_LABEL})*")
_HOST_MAX = 253
_USER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")  # never starts with '-', so ssh can't read it as an option
_PORT = re.compile(r"[0-9]{1,5}")


def _host(text: str) -> bool:
    return len(text) <= _HOST_MAX and _HOST.fullmatch(text) is not None


@dataclass(frozen=True, slots=True)
class Domain:
    """A host a session's commands may reach: a name, such as registry.npmjs.org, or `*.` and
    a name, such as *.npmjs.org"""

    value: str

    def __post_init__(self) -> None:
        text = self.value
        if not text:
            raise ReleaseError("'' is empty")
        if "://" in text:
            raise ReleaseError(f"{text!r} has a scheme")
        if "/" in text:
            raise ReleaseError(f"{text!r} has a path")
        if ":" in text:
            raise ReleaseError(f"{text!r} has a port")
        if not _host(text.removeprefix(WILDCARD)):
            raise ReleaseError(f"{text!r} is not a host name")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SandboxPath:
    """A path of the host as the config writes it: absolute, or under the home as `~/...`,
    without `..`"""

    value: str

    def __post_init__(self) -> None:
        text = self.value
        if not text:
            raise ReleaseError("'' is empty")
        if not text.startswith(("/", HOME)):
            raise ReleaseError(f"{text!r} is relative")
        if ".." in PurePosixPath(text).parts:
            raise ReleaseError(f"{text!r} holds ..")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SshDestination:
    """Where a tunnel's ssh connects: `[user@]host`, which the host's own ssh config resolves;
    no option, port, or command"""

    value: str

    def __post_init__(self) -> None:
        user, at, host = self.value.rpartition("@")
        if (at and _USER.fullmatch(user) is None) or not _host(host):
            raise ReleaseError(f"{SSH} {self.value!r} is not [user@]host")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class LocalPort:
    """The port on 127.0.0.1 a session reaches a tunnel at: 1024 to 65535"""

    value: int

    def __post_init__(self) -> None:
        port = self.value
        if not isinstance(port, int) or isinstance(port, bool) or not LOCAL_LOW <= port <= PORT_HIGH:
            raise ReleaseError(f"{LOCAL} {port!r} is not a port from {LOCAL_LOW} to {PORT_HIGH}")

    def __int__(self) -> int:
        return self.value


@dataclass(frozen=True, slots=True)
class RemoteAddress:
    """What a tunnel forwards to, on the far side: `host:port`"""

    value: str

    def __post_init__(self) -> None:
        host, colon, port = self.value.rpartition(":")
        if not colon or not _host(host) or _PORT.fullmatch(port) is None or not 1 <= int(port) <= PORT_HIGH:
            raise ReleaseError(f"{REMOTE} {self.value!r} is not host:port")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Tunnel:
    """A port the gate opens before the session starts (spec 087, #1589)"""

    ssh: SshDestination
    local: LocalPort
    remote: RemoteAddress

    @classmethod
    def parse(cls, raw: object) -> Tunnel:
        if not isinstance(raw, Mapping):
            raise ReleaseError(f"{raw!r} is not a table of {', '.join(TUNNEL_KEYS)}")
        missing = [k for k in TUNNEL_KEYS if k not in raw]
        if missing:
            raise ReleaseError(f"a tunnel lacks {', '.join(missing)}")
        extra = sorted(str(k) for k in raw if k not in TUNNEL_KEYS)
        if extra:
            raise ReleaseError(f"a tunnel sets {', '.join(extra)}, beyond {', '.join(TUNNEL_KEYS)}")
        ssh, remote = raw[SSH], raw[REMOTE]
        if not isinstance(ssh, str):
            raise ReleaseError(f"{SSH} {ssh!r} is not [user@]host")
        if not isinstance(remote, str):
            raise ReleaseError(f"{REMOTE} {remote!r} is not host:port")
        return cls(SshDestination(ssh), LocalPort(raw[LOCAL]), RemoteAddress(remote))


_OFF = {
    DOMAINS: "each declared domain",
    READ: "each declared read exception",
    WRITE: "each declared write path",
    TUNNELS: "each declared tunnel",
}
_FIX = {
    DOMAINS: "write each entry as a host name, or *. and a name, such as registry.npmjs.org",
    READ: "write each entry as an absolute path or one starting ~/, without .., such as ~/.config/some-tool",
    WRITE: "write each entry as an absolute path or one starting ~/, without .., such as ~/.cache/pnpm",
    TUNNELS: (
        'write each as [[agents.sandbox.tunnels]] with exactly ssh = "[user@]host", local = <1024..65535, '
        'each once> and remote = "host:port"'
    ),
}
_WHAT = {
    DOMAINS: "a list of host names",
    READ: "a list of paths",
    WRITE: "a list of paths",
    TUNNELS: "an array of tables, [[agents.sandbox.tunnels]]",
}


def refusal(key: str, why: str) -> Refusal:
    """The refusal of a malformed [agents.sandbox] key: dropped, so the session runs without it"""
    return Refusal(TABLE, key, SPEC, _OFF[key], _FIX[key], why=why)


def table_refusal(value: object) -> Refusal:
    """The refusal of an [agents] sandbox that isn't a table: every exception is dropped"""
    return Refusal(
        "[agents]",
        "sandbox",
        SPEC,
        f"each {TABLE} exception",
        f"write {TABLE} as a table of {', '.join(KEYS)}",
        why=f"must be a table, {TABLE}, got {value!r}",
    )


@dataclass(frozen=True, slots=True)
class SandboxConfig:
    """The [agents.sandbox] table, each key as declared; empty without the table, or with a key
    that was refused"""

    domains: tuple[Domain, ...] = ()
    read: tuple[SandboxPath, ...] = ()
    write: tuple[SandboxPath, ...] = ()
    tunnels: tuple[Tunnel, ...] = ()

    @classmethod
    def parse(cls, raw: object, where: str) -> tuple[SandboxConfig, tuple[Refusal, ...]]:
        """The table, and the refusal of each malformed key, which is left out; where names the
        [agents] table for an unknown key, which fails the load (D-63)"""
        if not isinstance(raw, dict):
            return cls(), (table_refusal(raw),)
        Table(raw, f"{where} [sandbox]").allow(*KEYS)
        refusals: list[Refusal] = []
        found = cls(
            domains=_key(raw, DOMAINS, _domains, refusals),
            read=_key(raw, READ, _paths, refusals),
            write=_key(raw, WRITE, _paths, refusals),
            tunnels=_key(raw, TUNNELS, _tunnels, refusals),
        )
        return found, tuple(refusals)


def _key[T](
    raw: Mapping[str, object], key: str, parse: Callable[[list[object]], tuple[T, ...]], refusals: list[Refusal]
) -> tuple[T, ...]:
    """The key's entries, or none with its refusal added when it is malformed; none without it"""
    if key not in raw:
        return ()
    value = raw[key]
    if not isinstance(value, list):
        refusals.append(refusal(key, f"must be {_WHAT[key]}, got {value!r}"))
        return ()
    try:
        return parse(value)
    except ReleaseError as exc:  # the first malformed entry, named; the whole key is dropped
        refusals.append(refusal(key, f"is malformed: {exc}"))
        return ()


def _texts(value: list[object]) -> list[str]:
    for entry in value:
        if not isinstance(entry, str):
            raise ReleaseError(f"{entry!r} is not a string")
    return [entry for entry in value if isinstance(entry, str)]


def _domains(value: list[object]) -> tuple[Domain, ...]:
    return tuple(Domain(text) for text in _texts(value))


def _paths(value: list[object]) -> tuple[SandboxPath, ...]:
    return tuple(SandboxPath(text) for text in _texts(value))


def _tunnels(value: list[object]) -> tuple[Tunnel, ...]:
    tunnels = tuple(Tunnel.parse(entry) for entry in value)
    seen: set[int] = set()
    for tunnel in tunnels:
        port = int(tunnel.local)
        if port in seen:
            raise ReleaseError(f"{LOCAL} {port} is given twice")
        seen.add(port)
    return tunnels
