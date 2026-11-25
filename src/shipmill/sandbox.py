"""[agents.sandbox] (spec 087): what a repo declares a sandboxed headless session may reach
beyond the default, in .github/shipmill.toml (D-4), read from the default branch as every
[agents] key is (D-16).

- domains: extra hosts a session's commands may reach, each a host name or `*.` and a name,
  with no scheme, port, or path
- read: paths taken out of the deny list; write: extra paths a session may write. Each is
  absolute or starts `~/`, without `..`
- local_ports: a boolean; true opens every local port (allowLocalBinding), on macOS only until
  the Linux probe (S-087-29) is recorded
- tunnels: tables of exactly ssh (`[user@]host`, no options), local (1024 to 65535, unique
  across both tables), and remote (`host:port`); parsed and checked, they open nothing until a
  probe finds how a sandboxed command reaches a local port (D-105, #1589)

[agents.sandbox.grant] holds the same keys, opened only for a launch whose item a trusted
person granted that kind (spec 087, Per item); its read and write entries may not name, hold,
or lie inside a credential store or ~/.config/gh/hosts.yml.

A malformed key is refused as D-64 says: the config still loads, the key is dropped, so the
session runs with the narrower default, never a wider one, and doctor, the tick, and every
command that loads the config name it. A key shipmill never knew fails the load (D-63).

`launch` builds what a sandboxed headless launch (`shipmill gate --sandbox`) adds to its one
`--settings` JSON: the sandbox, the permission rules that make the file tools see what Bash
sees, and the env's uv cache and gh config folders (#1531)."""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath

from shipmill.config import Table
from shipmill.errors import ReleaseError
from shipmill.refused import Refusal

TABLE = "[agents.sandbox]"
GRANT_TABLE = "[agents.sandbox.grant]"
SPEC = "087"
DOMAINS = "domains"
READ = "read"
WRITE = "write"
LOCAL_PORTS = "local_ports"
TUNNELS = "tunnels"
GRANT = "grant"
KEYS = (DOMAINS, READ, WRITE, LOCAL_PORTS, TUNNELS)
MACOS = "darwin"  # the one platform whose local ports the probe recorded (#1588)
LINUX_PROBE = "local ports wait for the Linux probe (S-087-29)"
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
    LOCAL_PORTS: "local ports",
    TUNNELS: "each declared tunnel",
}
_WHAT = {
    DOMAINS: "a list of host names",
    READ: "a list of paths",
    WRITE: "a list of paths",
    LOCAL_PORTS: "a boolean",
}


def _fix(key: str, table: str) -> str:
    if key == DOMAINS:
        return "write each entry as a host name, or *. and a name, such as registry.npmjs.org"
    if key in (READ, WRITE):
        example = "~/.config/some-tool" if key == READ else "~/.cache/pnpm"
        outside = ", outside the credential stores and ~/.config/gh/hosts.yml" if table == GRANT_TABLE else ""
        return f"write each entry as an absolute path or one starting ~/, without ..{outside}, such as {example}"
    if key == LOCAL_PORTS:
        return f"write {LOCAL_PORTS} = true or {LOCAL_PORTS} = false"
    return (
        f'write each as [[{table[1:-1]}.{TUNNELS}]] with exactly ssh = "[user@]host", local = <1024..65535, '
        'each once across [agents.sandbox] and its grant> and remote = "host:port"'
    )


def _what(key: str, table: str) -> str:
    return _WHAT[key] if key in _WHAT else f"an array of tables, [[{table[1:-1]}.{TUNNELS}]]"


def refusal(key: str, why: str, table: str = TABLE) -> Refusal:
    """The refusal of a malformed [agents.sandbox] or [agents.sandbox.grant] key: dropped, so
    the session runs without it"""
    return Refusal(table, key, SPEC, _OFF[key], _fix(key, table), why=why)


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


def grant_refusal(value: object) -> Refusal:
    """The refusal of an [agents.sandbox] grant that isn't a table: no kind can be granted"""
    return Refusal(
        TABLE,
        GRANT,
        SPEC,
        "every sandbox grant",
        f"write {GRANT_TABLE} as a table of {', '.join(KEYS)}",
        why=f"must be a table, {GRANT_TABLE}, got {value!r}",
    )


def host_refusal(key: str, table: str, platform: str) -> Refusal:
    """S-087-26: local_ports or a tunnel on a gate whose host isn't macOS, dropped until the
    Linux probe records how a sandboxed command there reaches a local port (D-64)"""
    return Refusal(
        table,
        key,
        SPEC,
        _OFF[key],
        "a macOS gate opens it; on this host, leave it for the probe or delete it",
        why=f"is dropped on {platform}: {LINUX_PROBE}",
    )


type Paths = tuple[SandboxPath, ...]


class GrantKind(StrEnum):
    """A kind of resource a trusted person's `sandbox:<kind>` label grants one launch (spec 087,
    Per item); each opens the [agents.sandbox.grant] key of the same name"""

    DOMAINS = DOMAINS
    READ = READ
    WRITE = WRITE
    LOCAL_PORTS = "local-ports"
    TUNNELS = TUNNELS

    @property
    def label(self) -> str:
        return f"sandbox:{self.value}"


@dataclass(frozen=True, slots=True)
class SandboxConfig:
    """The [agents.sandbox] table, each key as declared; empty without the table, or with a key
    that was refused. grant is its [agents.sandbox.grant] table, read the same way, whose own
    grant is always None; None without the table"""

    domains: tuple[Domain, ...] = ()
    read: tuple[SandboxPath, ...] = ()
    write: tuple[SandboxPath, ...] = ()
    tunnels: tuple[Tunnel, ...] = ()
    local_ports: bool = False
    grant: SandboxConfig | None = None

    @classmethod
    def parse(cls, raw: object, where: str, home: Path | None = None) -> tuple[SandboxConfig, tuple[Refusal, ...]]:
        """The table, and the refusal of each malformed key, which is left out; where names the
        [agents] table for an unknown key, which fails the load (D-63). home, Path.home() when
        None, places the credential stores a grant's read or write entry may not reach"""
        if not isinstance(raw, dict):
            return cls(), (table_refusal(raw),)
        Table(raw, f"{where} [sandbox]").allow(*KEYS, GRANT)
        refusals: list[Refusal] = []
        found = cls._keys(raw, TABLE, refusals, _paths)
        if GRANT not in raw:
            return found, tuple(refusals)
        granted = raw[GRANT]
        if not isinstance(granted, dict):
            return found, (*refusals, grant_refusal(granted))
        Table(granted, f"{where} [sandbox.grant]").allow(*KEYS)
        grant = cls._keys(granted, GRANT_TABLE, refusals, _outside(Path.home() if home is None else home))
        repeated = sorted({int(t.local) for t in found.tunnels} & {int(t.local) for t in grant.tunnels})
        if repeated:  # the grant's tunnels go: the table every session runs with stays as declared
            why = f"is malformed: {LOCAL} {repeated[0]} is given in {TABLE} {TUNNELS} too"
            refusals.append(refusal(TUNNELS, why, GRANT_TABLE))
            grant = replace(grant, tunnels=())
        return replace(found, grant=grant), tuple(refusals)

    @classmethod
    def _keys(
        cls, raw: Mapping[str, object], table: str, refusals: list[Refusal], paths: Callable[[list[object]], Paths]
    ) -> SandboxConfig:
        return cls(
            domains=_key(raw, DOMAINS, _domains, refusals, table),
            read=_key(raw, READ, paths, refusals, table),
            write=_key(raw, WRITE, paths, refusals, table),
            tunnels=_key(raw, TUNNELS, _tunnels, refusals, table),
            local_ports=_flag(raw, LOCAL_PORTS, refusals, table),
        )

    def on_host(self, platform: str) -> tuple[SandboxConfig, tuple[Refusal, ...]]:
        """S-087-26: the table as a gate on platform opens it. Off macOS, local_ports and every
        tunnel, in either table, are dropped with a refusal each (D-64), until the Linux probe
        (S-087-29) records how a sandboxed command there reaches a local port"""
        if platform == MACOS:
            return self, ()
        refusals: list[Refusal] = []
        tables = ((self, TABLE), (self.grant, GRANT_TABLE))
        for table, name in tables:
            if table is not None and table.local_ports:
                refusals.append(host_refusal(LOCAL_PORTS, name, platform))
            if table is not None and table.tunnels:
                refusals.append(host_refusal(TUNNELS, name, platform))
        grant = None if self.grant is None else replace(self.grant, local_ports=False, tunnels=())
        return replace(self, local_ports=False, tunnels=(), grant=grant), tuple(refusals)

    def granting(self, kinds: Collection[GrantKind]) -> SandboxConfig:
        """What one launch opens: this table with the entries of each granted kind its grant
        declares added, and no grant left; a kind the grant doesn't declare adds nothing"""
        grant = self.grant if self.grant is not None else SandboxConfig()

        def given[T](kind: GrantKind, entries: tuple[T, ...]) -> tuple[T, ...]:
            return entries if kind in kinds else ()

        return SandboxConfig(
            domains=(*self.domains, *given(GrantKind.DOMAINS, grant.domains)),
            read=(*self.read, *given(GrantKind.READ, grant.read)),
            write=(*self.write, *given(GrantKind.WRITE, grant.write)),
            tunnels=(*self.tunnels, *given(GrantKind.TUNNELS, grant.tunnels)),
            local_ports=self.local_ports or (GrantKind.LOCAL_PORTS in kinds and grant.local_ports),
        )


def _flag(raw: Mapping[str, object], key: str, refusals: list[Refusal], table: str) -> bool:
    """A boolean key, false without it, and false with its refusal added when it isn't one"""
    value = raw.get(key, False)
    if isinstance(value, bool):
        return value
    refusals.append(refusal(key, f"must be {_WHAT[key]}, got {value!r}", table))
    return False


def _key[T](
    raw: Mapping[str, object],
    key: str,
    parse: Callable[[list[object]], tuple[T, ...]],
    refusals: list[Refusal],
    table: str,
) -> tuple[T, ...]:
    """The key's entries, or none with its refusal added when it is malformed; none without it"""
    if key not in raw:
        return ()
    value = raw[key]
    if not isinstance(value, list):
        refusals.append(refusal(key, f"must be {_what(key, table)}, got {value!r}", table))
        return ()
    try:
        return parse(value)
    except ReleaseError as exc:  # the first malformed entry, named; the whole key is dropped
        refusals.append(refusal(key, f"is malformed: {exc}", table))
        return ()


def _texts(value: list[object]) -> list[str]:
    for entry in value:
        if not isinstance(entry, str):
            raise ReleaseError(f"{entry!r} is not a string")
    return [entry for entry in value if isinstance(entry, str)]


def _domains(value: list[object]) -> tuple[Domain, ...]:
    return tuple(Domain(text) for text in _texts(value))


def _paths(value: list[object]) -> Paths:
    return tuple(SandboxPath(text) for text in _texts(value))


def _outside(home: Path) -> Callable[[list[object]], Paths]:
    """_paths for a grant: an entry that names, holds, or lies inside a credential store or
    ~/.config/gh/hosts.yml is malformed, since a key is full access, never a narrow grant. The
    home is taken as given and resolved, and names compare case-folded, as macOS's file system
    does, so another spelling of a store can't reach it"""
    homes = dict.fromkeys((home, home.resolve()))
    stores = [(PurePosixPath(HOME) / name, [h / name for h in homes]) for name in CREDENTIALS]

    def folded(path: PurePosixPath | Path) -> tuple[str, ...]:
        return tuple(part.casefold() for part in path.parts)

    def reaches(path: tuple[str, ...], store: tuple[str, ...]) -> bool:
        shorter = min(len(path), len(store))
        return path[:shorter] == store[:shorter]  # the same path, or one holds the other

    def parse(value: list[object]) -> Paths:
        paths = _paths(value)
        for path in paths:
            for named, places in stores:
                if any(reaches(folded(expand(path, h)), folded(p)) for h in homes for p in places):
                    raise ReleaseError(f"{str(path)!r} reaches {named}, a credential store a grant can't open")
        return paths

    return parse


def _tunnels(value: list[object]) -> tuple[Tunnel, ...]:
    tunnels = tuple(Tunnel.parse(entry) for entry in value)
    seen: set[int] = set()
    for tunnel in tunnels:
        port = int(tunnel.local)
        if port in seen:
            raise ReleaseError(f"{LOCAL} {port} is given twice")
        seen.add(port)
    return tunnels


# The launch (spec 087, #1531): the `sandbox` and `permissions` a sandboxed headless session's
# one `--settings` JSON carries beside its env. Every path is absolute and expanded; the
# listings of ~/.config/shipmill and ~/.claude/projects are read at each launch, never cached

# What a session can't read, under the home, whether or not each exists. The credential stores
# and the host's own GitHub login come first: a grant's read or write entry may reach none of them
CREDENTIALS = (
    ".ssh",
    ".gnupg",
    ".netrc",
    ".git-credentials",
    ".pypirc",
    ".npmrc",
    ".docker/config.json",
    ".kube",
    ".aws",
    ".azure",
    ".config/gcloud",
    ".password-store",
    "Library/Keychains",
    ".config/gh/hosts.yml",  # the host's own GitHub login; the session's gh reads GH_CONFIG_DIR (D-105)
)
DENIED = (
    *CREDENTIALS,
    ".claude.json",
    ".claude/.credentials.json",
    ".claude/history.jsonl",
)
SHIPMILL_CONFIG = ".config/shipmill"  # each entry denied but the App key the session writes with
PROJECTS = ".claude/projects"  # each folder denied but the session's own; ~/.claude/plugins stays readable
MEMORY = "memory"  # the session's own project memory, which its Edit and Write tools may reach
DEFAULT_DOMAINS = (
    "github.com",
    "*.github.com",
    "*.githubusercontent.com",
    "pypi.org",
    "files.pythonhosted.org",
    "astral.sh",
    "*.astral.sh",
)
UV_CACHE = ".cache/shipmill"  # <home>/.cache/shipmill/<owner>-<repo>/uv, outside the git dir (D-105)
GH_CONFIG = "gh-config"  # in the state dir, created empty before each launch (D-105)
TOKEN_CACHES = "app-token"  # the state dir's entries the session's helpers write start with it
SETTINGS_FILES = (".claude/settings.json", ".claude/settings.local.json", ".mcp.json")
FILE_TOOLS = ("Edit", "Write")  # narrowed to the write scope in a sandboxed launch (S-087-7)
UV_CACHE_DIR = "UV_CACHE_DIR"
GH_CONFIG_DIR = "GH_CONFIG_DIR"
_PLAIN = re.compile(r"[A-Za-z0-9._-]+")
_TOOL = re.compile(r"[A-Za-z]\w*(?:\([^)]*\))?")  # one entry of an allowlist: a name, or a name and its rule


@dataclass(frozen=True, slots=True)
class Where:
    """The host paths a sandboxed launch is built from, each absolute: the gate's checkout, its
    git common dir as git names it, the main working tree, and the gate's state dir"""

    home: Path
    checkout: Path
    common: Path
    main: Path
    state: Path
    repo: str

    def __post_init__(self) -> None:
        for name in ("home", "checkout", "common", "main", "state"):
            path = getattr(self, name)
            if not path.is_absolute():
                raise ReleaseError(f"the sandbox's {name} must be an absolute path, got {str(path)!r}")
        owner, slash, name = self.repo.partition("/")
        if not slash or not all(_PLAIN.fullmatch(p) and p not in (".", "..") for p in (owner, name)):
            raise ReleaseError(f"repo must be owner/name, got {self.repo!r}")

    @property
    def uv_cache(self) -> Path:
        owner, _, name = self.repo.partition("/")
        return self.home / UV_CACHE / f"{owner}-{name}" / "uv"

    @property
    def gh_config(self) -> Path:
        return self.state / GH_CONFIG

    @property
    def projects(self) -> tuple[str, ...]:
        """The session's own project folders under ~/.claude/projects: its checkout's, where its
        transcript goes, and its main working tree's, whose memory every worktree shares"""
        return tuple(dict.fromkeys(project_folder(p) for p in (self.checkout, self.main)))


def project_folder(path: Path) -> str:
    """The folder name Claude Code gives a working directory under ~/.claude/projects"""
    return re.sub(r"[^A-Za-z0-9-]", "-", str(path))


def expand(path: SandboxPath, home: Path) -> Path:
    """A declared path, absolute: `~/` is the home"""
    text = str(path)
    return home / text.removeprefix(HOME) if text.startswith(HOME) else Path(text)


def _listed(folder: Path) -> list[Path]:
    """The folder's entries, read now; none when it doesn't exist"""
    return sorted(folder.iterdir()) if folder.is_dir() else []


def denied_reads(where: Where, declared: SandboxConfig, app_key: Path | None) -> tuple[Path, ...]:
    """S-087-3, S-087-4: every path of "What a session can't read", existing or not, the
    entries of ~/.config/shipmill but the App key, and the folders of ~/.claude/projects but
    the session's own, less each path a declared read entry is or holds"""
    home = where.home
    key = None if app_key is None else app_key.resolve()
    found = [home / p for p in DENIED]
    found += [p for p in _listed(home / SHIPMILL_CONFIG) if key is None or p.resolve() != key]
    found += [p for p in _listed(home / PROJECTS) if p.name not in where.projects]
    allowed = [expand(p, home) for p in declared.read]
    return tuple(p for p in found if not any(p == a or a in p.parents for a in allowed))


def write_scope(where: Where, declared: SandboxConfig) -> tuple[Path, ...]:
    """S-087-5: the checkout, the main working tree's .claude/worktrees, the git common dir,
    the session's uv cache, and each declared write entry"""
    worktrees = where.main / ".claude" / "worktrees"
    return (where.checkout, worktrees, where.common, where.uv_cache, *(expand(p, where.home) for p in declared.write))


def editable(where: Where, declared: SandboxConfig) -> tuple[Path, ...]:
    """The folders a session's Edit and Write tools may reach (S-087-7): the write scope and
    the session's own project memory folders; read only, nothing is created"""
    memory = tuple(where.home / PROJECTS / name / MEMORY for name in where.projects)
    return (*write_scope(where, declared), *memory)


def denied_writes(where: Where, state_files: Sequence[str]) -> tuple[Path, ...]:
    """S-087-6: the common dir's config and hooks, the state dir's entries (those there now
    and the ones the gate writes, state_files) but the token caches and gh-config, and the
    settings files of the checkout and of the main working tree"""
    names = {p.name for p in _listed(where.state)} | set(state_files)
    kept = sorted(n for n in names if n != GH_CONFIG and not n.startswith(TOKEN_CACHES))
    trees = dict.fromkeys((where.checkout, where.main))
    return (
        where.common / "config",
        where.common / "hooks",
        *(where.state / n for n in kept),
        *(tree / f for tree in trees for f in SETTINGS_FILES),
    )


def _rule(tool: str, path: Path) -> str:
    """A permission rule on an absolute path, which Claude Code writes with a leading //"""
    return f"{tool}(/{path})"


@dataclass(frozen=True, slots=True)
class Sandbox:
    """What a sandboxed headless launch adds: its env's UV_CACHE_DIR and GH_CONFIG_DIR, the
    settings' sandbox and permissions, and the folders its Edit and Write tools may reach"""

    env: Mapping[str, str]
    settings: Mapping[str, object]
    editable: tuple[Path, ...]

    def tools(self, allowed: str) -> str:
        """allowed with each bare Edit and Write in it narrowed to one rule per editable
        folder, `Edit(//<path>/**)`; every other entry as it was (S-087-7)"""
        entries = _TOOL.findall(allowed)
        if " ".join(entries) != allowed:
            raise ReleaseError(f"the allowlist {allowed!r} is not space-separated tool entries")
        narrowed: list[str] = []
        for entry in entries:
            if entry in FILE_TOOLS:
                narrowed += [_rule(entry, p / "**") for p in self.editable]
            else:
                narrowed.append(entry)
        return " ".join(narrowed)


def launch(
    where: Where,
    declared: SandboxConfig,
    app_key: Path | None,
    state_files: Sequence[str],
    granted: Collection[GrantKind] = (),
    platform: str = sys.platform,
) -> Sandbox:
    """Spec 087's settings for one headless launch, read now: the listings it denies by path,
    and gh-config, created empty, and the uv cache, created, before the session starts.
    declared is [agents.sandbox] as origin's default branch has it; app_key, the path the
    session's SHIPMILL_APP_KEY names, None without an App; granted, the kinds of
    [agents.sandbox.grant] a trusted person granted this launch's item. local_ports opens
    every local port (allowLocalBinding) on a macOS gate only, and adds nothing to
    allowedDomains (S-087-26). No key, grant or platform opens a Unix socket or an unsandboxed
    command (S-087-27)"""
    declared = declared.granting(granted)
    deny = denied_reads(where, declared, app_key)
    scope = write_scope(where, declared)
    gh = where.gh_config  # what the last session's gh wrote there goes
    if gh.is_symlink() or gh.is_file():
        gh.unlink()
    elif gh.exists():
        shutil.rmtree(gh)
    gh.mkdir(parents=True)
    where.uv_cache.mkdir(parents=True, exist_ok=True)
    network: dict[str, object] = {"allowedDomains": [*DEFAULT_DOMAINS, *(str(d) for d in declared.domains)]}
    if declared.local_ports and platform == MACOS:
        network["allowLocalBinding"] = True
    sandbox = {
        "enabled": True,
        "allowUnsandboxedCommands": False,
        "failIfUnavailable": True,
        "filesystem": {
            "denyRead": [str(p) for p in deny],
            "allowWrite": [str(p) for p in scope],
            "denyWrite": [str(p) for p in denied_writes(where, state_files)],
        },
        "network": network,
    }
    rules = [_rule(tool, q) for p in deny for tool in ("Read", "Edit") for q in (p, p / "**")]
    return Sandbox(
        env={UV_CACHE_DIR: str(where.uv_cache), GH_CONFIG_DIR: str(where.gh_config)},
        settings={"sandbox": sandbox, "permissions": {"deny": rules}},
        editable=editable(where, declared),
    )


# Before a sandboxed launch (spec 087): what would widen the session's sandbox from outside its
# --settings (S-087-13), and whether a Linux host can confine at all (S-087-17). Either fails
# the tick, which then starts no session; doctor's sandbox row reads the same (S-087-18)

WIDENS = "which would widen a headless session's sandbox"
WIDENING_FIX = (
    "move it to a project's settings outside the gate's checkout, and declare what the gate's sessions need in "
    "[agents.sandbox] of .github/shipmill.toml"
)
ADDITIONAL_DIRECTORIES = "additionalDirectories"
_GLOB = re.compile(r"[*?\[{]")
_FILE_RULE = re.compile(r"(Edit|Write)\((.*)\)", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Widening:
    """A settings file Claude Code merges into a headless session's own, and the key in it that
    would widen the session's sandbox (S-087-13)"""

    file: Path
    key: str

    @property
    def message(self) -> str:
        return f"{self.file} sets {self.key}, {WIDENS}"

    def error(self) -> ReleaseError:
        return ReleaseError(self.message, WIDENING_FIX)


def settings_files(checkout: Path, home: Path) -> tuple[Path, ...]:
    """The settings files whose keys merge into a session started in checkout: the checkout's
    .claude/settings.json and .claude/settings.local.json, and the user's ~/.claude/settings.json"""
    return (
        checkout / ".claude" / "settings.json",
        checkout / ".claude" / "settings.local.json",
        home / ".claude" / "settings.json",
    )


def widening(checkout: Path, home: Path, scope: Sequence[Path]) -> Widening | None:
    """S-087-13: the first key of settings_files that would widen a session whose Edit and
    Write tools may reach scope: a `sandbox` key, `permissions.additionalDirectories`, or a
    `permissions.allow` entry for Edit or Write that is bare or reaches beyond scope. None
    when no file holds one; a file that doesn't parse as a JSON object fails, as the gate
    can't tell what it would merge"""
    for path in settings_files(checkout, home):
        if not path.is_file():
            continue
        try:
            found = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ReleaseError(
                f"{path} doesn't parse as JSON ({exc}), so the gate can't tell whether it would widen a headless"
                " session's sandbox",
                "fix the file, or move it out of the way",
            ) from None
        if not isinstance(found, dict):
            raise ReleaseError(
                f"{path} holds no JSON object, so the gate can't tell what it would merge", "fix the file"
            )
        key = _widening_key(found, path, checkout, home, scope)
        if key is not None:
            return Widening(path, key)
    return None


def _widening_key(
    found: Mapping[str, object], path: Path, checkout: Path, home: Path, scope: Sequence[Path]
) -> str | None:
    if "sandbox" in found:
        return "sandbox"
    permissions = found.get("permissions")
    if permissions is None:
        return None
    if not isinstance(permissions, dict):
        return "permissions"  # Claude Code's reading of it can't be told, so it counts
    if ADDITIONAL_DIRECTORIES in permissions:
        return f"permissions.{ADDITIONAL_DIRECTORIES}"
    allowed = permissions.get("allow", [])
    if not isinstance(allowed, list):
        return "permissions.allow"
    project = path.parent.parent  # .claude/settings.json's project, the home for ~/.claude/settings.json
    for entry in allowed:
        if not isinstance(entry, str):
            return "permissions.allow"
        if entry in FILE_TOOLS:
            return f'permissions.allow "{entry}"'
        rule = _FILE_RULE.fullmatch(entry)
        if rule is not None and not _inside(rule[2], (project, path.parent), checkout, home, scope):
            return f'permissions.allow "{entry}"'
    return None


def _inside(pattern: str, bases: Sequence[Path], checkout: Path, home: Path, scope: Sequence[Path]) -> bool:
    """Whether every file a rule's gitignore-style pattern can match lies in scope: `//p` is
    absolute, `~/p` under the home, `/p` relative to the settings file (read both as its
    project and as its folder, so either reading must stay in scope), and anything else
    relative to the session's working directory, the checkout. The part before the first
    glob character is the folder it reaches; an empty pattern reaches everything"""
    if not pattern:
        return False
    if pattern.startswith("//"):
        roots = [Path(pattern[1:])]
    elif pattern.startswith("~/"):
        roots = [home / pattern[2:]]
    elif pattern.startswith("/"):
        roots = [base / pattern[1:] for base in bases]
    else:
        roots = [checkout / pattern]
    return all(_within(_fixed(root), scope) for root in roots)


def _fixed(path: Path) -> Path:
    """The folder a pattern reaches: its parts up to the first one holding a glob character,
    with `..` folded"""
    parts: list[str] = []
    for part in path.parts:
        if _GLOB.search(part):
            break
        parts.append(part)
    return Path(os.path.normpath(Path(*parts))) if parts else Path("/")


def _within(path: Path, scope: Sequence[Path]) -> bool:
    return any(path == folder or folder in path.parents for folder in scope)


@dataclass(frozen=True, slots=True)
class Unconfined:
    """S-087-17: what keeps Claude Code's sandbox from starting on this host, and its fix"""

    failed: str
    fix: str

    @property
    def message(self) -> str:
        return f"the sandbox can't start on this host: {self.failed}"

    def error(self) -> ReleaseError:
        return ReleaseError(self.message, self.fix)


BWRAP_PROBE = ("bwrap", "--ro-bind", "/", "/", "--unshare-user", "true")
PACKAGES = "install bubblewrap and socat (apt install bubblewrap socat, or dnf install bubblewrap socat)"
USERNS_FIX = (
    "let unprivileged users create user namespaces: sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0, "
    "and the same line in /etc/sysctl.d to keep it"
)
type Probe = Callable[[Sequence[str]], tuple[int, str]]  # a command -> its exit code and stderr


def _probe(cmd: Sequence[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(list(cmd), capture_output=True, text=True, timeout=30, check=False)
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, f"{shlex.join(cmd)} didn't finish within 30 seconds"
    return done.returncode, done.stderr


def confinement(
    platform: str = sys.platform, run: Probe = _probe, which: Callable[[str], str | None] = shutil.which
) -> Unconfined | None:
    """S-087-17: on Linux, whether bubblewrap can make a user namespace (`bwrap --ro-bind / /
    --unshare-user true`) and socat is on PATH, which Claude Code's sandbox needs; None when
    both hold, or on any other platform. A user-namespace refusal's fix is the sysctl"""
    if not platform.startswith("linux"):
        return None
    failed: list[str] = []
    fixes: list[str] = []
    if which(BWRAP_PROBE[0]) is None:
        failed.append("bwrap is not on PATH")
        fixes.append(PACKAGES)
    else:
        code, err = run(BWRAP_PROBE)
        if code != 0:
            last = next((line.strip() for line in reversed(err.splitlines()) if line.strip()), "no output")
            failed.append(f"`{shlex.join(BWRAP_PROBE)}` exited {code}: {last}")
            fixes.append(USERNS_FIX if "namespace" in err.lower() or "uid map" in err.lower() else PACKAGES)
    if which("socat") is None:
        failed.append("socat is not on PATH")
        if PACKAGES not in fixes:
            fixes.append(PACKAGES)
    return Unconfined("; ".join(failed), "; ".join(fixes)) if failed else None
