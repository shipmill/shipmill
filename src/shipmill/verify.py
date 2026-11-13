"""Spec 064: check that a repo's verification commands, [agents] verify, work from a headless
gate session, where and as such a session would run them.

The check adds a worktree detached at origin/<default> under <checkout>/.claude/worktrees, the
folder implementers' worktrees use, and removes it when the check ends, however it ends (D-24).
Each command goes through three steps in the list's order, and the first that fails names its
result; a command that fails step 1 or 2 is not run:

1. The allowlist: each of its parts (its simple commands, as the delivery hook splits them)
   matches an allow rule and no deny rule of a headless session: HEADLESS_TOOLS, the gate's
   --claude-arg tool flags, and the settings files' permissions, as Claude Code matches a Bash
   rule; a deny rule wins
2. The delivery hook a gate session loads judges each part, with SHIPMILL_GATE=1 (D-82)
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
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import ModuleType
from typing import Protocol

from shipmill.errors import ReleaseError
from shipmill.hooks import SETTINGS, HookRunner, pre_command, run_hook

TIMEOUT = 30 * 60.0  # seconds a command may run before the check stops it
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
    """One simple command of a command line: its text, its program as written, and its text past
    any leading NAME=value assignments, which a deny rule matches too"""

    text: str
    program: str
    bare: str


# --- Step 1: the allowlist ----------------------------------------------------------------------


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
        rule matches past any leading assignment, an allow rule doesn't"""
        if rule := next((r for r in self.deny if matches(r, part.text) or matches(r, part.bare)), None):
            return f"`{part.text}` matches the deny rule {rule}"
        if not any(matches(r, part.text) for r in self.allow):
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

    def allowlist(self, worktree: Path) -> Allowlist:
        """The rules for a session in worktree: the flags', then the user's, the project's, and
        the local settings' permissions"""
        allow, deny = list(self.allowed), list(self.disallowed)
        for path in (self.home / ".claude" / "settings.json", *(worktree / name for name in SETTINGS)):
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
        return [Part(s.text(), s.words[0], shlex.join(s.words)) for s in found]

    def refusal(self, part: Part, cwd: Path, env: Mapping[str, str]) -> Refusal | None:
        """The hook's refusal of the part, a PreToolUse Bash input whose cwd is cwd; None when it
        lets the part run, which is any exit but 2, as Claude Code reads it"""
        stdin = json.dumps(
            {
                "session_id": "00000000-0000-4000-8000-000000000000",
                "transcript_path": "",
                "cwd": str(cwd),
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


def run_shell(argv: list[str], cwd: Path, env: Mapping[str, str], timeout: float) -> Ran:
    """argv in its own process group, stdin from /dev/null and stdout dropped; past timeout the
    whole group is killed, so a test runner's children stop too"""
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except OSError as exc:
        raise ReleaseError(f"{argv[0]} could not start: {exc}") from None
    with proc:
        try:
            _, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):  # the group ended on its own
                os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            return Ran(None, "")
    return Ran(proc.returncode, stderr)


def missing(parts: Sequence[Part], cwd: Path, path: str) -> str | None:
    """The first part's program that the PATH lacks (a relative path is read from cwd); None
    when every program is found"""
    for part in parts:
        program = part.program
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


def judge(
    command: str, where: Path, allowlist: Allowlist, session: Headless, hook: Hook, shell: Shell, timeout: float
) -> Entry:
    """One command through the three steps; the first that fails names its result"""
    parts = hook.parts(command, where)
    for part in parts:
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
        allowlist = session.allowlist(where)
        return [judge(command, where, allowlist, session, hook, shell, timeout) for command in commands]
