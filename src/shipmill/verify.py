"""Spec 064: check that a repo's verification commands, [agents] verify, work from a headless
gate session, where and as such a session would run them.

The check adds a worktree detached at origin/<default> under <checkout>/.claude/worktrees, the
folder implementers' worktrees use, and removes it when the check ends, however it ends (D-24).
Each command goes through three steps in the list's order, and the first that fails names its
result; a command that fails step 1 or 2 is not run:

1. The allowlist: each of its parts (its simple commands, as the delivery hook splits them, and
   those inside its `$(...)` and backtick substitutions) matches an allow rule and no deny rule
   of a headless session: HEADLESS_TOOLS, the gate's --claude-arg tool flags, and the settings
   files' permissions, as Claude Code matches a Bash rule, past the wrappers it strips; a deny
   rule wins, and a substitution that can't be read is denied
2. The delivery hook a gate session loads judges each part, with SHIPMILL_GATE=1 (D-82), in the
   directory a `cd` before it set
3. The run: `$SHELL -c` in the worktree, in a headless session's environment, for at most 30
   minutes; exit 127 names the program the PATH lacks
"""

import hashlib
import importlib.util
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import ModuleType
from typing import Protocol

from shipmill.errors import ReleaseError
from shipmill.hooks import SETTINGS, HookRunner, pre_command, run_hook

TIMEOUT = 30 * 60.0  # seconds a command may run before the check stops it
POLL = 0.05  # seconds between looks at whether a command exited
TAIL = 64 * 1024  # bytes of a command's stderr kept, its end, which holds the line a result names
WORKTREES = Path(".claude") / "worktrees"  # where Claude Code's worktrees for implementers live
PREFIX = "shipmill-verify-"  # the check's worktree is PREFIX and 8 hex digits
ALLOW_FLAGS = ("--allowedTools", "--allowed-tools")
DENY_FLAGS = ("--disallowedTools", "--disallowed-tools")
NOT_FOUND = 127  # the shell's exit when it can't find a command's program
# the shell's own commands, which no PATH holds and exit 127 never names
BUILTINS = frozenset({".", ":", "[", "cd", "echo", "eval", "exec", "exit", "export", "set", "source", "test", "unset"})
_RULE = re.compile(r"[^\s,()]+(?:\([^)]*\))?")  # one rule of a tool list: a name, with its (specifier) if any
_REFUSAL = re.compile(r"^shipmill hook (?P<rule>[A-Za-z0-9_-]+): ")  # the hook's first stderr line

Git = Callable[[list[str], Path], str]  # (command, cwd) -> its stdout; ReleaseError when it fails


class Result(StrEnum):
    """What the check found of one command (spec 064)"""

    OK = "ok"
    DENIED = "denied"  # step 1: no allow rule matches a part, or a deny rule does
    REFUSED = "refused by hook"  # step 2: the delivery hook exits 2 on a part
    NOT_FOUND = "not found"  # step 3: exit 127
    FAILED = "failed"  # step 3: another nonzero exit
    TIMED_OUT = "timed out"  # step 3: stopped past the limit


@dataclass(frozen=True, slots=True)
class Entry:
    """One command's result and its detail"""

    command: str
    result: Result
    detail: str


@dataclass(frozen=True, slots=True)
class Part:
    """One simple command of a command line: its text, its program as written, its text past
    any leading NAME=value assignments, which a deny rule matches too, and the directory a `cd`
    in an earlier part of its line set (None: the line's own)"""

    text: str
    program: str
    bare: str
    cwd: Path | None = None

    def unwrapped(self) -> tuple[str, str]:
        """Its text and its bare text past the wrappers Claude Code strips (WRAPPERS); both as
        they are when shlex can't split them"""
        try:
            words, bare = shlex.split(self.text), shlex.split(self.bare)
        except ValueError:
            return self.text, self.bare
        assignments = words[: len(words) - len(bare)]
        inner = unwrap(bare)
        return shlex.join((*assignments, *inner)), shlex.join(inner)

    def programs(self) -> list[str]:
        """Its program, and the one its wrappers wrap when it has any"""
        try:
            inner = unwrap(shlex.split(self.bare))
        except ValueError:
            return [self.program]
        return [self.program] if not inner or inner[0] == self.program else [self.program, inner[0]]


# --- Step 1: the allowlist ----------------------------------------------------------------------


def _quote_end(command: str, i: int) -> int:
    """The index of the `'` closing the one at i; ValueError when none does"""
    end = command.find("'", i + 1)
    if end < 0:
        raise ValueError("an unclosed '")
    return end


def _tick_end(command: str, i: int) -> int:
    """The index of the backtick closing a substitution whose body starts at i"""
    while i < len(command):
        if command[i] == "\\":
            i += 2
            continue
        if command[i] == "`":
            return i
        i += 1
    raise ValueError("an unclosed `")


def _paren_end(command: str, i: int) -> int:
    """The index of the `)` closing a `$(` whose body starts at i, past the quotes, parentheses,
    and substitutions it holds"""
    depth, quoted = 1, False
    while i < len(command):
        ch = command[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "'" and not quoted:
            i = _quote_end(command, i) + 1
            continue
        if command.startswith("$(", i):
            i = _paren_end(command, i + 2) + 1
            continue
        if ch == "`":
            i = _tick_end(command, i + 1) + 1
            continue
        if ch == '"':
            quoted = not quoted
        elif ch == "(" and not quoted:
            depth += 1
        elif ch == ")" and not quoted:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("an unclosed $(")


def substitutions(command: str) -> list[str]:
    """The commands of the `$(...)` and backtick substitutions in a command line, outermost
    first, inside double quotes too and never inside single quotes; an arithmetic `$((...))`
    gives the substitutions it holds. ValueError when a quote or a substitution isn't closed"""
    found: list[str] = []
    i, quoted = 0, False
    while i < len(command):
        ch = command[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "'" and not quoted:
            i = _quote_end(command, i) + 1
            continue
        if command.startswith("$(", i):
            end = _paren_end(command, i + 2)
            body = command[i + 2 : end]
            if body.startswith("(") and body.endswith(")"):
                found += substitutions(body[1:-1])
            else:
                found.append(body)
            i = end + 1
            continue
        if ch == "`":
            end = _tick_end(command, i + 1)
            found.append(re.sub(r"\\([\\`$])", r"\1", command[i + 1 : end]))
            i = end + 1
            continue
        if ch == '"':
            quoted = not quoted
        i += 1
    if quoted:
        raise ValueError('an unclosed "')
    return found


# The wrappers Claude Code strips from a command before it matches a Bash rule, each with its
# options that take the next word as their value
WRAPPERS: Mapping[str, frozenset[str]] = {
    "timeout": frozenset({"-k", "--kill-after", "-s", "--signal"}),
    "nohup": frozenset(),
    "nice": frozenset({"-n", "--adjustment"}),
    "command": frozenset(),
    "xargs": frozenset(
        {"-a", "--arg-file", "-d", "--delimiter", "-E", "-I", "-L", "-n", "--max-args", "-P", "--max-procs", "-s"}
        | {"--max-chars", "--process-slot-var"}
    ),
}


def unwrap(words: Sequence[str]) -> list[str]:
    """The words past the wrappers that lead them, with each wrapper's options and timeout's
    duration; the words as they are when a wrapper wraps no command"""
    rest = list(words)
    while rest and os.path.basename(rest[0]) in WRAPPERS:
        name = os.path.basename(rest[0])
        i = 1
        while i < len(rest) and rest[i].startswith("-") and rest[i] != "-":
            if rest[i] == "--":
                i += 1
                break
            i += 2 if rest[i] in WRAPPERS[name] else 1
        if name == "timeout":
            i += 1  # its duration
        if i >= len(rest):
            return rest
        rest = rest[i:]
    return rest


def rules(text: str) -> tuple[str, ...]:
    """The rules of a tool list as --allowedTools takes it: names and Name(specifier) entries,
    apart by spaces or commas"""
    return tuple(m.group(0) for m in _RULE.finditer(text))


def flag_rules(args: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The allow and deny rules of the gate's --claude-arg flags: the values after
    --allowedTools or --allowed-tools (and --disallowedTools, --disallowed-tools), up to the next
    flag, or the value after `=`"""
    allow: list[str] = []
    deny: list[str] = []
    into: list[str] | None = None
    for arg in args:
        if not arg.startswith("-"):
            if into is not None:
                into.extend(rules(arg))
            continue
        flag, eq, value = arg.partition("=")
        into = allow if flag in ALLOW_FLAGS else deny if flag in DENY_FLAGS else None
        if eq and into is not None:
            into.extend(rules(value))
            into = None
    return tuple(allow), tuple(deny)


def permissions(path: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """A settings file's permissions.allow and permissions.deny; () each when it doesn't exist.
    A file that isn't a JSON object, or a list that isn't strings, exits 2 naming it"""
    if not path.is_file():
        return (), ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ReleaseError(f"{path} is not JSON ({exc}), so its permissions can't be read") from None
    if not isinstance(data, dict):
        raise ReleaseError(f"{path} is not a JSON object, so its permissions can't be read")
    perms = data.get("permissions", {})
    if not isinstance(perms, dict):
        raise ReleaseError(f"{path}: permissions is not an object")
    found: list[tuple[str, ...]] = []
    for key in ("allow", "deny"):
        value = perms.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ReleaseError(f"{path}: permissions.{key} is not a list of strings")
        found.append(tuple(value))
    return found[0], found[1]


def matches(rule: str, part: str) -> bool:
    """Whether a rule matches a part as Claude Code documents it: `Bash` and `Bash(*)` any part;
    `Bash(<prefix>:*)`, and `Bash(<prefix> *)` when that `*` is its only one, the prefix alone
    or followed by a space; `Bash(<pattern>)` with `*` matching any run of characters, else the
    exact text. A rule of another tool matches none"""
    if rule in ("Bash", "Bash(*)"):
        return True
    if not (rule.startswith("Bash(") and rule.endswith(")")):
        return False
    inner = rule[len("Bash(") : -1]
    if inner.endswith(":*") or (inner.endswith(" *") and inner.count("*") == 1):
        prefix = inner[:-2]
        return part == prefix or part.startswith(prefix + " ")
    if "*" in inner:
        return re.fullmatch(".*".join(re.escape(s) for s in inner.split("*")), part, re.DOTALL) is not None
    return part == inner


@dataclass(frozen=True, slots=True)
class Allowlist:
    """A headless session's Bash allow and deny rules"""

    allow: tuple[str, ...]
    deny: tuple[str, ...]

    def denial(self, part: Part) -> str | None:
        """Why the part is denied, naming it and any deny rule; None when it is allowed. A deny
        rule matches past any leading assignment, an allow rule doesn't; both match the part as
        written and past the wrappers Claude Code strips"""
        text, bare = part.unwrapped()
        denied = (part.text, part.bare, text, bare)
        if rule := next((r for r in self.deny if any(matches(r, form) for form in denied)), None):
            return f"`{part.text}` matches the deny rule {rule}"
        if not any(matches(r, form) for r in self.allow for form in (part.text, text)):
            return f"no allow rule matches `{part.text}`"
        return None


@dataclass(frozen=True, slots=True)
class Headless:
    """What a headless gate session gets: its tool flags and its process environment"""

    allowed: tuple[str, ...]  # HEADLESS_TOOLS and the --claude-arg allow rules
    disallowed: tuple[str, ...]  # the --claude-arg deny rules
    env: Mapping[str, str]  # the session's process env, SHIPMILL_GATE=1 included
    home: Path  # whose ~/.claude/settings.json the session reads

    @classmethod
    def of(cls, claude_args: Sequence[str], environ: Mapping[str, str], home: Path) -> Headless:
        """As ClaudeCli.start starts a session: HEADLESS_TOOLS, the gate's --claude-arg flags, and
        headless_env with GATE_SESSION set, as its --settings env sets it for the session's tools"""
        from shipmill.gate import GATE_SESSION, HEADLESS_TOOLS, headless_env  # the gate's tick runs the check

        allow, deny = flag_rules(claude_args)
        return cls((*rules(HEADLESS_TOOLS), *allow), deny, {**headless_env(environ), GATE_SESSION: "1"}, home)

    def allowlist(self, worktree: Path, checkout: Path) -> Allowlist:
        """The rules for a gate session: the flags', then the user's, the project's (tracked, so
        read from worktree at origin/<default>), and the local settings' permissions, read from
        the checkout the gate's sessions start in, since an untracked file is never in worktree"""
        project, local = SETTINGS
        allow, deny = list(self.allowed), list(self.disallowed)
        for path in (self.home / ".claude" / "settings.json", worktree / project, checkout / local):
            more, less = permissions(path)
            allow += more
            deny += less
        return Allowlist(tuple(allow), tuple(deny))


# --- Step 2: the delivery hook -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Refusal:
    """The hook's exit 2 on a part: the rule its first stderr line names, and its Instead line"""

    rule: str
    instead: str

    def detail(self, part: str) -> str:
        return f"the hook's {self.rule} rule refuses `{part}`" + (f"; {self.instead}" if self.instead else "")


class Hook(Protocol):
    """What the check asks of the delivery hook: a command's parts, and its verdict on each"""

    def parts(self, command: str, cwd: Path) -> list[Part]: ...

    def refusal(self, part: Part, cwd: Path, env: Mapping[str, str]) -> Refusal | None: ...


def _load(script: Path) -> ModuleType:
    """The hook's script as a module, named after its path, so its dataclasses find it"""
    name = f"shipmill_delivery_{hashlib.sha256(str(script).encode()).hexdigest()[:12]}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise ReleaseError(f"{script} can't be loaded as the delivery hook's script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class DeliveryHook:
    """The delivery hook of the plugin install at root (its CLAUDE_PLUGIN_ROOT): the parts are
    its own script's `commands`, and each part goes to the PreToolUse command its hooks.json
    declares for Bash, run as Claude Code runs it, as the hook self-test does (spec 026)"""

    def __init__(self, root: Path, shell: str = "/bin/sh", run: HookRunner = run_hook) -> None:
        self.root = root
        self._command, self._timeout = pre_command(root / "hooks" / "hooks.json")
        self._script = _load(root / "hooks" / "delivery.py")
        self._shell = shell
        self._run = run

    def parts(self, command: str, cwd: Path) -> list[Part]:
        """The command's simple commands; the whole line as one when shlex can't split it, as
        the hook then lets it pass"""
        try:
            found = self._script.commands(command, cwd)
        except ValueError:
            return [Part(command.strip(), command.split()[0], command.strip())]
        return [Part(s.text(), s.words[0], shlex.join(s.words), s.cwd) for s in found]

    def refusal(self, part: Part, cwd: Path, env: Mapping[str, str]) -> Refusal | None:
        """The hook's refusal of the part, run in cwd, as a PreToolUse Bash input whose cwd is
        the directory a `cd` before the part set (cwd when none did), as the hook reads the whole
        line in a session; None when it lets the part run, which is any exit but 2, as Claude
        Code reads it"""
        stdin = json.dumps(
            {
                "session_id": "00000000-0000-4000-8000-000000000000",
                "transcript_path": "",
                "cwd": str(part.cwd or cwd),
                "permission_mode": "default",
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": part.text, "description": "shipmill's check of [agents] verify"},
                "tool_use_id": "toolu_shipmill_verify",
            }
        )
        done = self._run(
            [self._shell, "-c", self._command], stdin, cwd, {**env, "CLAUDE_PLUGIN_ROOT": str(self.root)}, self._timeout
        )
        if done.code != 2:
            return None
        said = done.stderr.strip().splitlines()
        first = said[0] if said else "no stderr"
        m = _REFUSAL.match(first)
        instead = next((line for line in said if line.startswith("Instead: ")), "")
        return Refusal(m["rule"] if m else first, instead)


# --- Step 3: the run -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Ran:
    """A command's exit code, None when it was stopped past its limit, and its stderr"""

    code: int | None
    stderr: str


Shell = Callable[[list[str], Path, Mapping[str, str], float], Ran]  # (argv, cwd, env, timeout)


def _exited(pid: int, timeout: float) -> bool:
    """Whether the child pid exits within timeout, left unreaped, so its pid, the id of its
    process group, can't be reused before the group is killed"""
    deadline = time.monotonic() + timeout
    while os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL)
    return True


def run_shell(argv: list[str], cwd: Path, env: Mapping[str, str], timeout: float) -> Ran:
    """argv in its own process group, stdin from /dev/null, stdout dropped, and stderr into a
    file, so a child holding it never keeps the check waiting; when argv exits, or past timeout,
    the whole group is killed, so a test runner's children stop and none outlives the worktree"""
    with tempfile.TemporaryFile() as stderr:
        try:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=dict(env),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr,
                start_new_session=True,
            )
        except OSError as exc:
            raise ReleaseError(f"{argv[0]} could not start: {exc}") from None
        with proc:
            exited = _exited(proc.pid, timeout)
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:  # nothing of the group is left
                pass
            except PermissionError:  # macOS's answer for a group whose one process is argv, exited
                if not exited:
                    raise
            code = proc.wait()
        if not exited:
            return Ran(None, "")
        size = stderr.seek(0, os.SEEK_END)
        stderr.seek(max(0, size - TAIL))
        return Ran(code, stderr.read().decode(errors="replace"))


def missing(parts: Sequence[Part], cwd: Path, path: str) -> str | None:
    """The first part's program that the PATH lacks (a relative path is read from cwd); None
    when every program is found"""
    for part in parts:
        for program in part.programs():
            if program in BUILTINS:
                continue
            if "/" in program:
                if not os.access(cwd / os.path.expanduser(program), os.X_OK):
                    return program
            elif shutil.which(program, path=path) is None:
                return program
    return None


def last_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1].strip()[:300] if lines else "no stderr"


# --- The check -----------------------------------------------------------------------------------


@contextmanager
def worktree(checkout: Path, default: str, git: Git) -> Iterator[Path]:
    """A worktree detached at origin/<default> under the checkout's .claude/worktrees, removed
    when the block ends, however it ends (D-24)"""
    folder = checkout / WORKTREES / f"{PREFIX}{secrets.token_hex(4)}"
    git(["git", "-C", str(checkout), "worktree", "add", "--detach", str(folder), f"origin/{default}"], checkout)
    try:
        yield folder
    finally:
        git(["git", "-C", str(checkout), "worktree", "remove", "--force", str(folder)], checkout)


def every_part(command: str, where: Path, hook: Hook) -> list[Part]:
    """The command's parts and, after them, those of its substitutions, nested ones too;
    ValueError when a substitution can't be read"""
    found = hook.parts(command, where)
    for body in substitutions(command):
        found += every_part(body, where, hook)
    return found


def judge(
    command: str, where: Path, allowlist: Allowlist, session: Headless, hook: Hook, shell: Shell, timeout: float
) -> Entry:
    """One command through the three steps; the first that fails names its result. The
    allowlist judges the commands of its substitutions as parts too, as Claude Code does; the
    hook gets the parts its own splitter finds, as it gets the line in a session"""
    parts = hook.parts(command, where)
    try:
        inner = [p for body in substitutions(command) for p in every_part(body, where, hook)]
    except ValueError:
        if "$(" in command or "`" in command:  # fail closed: what can't be read can't be allowed
            detail = f"can't read the command substitution in `{command}`, so no rule can allow it"
            return Entry(command, Result.DENIED, detail)
        inner = []  # an unclosed quote and no substitution: the shell's own error
    for part in (*parts, *inner):
        if (denied := allowlist.denial(part)) is not None:
            return Entry(command, Result.DENIED, denied)
    for part in parts:
        if (refused := hook.refusal(part, where, session.env)) is not None:
            return Entry(command, Result.REFUSED, refused.detail(part.text))
    ran = shell([session.env.get("SHELL") or "/bin/sh", "-c", command], where, session.env, timeout)
    if ran.code is None:
        return Entry(command, Result.TIMED_OUT, f"stopped after {timeout / 60:g} minutes")
    if ran.code == 0:
        return Entry(command, Result.OK, "")
    if ran.code == NOT_FOUND:
        path = session.env.get("PATH", "")
        if (program := missing(parts, where, path)) is not None:
            return Entry(command, Result.NOT_FOUND, f"{program} is not on the gate's PATH: {path}")
        return Entry(command, Result.NOT_FOUND, f"exit 127: {last_line(ran.stderr)}")
    return Entry(command, Result.FAILED, f"exit {ran.code}: {last_line(ran.stderr)}")


def check(
    commands: Sequence[str],
    checkout: Path,
    default: str,
    session: Headless,
    hook: Hook,
    git: Git,
    shell: Shell = run_shell,
    timeout: float = TIMEOUT,
) -> list[Entry]:
    """Each command's entry, in the list's order, from one worktree at origin/<default>, which
    is gone when this returns or raises"""
    with worktree(checkout, default, git) as where:
        allowlist = session.allowlist(where, checkout)
        return [judge(command, where, allowlist, session, hook, shell, timeout) for command in commands]
