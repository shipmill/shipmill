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
command that loads the config name it. A key shipmill never knew fails the load (D-63).

`launch` builds what a sandboxed headless launch (`shipmill gate --sandbox`) adds to its one
`--settings` JSON: the sandbox, the permission rules that make the file tools see what Bash
sees, and the env's uv cache and gh config folders (#1531). `violations` reads the text the
sandbox writes when it refuses a host, for the tick and the check of [agents] verify (#1535)."""

import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from shipmill.config import CONFIG_PATH, Table
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


# The launch (spec 087, #1531): the `sandbox` and `permissions` a sandboxed headless session's
# one `--settings` JSON carries beside its env. Every path is absolute and expanded; the
# listings of ~/.config/shipmill and ~/.claude/projects are read at each launch, never cached

# What a session can't read, under the home, whether or not each exists
DENIED = (
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
    settings' sandbox and permissions, and the folders its Edit and Write tools may reach.
    rules is its filesystem and network rules as the sandbox runtime (`srt --settings`) reads
    them, for the check of [agents] verify (S-087-16); pinned, the same rules without the
    folders of ~/.claude/projects, which every new worktree adds to, for that check's
    fingerprint"""

    env: Mapping[str, str]
    settings: Mapping[str, object]
    editable: tuple[Path, ...]
    rules: Mapping[str, object] = field(default_factory=dict)
    pinned: Mapping[str, object] = field(default_factory=dict)

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


def launch(where: Where, declared: SandboxConfig, app_key: Path | None, state_files: Sequence[str]) -> Sandbox:
    """Spec 087's settings for one headless launch, read now: the listings it denies by path,
    and gh-config, created empty, and the uv cache, created, before the session starts.
    declared is [agents.sandbox] as origin's default branch has it; app_key, the path the
    session's SHIPMILL_APP_KEY names, None without an App"""
    deny = denied_reads(where, declared, app_key)
    scope = write_scope(where, declared)
    gh = where.gh_config  # what the last session's gh wrote there goes
    if gh.is_symlink() or gh.is_file():
        gh.unlink()
    elif gh.exists():
        shutil.rmtree(gh)
    gh.mkdir(parents=True)
    where.uv_cache.mkdir(parents=True, exist_ok=True)
    filesystem = {
        "denyRead": [str(p) for p in deny],
        "allowWrite": [str(p) for p in scope],
        "denyWrite": [str(p) for p in denied_writes(where, state_files)],
    }
    domains = [*DEFAULT_DOMAINS, *(str(d) for d in declared.domains)]
    sandbox = {
        "enabled": True,
        "allowUnsandboxedCommands": False,
        "failIfUnavailable": True,
        "filesystem": filesystem,
        "network": {"allowedDomains": domains},
    }
    rules = [_rule(tool, q) for p in deny for tool in ("Read", "Edit") for q in (p, p / "**")]
    memory = tuple(where.home / PROJECTS / name / MEMORY for name in where.projects)
    network = {"allowedDomains": domains, "deniedDomains": []}
    projects = where.home / PROJECTS
    steady = [str(p) for p in deny if p.parent != projects]
    return Sandbox(
        env={UV_CACHE_DIR: str(where.uv_cache), GH_CONFIG_DIR: str(where.gh_config)},
        settings={"sandbox": sandbox, "permissions": {"deny": rules}},
        editable=(*scope, *memory),
        rules={"filesystem": filesystem, "network": network},
        pinned={"filesystem": filesystem | {"denyRead": steady}, "network": network},
    )


# What the sandbox says when it refuses (#1524, #1588, docs/design/agent-modes.md): a refused
# host leaves a <sandbox_violations> block of `deny <operation> <target> (<why>)` lines in the
# tool result, and the proxy's own answer reads BLOCKED. A refused path leaves only the
# program's own error (EPERM on macOS; ENOENT or EROFS on Linux), with no block
VIOLATIONS = "<sandbox_violations>"
BLOCKED = "Connection blocked by network allowlist"
_BLOCK = re.compile(rf"{VIOLATIONS}[ \t]*\r?\n((?:[ \t]*deny [^\n]*(?:\n|$))+)")
_DENY = re.compile(r"[ \t]*deny (?P<operation>[\w*-]+) (?P<target>\S+)(?: \([^)]*\))?[ \t]*\r?")
_SAID = {DOMAINS: "a connection to", READ: "reading", WRITE: "writing"}
_REFUSED = "the sandbox refused "  # the start of a refused command's detail in the verify check


@dataclass(frozen=True, slots=True)
class Violation:
    """One `deny <operation> <target>` line of a <sandbox_violations> block"""

    operation: str  # such as network-outbound, file-read-data, file-write-create
    target: str  # host:port for a connection, a path for a file

    @property
    def key(self) -> str | None:
        """The [agents.sandbox] key that would allow it; None for an operation no key opens"""
        if self.operation.startswith("network"):
            return DOMAINS
        if self.operation.startswith("file-read"):
            return READ
        if self.operation.startswith("file-write"):
            return WRITE
        return None

    @property
    def named(self) -> str:
        """The host without its port, for a connection; the path, for a file"""
        if self.key != DOMAINS:
            return self.target
        host, colon, port = self.target.rpartition(":")
        return host if colon and port.isdigit() else self.target

    @property
    def said(self) -> str:
        """What it refused, as a detail says it: `a connection to example.com`"""
        key = self.key
        return f"{self.operation} {self.target}" if key is None else f"{_SAID[key]} {self.named}"

    def fix(self) -> str:
        return entry_fix(self.key, self.named)


def entry_fix(key: str | None, named: str) -> str:
    """S-087-14, S-087-16: the [agents.sandbox] entry that allows what the sandbox refused,
    reviewed as any widening is; never an allowlist change or a --claude-arg"""
    where = f"in {CONFIG_PATH.as_posix()}, in a pull request the maintainer approves"
    if key is None:
        return f"declare what it needs in {TABLE} {where}"
    return f'add "{named}" to {TABLE} {key} {where}'


def violations(text: str) -> tuple[Violation, ...]:
    """Each `deny` line of each <sandbox_violations> block in text, in order; none in a text
    that only quotes the tag, as a document about it does"""
    found: list[Violation] = []
    for block in _BLOCK.finditer(text):
        for line in block.group(1).splitlines():
            if (m := _DENY.fullmatch(line)) is not None:
                found.append(Violation(m["operation"], m["target"]))
    return tuple(found)


def refused_detail(text: str) -> str | None:
    """The verify check's detail for a command whose output says the sandbox refused it
    (S-087-16): the first violation, naming the host or path, else the proxy's refusal; None
    when the output says neither"""
    found = violations(text)
    if found:
        return f"{_REFUSED}{found[0].said}"
    if BLOCKED in text:
        return f"the sandbox's proxy refused a host outside the allowed domains: {BLOCKED}"
    return None


def detail_fix(detail: str) -> str:
    """The fix for a refused_detail: the [agents.sandbox] entry its host or path needs"""
    said = detail.removeprefix(_REFUSED)
    for key, verb in _SAID.items():
        if detail.startswith(_REFUSED) and said.startswith(f"{verb} "):
            return entry_fix(key, said.removeprefix(f"{verb} "))
    return entry_fix(DOMAINS if BLOCKED in detail else None, "<host>")
