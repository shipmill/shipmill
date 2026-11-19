"""shipmill's delivery hooks for Claude Code (spec 026, D-36)

`delivery.py pre` reads a PreToolUse input for Bash and refuses a command the delivery rules
forbid, in a repo whose .github/shipmill.toml has an [agents] section: exit 2 with three lines
on stderr, the refused command, the rule, and the command to run instead. `delivery.py post`
reads a PostToolUse input for Edit, Write, and MultiEdit, and after an edit of the direction
(docs/product.md, docs/product/) or a REVIEW.md runs `shipmill product check` or `shipmill
review check`: exit 2 shows a failed check's output to the model. Exit 0 allows; exit 1 means
the input wasn't the hook JSON, or a check couldn't run. hooks/hooks.json runs it with a
Python 3.11+ that uv finds or installs, and exits 1 itself, letting the command run, when it
can't start it (D-40).

`delivery.py stop` reads a Stop input (spec 062): in a headless gate session (SHIPMILL_GATE=1)
of a repo with [agents], a final message that addresses the maintainer (@SHIPMILL_MAINTAINER, or
a line starting with one of ADDRESSES) while the transcript holds no successful issue create or
needs-decision label exits 2, once per session: stop_hook_active and a refusal record in the
temporary directory each let a later stop end. What it can't read exits 1, never 2.

Stdlib only and Python 3.11+ (tomllib), since the plugin can't import the installed shipmill.
The hooks catch an agent's mistake: a command shlex can't split, and `bash -c`, `eval`,
`$(...)`, and here-documents, pass; the trust filter (D-16) is the control against hostile
text. No command but a `git push`, and no edit but of the direction or a REVIEW.md, may start
a process, and each call reads a repo's config, and its pyproject.toml, at most once. A `gh api
graphql` call's `-F query=@file`, `-F <variable>=@file`, and --input file are read too, to tell
a merge mutation's mergeMethod (#1373); one the hook can't read, such as stdin, is refused.

The app-writes rule applies only where the App is available to the session (spec 033, D-54):
a non-empty SHIPMILL_APP_KEY in the hook's own environment, which shipmill gate sets on every
session it starts, or the App's key file at $HOME/.config/shipmill/app-<app_id>.pem, checked
with one stat and never read. A command's own NAME=value assignments are never read for it.

The uv-run rule (D-82) applies only in a session shipmill gate started headless, whose
--settings env sets SHIPMILL_GATE=1, read from the hook's own environment alone: there `uv run`
starts only python, pytest, ruff, mypy, a [hooks] uv_run program, a path to a .py file, or an
entry of the checkout's [project.scripts]. Its known limit: `uv run python -c`, the
allowlist's `Bash(uvx *)`, and `uv tool run`, the long form of uvx, still start any program,
so it narrows the routing around a denied command without closing it.
"""

from __future__ import annotations

import fnmatch
import io
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TextIO

CONFIG = Path(".github") / "shipmill.toml"
# The CLI runs as `uvx shipmill==<version>`, the version in the plugin's own plugin.json one
# folder above hooks/ (spec 031, D-43): the release the plugin was written against, never a
# bare shipmill from PATH. It runs anywhere the hook does: the hook itself needs uv, and a
# headless session's allowlist has `Bash(uvx *)`
PLUGIN_JSON = Path(__file__).resolve().parents[1] / ".claude-plugin" / "plugin.json"
PLUGIN_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
EVENTS = {"pre": "PreToolUse", "post": "PostToolUse"}
EDITS = frozenset({"Edit", "Write", "MultiEdit"})
CUT = 200  # the refused command, as the first line shows it
SHA = "<sha>"  # the lease's commit, which only the session knows: the remote branch it last fetched

# A Bash rule sees one process; Runner starts one and Context carries it, so a test counts them
Runner = Callable[[Sequence[str], Path], "subprocess.CompletedProcess[str]"]
ReadConfig = Callable[[Path], "str | None"]  # the config's text; None when there is no such file


def run(cmd: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True, check=False)


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


class BadInput(ValueError):
    """The hook input isn't the JSON object Claude Code sends: exit 1"""


class ConfigError(ValueError):
    """The config doesn't parse, or a key the hooks read is malformed"""


class PluginError(ValueError):
    """The plugin's plugin.json is missing, isn't JSON, or holds no X.Y.Z version: exit 2"""


def shipmill(path: Path = PLUGIN_JSON) -> tuple[str, ...]:
    """`uvx shipmill==<version>`, the version in the plugin's plugin.json (spec 031)"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PluginError(f"{path} is missing: the plugin's version names the shipmill it runs") from None
    except json.JSONDecodeError as exc:
        raise PluginError(f"{path} is not JSON: {exc}") from None
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str) or not PLUGIN_VERSION.match(version):
        raise PluginError(f"{path}: version is {version!r}, not X.Y.Z")
    return ("uvx", f"shipmill=={version}")


# --- The hook input --------------------------------------------------------------------------


@dataclass(frozen=True)
class HookInput:
    event: str
    tool: str
    tool_input: Mapping[str, object]
    cwd: Path

    def text(self, key: str) -> str:
        value = self.tool_input.get(key)
        if not isinstance(value, str):
            what = "has no" if key not in self.tool_input else "has a non-string"
            raise BadInput(f"the {self.tool} input {what} tool_input.{key}")
        return value


def parse_input(text: str) -> HookInput:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BadInput(f"stdin is not JSON: {exc}") from None
    if not isinstance(data, dict):
        raise BadInput("stdin is not a JSON object")
    for key in ("hook_event_name", "tool_name"):
        if key not in data:
            raise BadInput(f"the input has no {key}")
        if not isinstance(data[key], str):
            raise BadInput(f"the input's {key} is not a string")
    if "tool_input" not in data:
        raise BadInput("the input has no tool_input")
    tool_input = data["tool_input"]
    if not isinstance(tool_input, dict):
        raise BadInput("the input's tool_input is not an object")
    cwd = data.get("cwd")
    if cwd is not None and (not isinstance(cwd, str) or not os.path.isabs(cwd)):
        raise BadInput("the input's cwd is not an absolute path")
    return HookInput(data["hook_event_name"], data["tool_name"], tool_input, Path(cwd) if cwd else Path.cwd())


# --- The config ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """What the hooks read of a repo whose config has [agents]"""

    app_id: int | None = None
    default_branch: bool = True  # [hooks] default_branch
    private: tuple[str, ...] = ()  # [hooks] private
    uv_run: tuple[str, ...] = ()  # [hooks] uv_run: programs a gate session's uv run may start besides the built-in
    merge: str = "squash"  # [agents] merge: the method a pull request lands with, squash without the key (D-96)


MERGE_METHODS = ("squash", "merge")  # [agents] merge's values, as shipmill's AgentsConfig reads them (spec 072)
HOOKS_KEYS = frozenset({"default_branch", "private", "uv_run"})


def parse_config(text: str) -> Config | None:
    """The config, or None when it has no [agents] section and no rule applies; ConfigError
    names what is wrong, as the refusal's Rule line shows it"""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"the config doesn't parse: {exc}") from None
    if "agents" not in data:
        return None
    agents = data["agents"]
    if not isinstance(agents, dict):
        raise ConfigError("[agents] is not a table")
    app_id = agents.get("app_id")
    if app_id is not None and (not isinstance(app_id, int) or isinstance(app_id, bool) or app_id < 1):
        raise ConfigError(f"[agents] app_id must be an integer of 1 or more, got {app_id!r}")
    merge = agents.get("merge", "squash")
    if not isinstance(merge, str) or merge not in MERGE_METHODS:
        raise ConfigError(f'[agents] merge must be "squash" or "merge", got {merge!r}')
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ConfigError("[hooks] is not a table")
    unknown = sorted(set(hooks) - HOOKS_KEYS)
    if unknown:
        raise ConfigError(f"[hooks] has an unknown key: {unknown[0]}")
    default_branch = hooks.get("default_branch", True)
    if not isinstance(default_branch, bool):
        raise ConfigError(f"[hooks] default_branch must be true or false, got {default_branch!r}")
    private = hooks.get("private", [])
    if not isinstance(private, list) or not all(isinstance(glob, str) and glob for glob in private):
        raise ConfigError(f"[hooks] private must be a list of globs, got {private!r}")
    uv_run = hooks.get("uv_run", [])
    if not isinstance(uv_run, list) or not all(isinstance(name, str) and name for name in uv_run):
        raise ConfigError(f"[hooks] uv_run must be a list of program names, got {uv_run!r}")
    return Config(app_id, default_branch, tuple(private), tuple(uv_run), merge)


@dataclass(frozen=True)
class Broken:
    message: str


PYPROJECT = Path("pyproject.toml")


def parse_scripts(text: str) -> frozenset[str]:
    """pyproject.toml's [project.scripts] names; ConfigError when it doesn't parse or the
    table has the wrong shape"""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{PYPROJECT} doesn't parse: {exc}") from None
    project = data.get("project", {})
    if not isinstance(project, dict):
        raise ConfigError(f"{PYPROJECT}: [project] is not a table")
    scripts = project.get("scripts", {})
    if not isinstance(scripts, dict):
        raise ConfigError(f"{PYPROJECT}: [project.scripts] is not a table")
    return frozenset(scripts)


@dataclass
class Configs:
    """Each repo's config, and its pyproject.toml's [project.scripts], read at most once per call"""

    read: ReadConfig
    seen: dict[Path, Config | Broken | None] = field(default_factory=dict)
    scripts_seen: dict[Path, frozenset[str] | Broken] = field(default_factory=dict)

    def at(self, root: Path) -> Config | Broken | None:
        if root not in self.seen:
            self.seen[root] = self._load(root)
        return self.seen[root]

    def scripts(self, root: Path) -> frozenset[str] | Broken:
        """The checkout's [project.scripts] names; none without a pyproject.toml"""
        if root not in self.scripts_seen:
            self.scripts_seen[root] = self._scripts(root)
        return self.scripts_seen[root]

    def _scripts(self, root: Path) -> frozenset[str] | Broken:
        try:
            text = self.read(root / PYPROJECT)
        except (OSError, UnicodeDecodeError) as exc:
            return Broken(f"{PYPROJECT} can't be read: {exc}")
        if text is None:
            return frozenset()
        try:
            return parse_scripts(text)
        except ConfigError as exc:
            return Broken(str(exc))

    def _load(self, root: Path) -> Config | Broken | None:
        try:
            text = self.read(root / CONFIG)
        except (OSError, UnicodeDecodeError) as exc:
            return Broken(f"the config can't be read: {exc}")
        if text is None:
            return None
        try:
            return parse_config(text)
        except ConfigError as exc:
            return Broken(str(exc))


def repo_root(start: Path) -> Path | None:
    """The nearest folder holding a .git folder, or a worktree's .git file; no subprocess"""
    for folder in (start, *start.parents):
        if (folder / ".git").exists():
            return folder
    return None


# --- Reading a Bash command ------------------------------------------------------------------

PUNCTUATION = "();<>|&\n"
OPERATORS = sorted(
    ("&&", "||", ";;", "<<<", "<<-", "<<", ">>", "<&", ">&", "&>", "<>", ">|", "|&", "&", "|", ";", "\n")
    + ("(", ")", "<", ">"),
    key=len,
    reverse=True,
)
SEPARATORS = frozenset({"&&", "||", ";;", "&", "|", "|&", ";", "\n"})
PIPES = frozenset({"|", "|&"})
REDIRECTS = frozenset({"<<<", "<<-", "<<", ">>", "<&", ">&", "&>", "<>", ">|", "<", ">"})
KEYWORDS = frozenset({"!", "{", "if", "then", "elif", "else", "while", "until", "do", "time"})
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
WORD_START = " \t\n;&|()"


HERE_DOC = re.compile(r"<<-?[ \t]*(\S+)")


def _delimiter(word: str) -> str:
    return re.sub(r"[;&|()<>].*", "", word).replace("'", "").replace('"', "").replace("\\", "")


def _past_bodies(command: str, i: int, pending: list[str]) -> int:
    """The index past the here-document bodies that start after the newline at i"""
    lines = command[i + 1 :].split("\n")
    skipped = 0
    while pending and skipped < len(lines):
        if lines[skipped].strip() == pending[0]:
            pending.pop(0)
        skipped += 1
    pending.clear()
    return i + 1 + sum(len(line) + 1 for line in lines[:skipped])


def _substitution_end(command: str, i: int) -> int:
    """The index past the `)` closing a `$(` whose body starts at i, with its own quotes and
    here-documents, so a body's `"` doesn't end the double quotes around the `$(...)`"""
    depth = 1
    pending: list[str] = []
    quote = ""
    while i < len(command):
        ch = command[i]
        if quote == "'":
            quote = "" if ch == "'" else quote
        elif ch == "\\":
            i += 1
        elif quote == '"' and command.startswith("$(", i):
            i = _substitution_end(command, i + 2)
            continue
        elif quote == '"':
            quote = "" if ch == '"' else quote
        elif ch in "'\"":
            quote = ch
        elif not command.startswith("<<<", i) and (match := HERE_DOC.match(command, i)) is not None:
            pending.append(_delimiter(match.group(1)))
            i = match.end()
            continue
        elif ch == "\n" and pending:
            i = _past_bodies(command, i, pending)
            continue
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if not depth:
                return i + 1
        i += 1
    return i


def _strip(command: str) -> str:
    """The command without comments, line continuations, and here-document bodies, which the
    hooks don't read; quotes are kept for shlex"""
    out: list[str] = []
    pending: list[str] = []  # here-document delimiters whose bodies start at the next newline
    quote = ""
    i = 0
    while i < len(command):
        ch = command[i]
        if quote == "'":
            out.append(ch)
            quote = "" if ch == "'" else quote
        elif ch == "\\" and command[i + 1 : i + 2] == "\n":
            i += 1
        elif ch == "\\":
            out.append(command[i : i + 2])
            i += 1
        elif quote == '"' and command.startswith("$(", i):
            # "$(cat <<'EOF' ... EOF)": one word, kept as text with its own quotes escaped
            end = _substitution_end(command, i + 2)
            out.append(command[i:end].replace("\\", "\\\\").replace('"', '\\"'))
            i = end
            continue
        elif quote == '"':
            out.append(ch)
            quote = "" if ch == '"' else quote
        elif ch in "'\"":
            out.append(ch)
            quote = ch
        elif ch == "#" and (i == 0 or command[i - 1] in WORD_START):
            end = command.find("\n", i)
            i = len(command) if end < 0 else end
            continue
        elif command.startswith("<<", i) and not command.startswith("<<<", i):
            match = HERE_DOC.match(command, i)
            if match is None:
                out.append(ch)
            else:
                pending.append(_delimiter(match.group(1)))
                out.append(match.group(0))
                i = match.end()
                continue
        elif ch == "\n" and pending:
            out.append(ch)
            i = _past_bodies(command, i, pending)
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _units(token: str) -> list[str]:
    """A run of punctuation, such as `);` or `&&\\n`, as its operators"""
    units = []
    while token:
        op = next((o for o in OPERATORS if token.startswith(o)), token[0])
        units.append(op)
        token = token[len(op) :]
    return units


def _lex(command: str) -> list[tuple[str, bool]]:
    """Words and operators; ValueError when shlex can't split it"""
    lexer = shlex.shlex(_strip(command), posix=True, punctuation_chars=PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    found: list[tuple[str, bool]] = []
    for token in lexer:
        if token and all(ch in PUNCTUATION for ch in token):
            found.extend((unit, True) for unit in _units(token))
        else:
            found.append((token, False))
    return found


@dataclass(frozen=True)
class Simple:
    """One simple command: its leading NAME=value assignments, its words, the program first,
    and the directory it runs in"""

    assignments: tuple[str, ...]
    words: tuple[str, ...]
    cwd: Path

    @property
    def program(self) -> str:
        return os.path.basename(self.words[0])

    def text(self) -> str:
        return shlex.join((*self.assignments, *self.words))


def _simple(words: list[str], cwd: Path) -> Simple | None:
    while words and words[0] in KEYWORDS:
        words = words[1:]
    head = 0
    while head < len(words) and ASSIGNMENT.match(words[head]):
        head += 1
    assignments, rest = words[:head], words[head:]
    if rest and os.path.basename(rest[0]) == "env":  # env NAME=value gh ...
        i = 1
        while i < len(rest) and (rest[i].startswith("-") or ASSIGNMENT.match(rest[i])):
            if rest[i] in ("-u", "--unset", "-C", "--chdir", "-S", "--split-string"):
                i += 1
            elif ASSIGNMENT.match(rest[i]):
                assignments.append(rest[i])
            i += 1
        rest = rest[i:]
    return Simple(tuple(assignments), tuple(rest), cwd) if rest else None


def _cd(words: Sequence[str], cwd: Path) -> Path:
    args = [w for w in words[1:] if w not in ("-L", "-P", "-e", "-@")]
    if not args:
        return Path.home()
    if args[0] == "-":
        return cwd
    return Path(os.path.normpath(os.path.join(cwd, os.path.expanduser(args[0]))))


def commands(command: str, cwd: Path) -> list[Simple]:
    """The simple commands of a Bash command line, each with the directory a `cd` before it
    reached; ValueError when shlex can't split it"""
    tokens = _lex(command)
    found: list[Simple] = []
    dirs = [cwd]  # a subshell's cd ends with it
    words: list[str] = []

    def end(separator: str) -> None:
        nonlocal words
        simple = _simple(words, dirs[-1])
        words = []
        if simple is None:
            return
        found.append(simple)
        if simple.program == "cd" and separator not in PIPES:
            dirs[-1] = _cd(simple.words, dirs[-1])

    i = 0
    while i < len(tokens):
        token, operator = tokens[i]
        if not operator:
            words.append(token)
        elif token in SEPARATORS:
            end(token)
        elif token in REDIRECTS:
            if words and words[-1].isdigit():  # 2>&1: the descriptor isn't an argument
                words.pop()
            if i + 1 < len(tokens) and not tokens[i + 1][1]:
                i += 1  # the redirect's target
        elif token == "(" and words and words[-1].endswith("$"):
            depth = 1  # $(...): a substitution the hooks don't read; it stays an argument
            while depth and i + 1 < len(tokens):
                i += 1
                if tokens[i] == ("(", True):
                    depth += 1
                elif tokens[i] == (")", True):
                    depth -= 1
            words[-1] += "(...)"
        elif token == "(":
            end(token)
            dirs.append(dirs[-1])
        else:  # ")"
            end(token)
            if len(dirs) > 1:
                dirs.pop()
        i += 1
    end("\n")
    return found


# --- What a command is -----------------------------------------------------------------------

GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"})


@dataclass(frozen=True)
class GitCall:
    where: Path  # the directory git runs in, after any -C
    sub: int  # the subcommand's index in the words


def git_call(cmd: Simple) -> GitCall | None:
    if cmd.program != "git":
        return None
    where = cmd.cwd
    i = 1
    while i < len(cmd.words) and cmd.words[i].startswith("-"):
        if cmd.words[i] == "-C" and i + 1 < len(cmd.words):
            where = Path(os.path.normpath(os.path.join(where, os.path.expanduser(cmd.words[i + 1]))))
        if cmd.words[i] in GIT_VALUE_OPTIONS:
            i += 1
        i += 1
    return GitCall(where, i) if i < len(cmd.words) else None


def is_push(cmd: Simple) -> bool:
    call = git_call(cmd)
    return call is not None and cmd.words[call.sub] == "push"


@dataclass(frozen=True)
class GhCall:
    shipmill: bool  # through `shipmill gh`, directly or through uvx
    start: int  # the index in the words of gh's first argument

    def args(self, cmd: Simple) -> tuple[str, ...]:
        return cmd.words[self.start :]


def _shipmill_gh(words: Sequence[str], at: int) -> int | None:
    """The index after `gh` when words[at] is shipmill and its subcommand is gh"""
    i = at + 1
    while i < len(words) and words[i].startswith("-"):
        i += 2 if words[i] == "--repo" else 1
    return i + 1 if i < len(words) and words[i] == "gh" else None


# The shipmill package as uvx runs it: bare, with extras, or with any version specifier, such as
# shipmill==0.57.0, shipmill@latest, shipmill>=0.57, or shipmill[x]==0.57.0; each runs shipmill
# from PyPI, so its gh is shipmill gh, which the rebase-merge rule still checks
SHIPMILL_SPEC = re.compile(r"^shipmill(?:\[[^\]]*\])?(?:\s*[=<>!~@].*)?$")


def gh_call(cmd: Simple) -> GhCall | None:
    program = cmd.program
    if program == "gh":
        return GhCall(False, 1)
    if program == "shipmill":
        start = _shipmill_gh(cmd.words, 0)
        return None if start is None else GhCall(True, start)
    if program in ("uvx", "uv"):  # uvx shipmill==<version> gh ..., uvx --from <spec> shipmill gh ...
        for at in range(1, len(cmd.words)):
            word = cmd.words[at]
            pinned = SHIPMILL_SPEC.match(word) is not None or os.path.basename(word) == "shipmill"
            start = _shipmill_gh(cmd.words, at) if pinned else None
            if start is not None:
                return GhCall(True, start)
    return None


GH_VALUE_OPTIONS = frozenset({"-R", "--repo"})


def gh_command(args: Sequence[str]) -> tuple[str, str]:
    """The command group and subcommand, such as ("pr", "merge"); "" when absent"""
    found: list[str] = []
    i = 0
    while i < len(args) and len(found) < 2:
        if args[i] in GH_VALUE_OPTIONS:
            i += 1
        elif not args[i].startswith("-"):
            found.append(args[i])
        i += 1
    found += ["", ""]
    return found[0], found[1]


GH_WRITES: Mapping[str, frozenset[str]] = {
    "issue": frozenset(
        {"create", "new", "comment", "edit", "close", "reopen", "delete", "lock", "unlock", "pin", "unpin"}
        | {"transfer", "develop"}
    ),
    "pr": frozenset(
        {"create", "new", "comment", "edit", "close", "reopen", "merge", "review", "ready", "lock", "unlock"}
        | {"update-branch"}
    ),
    "label": frozenset({"create", "edit", "delete", "clone"}),
    "release": frozenset({"create", "edit", "delete", "delete-asset", "upload"}),
    "workflow": frozenset({"run", "enable", "disable"}),
    "run": frozenset({"rerun", "cancel", "delete"}),
    "repo": frozenset({"create", "edit", "delete", "rename", "archive", "unarchive", "fork"}),
    "secret": frozenset({"set", "delete", "remove"}),
    "variable": frozenset({"set", "delete", "remove"}),
}
API_FIELDS = ("-f", "-F", "--field", "--raw-field")
API_VALUE_OPTIONS = frozenset(
    {"-H", "--header", "-q", "--jq", "-t", "--template", "--hostname", "--cache", "-p", "--preview"}
)


@dataclass(frozen=True)
class ApiField:
    """One `gh api` field, `key=value`: its flag (-f, -F, --field, --raw-field), and the index of
    the word holding it in gh's arguments"""

    flag: str
    text: str  # key=value
    word: int

    @property
    def key(self) -> str:
        return self.text.partition("=")[0]

    @property
    def value(self) -> str:
        return self.text.partition("=")[2]

    @property
    def typed(self) -> bool:
        """-F and --field read `@file` as the file's contents; -f and --raw-field never do"""
        return self.flag in ("-F", "--field")


@dataclass(frozen=True)
class ApiCall:
    method: str | None  # -X's value
    fields: tuple[ApiField, ...]
    inputs: tuple[str, ...]  # each --input's value
    endpoint: str | None

    @property
    def graphql(self) -> bool:
        return self.endpoint is not None and (self.endpoint == "graphql" or self.endpoint.endswith("/graphql"))


def api_call(args: Sequence[str]) -> ApiCall:
    """`gh api`'s method, fields, --input files, and endpoint, from gh's arguments"""
    method: str | None = None
    fields: list[ApiField] = []
    inputs: list[str] = []
    endpoint: str | None = None
    i = 1
    while i < len(args):
        word = args[i]
        value = args[i + 1] if i + 1 < len(args) else ""
        long, eq, attached = word.partition("=")
        if word in ("-X", "--method"):
            method, i = value, i + 1
        elif eq and long == "--method":
            method = attached
        elif word.startswith("-X"):
            method = word[2:]
        elif word in API_FIELDS:
            fields.append(ApiField(word, value, i + 1))
            i += 1
        elif eq and long in ("--field", "--raw-field"):
            fields.append(ApiField(long, attached, i))
        elif word[:2] in ("-f", "-F") and len(word) > 2:
            fields.append(ApiField(word[:2], word[2:], i))
        elif word == "--input" or long == "--input":
            inputs.append(attached if eq else value)
            i += 0 if eq else 1
        elif word in API_VALUE_OPTIONS:
            i += 1
        elif not word.startswith("-") and endpoint is None:
            endpoint = word
        i += 1
    return ApiCall(method, tuple(fields), tuple(inputs), endpoint)


def _api_write(args: Sequence[str]) -> bool:
    """`gh api`: -X other than GET, or a field or --input without -X GET; for graphql, a query
    that holds mutation. A query read from a file (`-F query=@file`) or --input counts as a
    write, since the hook reads no file to tell: `shipmill gh` runs a read as well"""
    call = api_call(args)
    if call.endpoint == "graphql":
        queries = [f for f in call.fields if f.key == "query"]
        from_file = any(f.typed and f.value.startswith("@") for f in queries)
        return bool(call.inputs) or from_file or any("mutation" in f.value for f in queries)
    if call.method is not None:
        return call.method.upper() != "GET"
    return bool(call.fields) or bool(call.inputs)


def is_gh_write(args: Sequence[str]) -> bool:
    group, sub = gh_command(args)
    if group == "api":
        return _api_write(args)
    return sub in GH_WRITES.get(group, frozenset())


# --- The rules -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Context:
    runner: Runner  # for the git push rules that read the remote's default branch, and the checks
    configs: Configs
    plugin: Path = PLUGIN_JSON  # the plugin.json whose version the CLI runs at (spec 031)
    env: Mapping[str, str] = field(default_factory=lambda: os.environ)  # the hook's own environment (spec 033)


APP_KEY = "SHIPMILL_APP_KEY"  # the gate sets it on every session it starts (spec 033)


def app_available(app_id: int, env: Mapping[str, str]) -> bool:
    """Spec 033, D-54: the App is available to the session when the hook's own environment has
    a non-empty SHIPMILL_APP_KEY, or when the App's key file is at
    $HOME/.config/shipmill/app-<app_id>.pem. One stat at most: the file is never opened, and
    no process starts. A HOME that is unset or not absolute counts only the variable, so no
    path in the repo can stand in for the host's"""
    if env.get(APP_KEY):
        return True
    home = env.get("HOME", "")
    if not os.path.isabs(home):
        return False
    return os.path.isfile(os.path.join(home, ".config", "shipmill", f"app-{app_id}.pem"))


@dataclass(frozen=True)
class Rule:
    name: str
    text: str  # the Rule line
    source: str  # where it is written
    guards: Callable[[Simple], bool]  # the rule judges this command, so a broken config refuses it
    # the command to run instead, or what to do when no command is left; None allows
    check: Callable[[Simple, Config, Context], Simple | str | None]
    gate: bool = False  # judged only in a headless session shipmill gate started (D-82)


def _with_args(cmd: Simple, call: GhCall, args: Sequence[str]) -> Simple:
    return replace(cmd, words=(*cmd.words[: call.start], *args))


MERGE_VALUE_OPTIONS = frozenset(
    {"-b", "--body", "-F", "--body-file", "-t", "--subject", "-A", "--author-email", "--match-head-commit"}
    | GH_VALUE_OPTIONS
)
MERGE_VALUE_SHORTS = "bFtAR"


def _merge_swap(args: Sequence[str], method: str, to: str) -> list[str] | None:
    """gh pr merge's arguments with --<to> for --<method> or its letter (-r, -s), bundled or
    not (as in -dr); None when no word names method. A flag given any value (--squash=1, -s=T,
    -ds=true, which gh's flag parser reads as true) names it too, so no spelling of a value
    gets past the rule"""
    letter = method[0]
    out: list[str] = []
    named = False
    i = 0
    while i < len(args):
        word = args[i]
        short = re.fullmatch(r"-([A-Za-z]+)(=.*)?", word, re.DOTALL)
        if word == f"--{method}" or word.startswith(f"--{method}="):
            named = True
        elif short is not None:  # -r, bundled as in -dr, or with a value as in -r=true
            letters, value = short.group(1), short.group(2) or ""
            cut = next((k for k, ch in enumerate(letters) if ch in MERGE_VALUE_SHORTS), len(letters))
            named = named or letter in letters[:cut]
            kept = letters[:cut].replace(letter, "") + letters[cut:]
            if value and (cut < len(letters) or not letters.endswith(letter)):  # the value isn't method's
                kept += value
            if kept:
                out.append(f"-{kept}")
            if cut == len(letters) - 1 and not value:  # a value option last: its value is the next word
                out.extend(args[i + 1 : i + 2])
                i += 1
        elif word in MERGE_VALUE_OPTIONS:
            out.extend(args[i : i + 2])
            i += 1
        else:
            out.append(word)
        i += 1
    return [*out, f"--{to}"] if named else None


# GraphQL's merge mutations (#1373): each takes mergeMethod, MERGE when omitted
GRAPHQL_MERGE = re.compile(r"\b(?:mergePullRequest|enablePullRequestAutoMerge)\s*\(")
# what the hook reads past in a query: a block string, a string, a comment
GRAPHQL_SKIP = re.compile(r'"""(?:\\"""|[^"]|"(?!""))*"""|"(?:\\.|[^"\\\n])*"|#[^\n\r]*')
GRAPHQL_METHOD = re.compile(r"\bmergeMethod\b(?:\s*:\s*(\$?[A-Za-z_]\w*))?")
GRAPHQL_INPUT = re.compile(r"\binput\s*:\s*\$([A-Za-z_]\w*)")
GRAPHQL_FIELD_KEY = re.compile(r"^([^\[\]]+)\[([^\[\]]+)\]$")  # gh's nested field, input[mergeMethod]
GRAPHQL_METHODS = frozenset({"MERGE", "SQUASH", "REBASE"})


@dataclass(frozen=True)
class Written:
    """A value as gh sends it, and where the command writes it: the index of the word in gh's
    arguments, or the file gh reads it from"""

    value: object
    word: int | None = None
    file: str | None = None
    literal: bool = False  # the word is a query that holds the value inline


@dataclass(frozen=True)
class Unread:
    """A variable's value from a file the hook can't read, such as stdin"""

    why: str


@dataclass(frozen=True)
class Merges:
    """A gh api graphql call's merge mutations: each method it names (MERGE for one it omits),
    upper-case, and why the hook can't tell one, or None when it can tell them all"""

    methods: tuple[Written, ...]
    unread: str | None


GRAPHQL_FILE_MAX = 1 << 20  # a query or body file past this is not read: it counts as unread


def _graphql_file(path: str, cwd: Path) -> str | None:
    """A file gh reads for `@path` or --input path; None for stdin, a file the hook can't read,
    one past GRAPHQL_FILE_MAX, or no regular file: a FIFO or a device such as /dev/zero or
    /dev/stdin would hang the hook, which opens without blocking and reads regular files only"""
    if path in ("", "-"):
        return None
    try:
        fd = os.open(Path(cwd, os.path.expanduser(path)), os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                return None
            data = file.read(GRAPHQL_FILE_MAX + 1)
    except OSError:
        return None
    if len(data) > GRAPHQL_FILE_MAX:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _graphql_args(text: str, at: int) -> str | None:
    """The argument list of the call whose ( is at text[at - 1], to its ); None if unclosed"""
    depth = 1
    for i in range(at, len(text)):
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        if depth == 0:
            return text[at:i]
    return None


def graphql_merges(cmd: Simple, args: Sequence[str]) -> Merges | None:
    """A gh api graphql call's merge mutations, mergePullRequest and enablePullRequestAutoMerge:
    the query from -f/-F query= (an -F @file read), or from an --input file's JSON, and each
    mutation's mergeMethod from a literal, a variable a field or the --input's variables gives,
    or GitHub's default, MERGE. None when the call is no graphql call, or holds no merge
    mutation and its whole query is read"""
    api = api_call(args)
    if not api.graphql:
        return None
    unread: list[str] = []
    queries: list[Written] = []
    scalars: dict[str, list[Written]] = {}  # a variable gh sends: m from -f m=SQUASH
    objects: dict[str, dict[str, list[Written]]] = {}  # input from -f input[mergeMethod]=SQUASH

    def why(path: str) -> str:
        return f"{'stdin' if path in ('', '-') else path} cannot be read"

    def read(path: str) -> str | None:
        text = _graphql_file(path, cmd.cwd)
        if text is None:
            unread.append(why(path))
        return text

    for f in api.fields:
        if f.typed and f.value.startswith("@") and f.key == "query":
            text = read(f.value[1:])
            if text is None:
                continue
            written = Written(text, file=f.value[1:])
        elif f.typed and f.value.startswith("@"):  # a variable's file counts only if a merge reads it
            text = _graphql_file(f.value[1:], cmd.cwd)
            written = Written(Unread(why(f.value[1:])) if text is None else text.strip(), file=f.value[1:])
        else:
            written = Written(f.value, word=f.word, literal=f.key == "query")
        nested = GRAPHQL_FIELD_KEY.match(f.key)
        if f.key == "query":
            queries.append(written)
        elif nested is not None:
            objects.setdefault(nested.group(1), {}).setdefault(nested.group(2), []).append(written)
        elif f.key != "operationName":
            scalars.setdefault(f.key, []).append(written)
    for path in api.inputs:
        text = read(path)
        if text is None:
            continue
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            unread.append(f"{path} is not JSON")
            continue
        if not isinstance(body, dict):
            unread.append(f"{path} is not a JSON object")
            continue
        if isinstance(body.get("query"), str):
            queries.append(Written(body["query"], file=path))
        variables = body.get("variables")
        for name, value in (variables if isinstance(variables, dict) else {}).items():
            if isinstance(value, dict):
                for key, item in value.items():
                    objects.setdefault(name, {}).setdefault(key, []).append(Written(item, file=path))
            else:
                scalars.setdefault(name, []).append(Written(value, file=path))

    methods: list[Written] = []

    def method(found: Written) -> None:
        name = found.value.upper() if isinstance(found.value, str) else None
        if name in GRAPHQL_METHODS:
            methods.append(replace(found, value=name))
        elif isinstance(found.value, Unread):
            unread.append(found.value.why)
        else:
            unread.append(f"mergeMethod {found.value!r} names no merge method")

    for query in queries:
        assert isinstance(query.value, str)
        text = GRAPHQL_SKIP.sub(lambda m: '""' if m.group().startswith('"') else " ", query.value)
        for call in GRAPHQL_MERGE.finditer(text):
            inside = _graphql_args(text, call.end())
            if inside is None:
                unread.append("its arguments do not close")
                continue
            named = list(GRAPHQL_METHOD.finditer(inside))
            for found in named:
                value = found.group(1)
                if value is None:
                    unread.append("a mergeMethod holds no enum value")
                elif value.startswith("$"):
                    given = scalars.get(value[1:], [])
                    if not given:
                        unread.append(f"{value} is not given")
                    for written in given:
                        method(written)
                else:
                    method(replace(query, value=value))
            variable = GRAPHQL_INPUT.search(inside)
            if not named and variable is not None:
                name = variable.group(1)
                if name not in objects:
                    unread.append(f"${name} is not given")
                for written in objects.get(name, {}).get("mergeMethod", []):
                    method(written)
                if name in objects and "mergeMethod" not in objects[name]:
                    methods.append(Written("MERGE"))
            elif not named:
                methods.append(Written("MERGE"))
    if not methods and not unread:
        return None
    return Merges(tuple(methods), unread[0] if unread else None)


def _graphql_swapped(cmd: Simple, call: GhCall, merges: Merges, method: str, to: str) -> Simple | str | None:
    """The call with each mergeMethod that names method swapped for to: in the query, or in the
    field that gives its variable; what to change when a file names it; None when none does"""
    old, new = method.upper(), to.upper()
    hits = [w for w in merges.methods if w.value == old]
    if not hits:
        return None
    files = sorted({w.file for w in hits if w.file is not None})
    if files:
        return f"set mergeMethod to {new} in {', '.join(files)}, then run: {cmd.text()}"
    args = list(call.args(cmd))
    swap = re.compile(rf"(\bmergeMethod\s*:\s*){old}\b", re.IGNORECASE)
    for w in hits:
        assert w.word is not None
        word = args[w.word]
        if w.literal:
            args[w.word] = swap.sub(rf"\g<1>{new}", word)
        else:  # the field's value is the word's tail: key=SQUASH, -fkey=SQUASH, --field=key=SQUASH
            head, _, _ = word.rpartition("=")
            args[w.word] = f"{head}={new}"
    return _with_args(cmd, call, args)


def _merge_guards(method: str) -> Callable[[Simple], bool]:
    """A rule judging every gh pr merge, a gh api call whose merge_method is method, and a gh
    api graphql call with a merge mutation, or a query the hook can't read"""

    def guards(cmd: Simple) -> bool:
        call = gh_call(cmd)
        if call is None:
            return False
        args = call.args(cmd)
        if gh_command(args) == ("pr", "merge"):
            return True
        if gh_command(args)[0] != "api":
            return False
        return any(f"merge_method={method}" in word for word in args) or graphql_merges(cmd, args) is not None

    return guards


def _method_swapped(cmd: Simple, method: str, to: str) -> Simple | str | None:
    """The command with method swapped for to: gh pr merge's flag, a gh api call's
    merge_method, or a graphql merge mutation's mergeMethod; what to do when the hook can't
    read a mutation's method (fail closed, #1373); None when it names no method"""
    call = gh_call(cmd)
    if call is None:
        return None
    args = call.args(cmd)
    group, sub = gh_command(args)
    if (group, sub) == ("pr", "merge"):
        swapped = _merge_swap(args, method, to)
        return None if swapped is None else _with_args(cmd, call, swapped)
    if group != "api":
        return None
    merges = graphql_merges(cmd, args)
    if merges is not None:
        if merges.unread is not None:
            return (
                f"the hook cannot read the mergeMethod of a merge mutation ({merges.unread}); write it inline,"
                f" mergeMethod: {to.upper()}, in -f query=, or give its variable as a -f field, then run the call"
            )
        return _graphql_swapped(cmd, call, merges, method, to)
    field = f"merge_method={method}"
    if any(field in word for word in args):
        return _with_args(cmd, call, [word.replace(field, f"merge_method={to}") for word in args])
    return None


def _rebase_check(cmd: Simple, config: Config, ctx: Context) -> Simple | str | None:
    """No rebase merge (D-96); instead, the method [agents] merge names"""
    return _method_swapped(cmd, "rebase", config.merge)


def _method_check(cmd: Simple, config: Config, ctx: Context) -> Simple | str | None:
    """Spec 072: under [agents] merge = "merge", a squash merge; instead, a merge commit. Under
    "squash", or no key, both methods pass: --merge is how a stack's base lands, which the hook
    can't tell from another pull request (S-026-10)"""
    return _method_swapped(cmd, "squash", "merge") if config.merge == "merge" else None


PUSH_VALUE_OPTIONS = frozenset({"-o", "--push-option", "--receive-pack", "--exec", "--repo"})


def _lease_ref(refspec: str) -> str:
    src, colon, dst = refspec.partition(":")
    ref = dst if colon else src
    ref = ref.removeprefix("refs/heads/")
    return "<branch>" if ref in ("", "HEAD") else ref


def _force_check(cmd: Simple, config: Config, ctx: Context) -> Simple | None:
    """A force push without a lease pinned to a commit: --force, -f, a + refspec, a bare
    --force-with-lease, or --force-with-lease=<ref>; instead, a lease on each ref the push
    names, pinned to <sha>, with the + dropped"""
    call = git_call(cmd)
    if call is None or cmd.words[call.sub] != "push":
        return None
    words = cmd.words
    out = list(words[: call.sub + 1])
    positions: list[int] = []  # the positional arguments' indexes in out
    pinned: list[str] = []
    unpinned: list[str] = []
    forced = False
    options_end = False
    i = call.sub + 1
    while i < len(words):
        word = words[i]
        if options_end or not word.startswith("-") or word == "-":
            positions.append(len(out))
            out.append(word)
        elif word == "--":
            options_end = True
            out.append(word)
        elif word in PUSH_VALUE_OPTIONS:
            out.extend(words[i : i + 2])
            i += 1
        elif word in ("--force", "--force-with-lease"):
            forced = True
        elif word.startswith("--force-with-lease="):
            ref, colon, _ = word.partition("=")[2].partition(":")
            if colon:
                pinned.append(ref)
                out.append(word)
            else:
                forced = True
                unpinned.append(ref)
        elif re.fullmatch(r"-[A-Za-z]+", word):
            letters = word[1:]
            cut = letters.find("o")  # -o takes a value: the letters after it are the value
            head, tail = (letters, "") if cut < 0 else (letters[:cut], letters[cut:])
            forced = forced or "f" in head
            kept = head.replace("f", "") + tail
            if kept:
                out.append(f"-{kept}")
            if tail == "o" and i + 1 < len(words):
                out.append(words[i + 1])
                i += 1
        else:
            out.append(word)
        i += 1
    refspecs = positions[1:]  # the first positional is the remote
    for at in refspecs:
        if out[at].startswith("+"):
            forced = True
            out[at] = out[at][1:]
    if not forced:
        return None
    refs = [_lease_ref(ref) for ref in unpinned] + [_lease_ref(out[at]) for at in refspecs]
    if not refs:
        refs = ["<branch>"]
    leases = [f"--force-with-lease={ref}:{SHA}" for ref in dict.fromkeys(refs) if ref not in pinned]
    out[call.sub + 1 : call.sub + 1] = leases
    return replace(cmd, words=tuple(out))


ORIGIN_HEAD = "refs/remotes/origin/HEAD"
BRANCH = "<branch>"  # the work branch to push instead, which only the session knows


def _git_out(ctx: Context, where: Path, *args: str) -> str | None:
    """A git query's one line of output; None when it fails, which the rule reads as unknown"""
    try:
        result = ctx.runner(("git", *args), where)
    except OSError:
        return None
    out = result.stdout.strip()
    return out if result.returncode == 0 and out else None


def _push_positionals(words: Sequence[str], start: int) -> tuple[list[int], set[str]]:
    """The indexes of a git push's positional arguments (the remote, then the refspecs), and
    its options"""
    positionals: list[int] = []
    options: set[str] = set()
    options_end = False
    i = start
    while i < len(words):
        word = words[i]
        if options_end or not word.startswith("-") or word == "-":
            positionals.append(i)
        elif word == "--":
            options_end = True
        elif word in PUSH_VALUE_OPTIONS:
            i += 1
        elif re.fullmatch(r"-[A-Za-z]+", word):
            letters = word[1:]
            options.update(f"-{ch}" for ch in letters.partition("o")[0])
            if letters.endswith("o"):  # -o takes the next word as its value
                i += 1
        else:
            options.add(word.partition("=")[0])
        i += 1
    return positionals, options


def _destination(refspec: str) -> str:
    """The branch a refspec writes, without +, refs/heads/, and with HEAD left for the caller"""
    src, colon, dst = refspec.removeprefix("+").partition(":")
    ref = dst if colon and dst else src
    return ref.removeprefix("refs/heads/")


EVERY_BRANCH = frozenset({"--all", "--branches", "--mirror"})


def _lease_to_branch(words: Sequence[str], default: str) -> list[str]:
    """force-push's lease on the default branch, moved to <branch> with the push"""
    prefix = f"--force-with-lease={default}:"
    return [f"--force-with-lease={BRANCH}:{w.removeprefix(prefix)}" if w.startswith(prefix) else w for w in words]


def _default_check(cmd: Simple, config: Config, ctx: Context) -> Simple | None:
    """A push to the default branch, the target of origin/HEAD: a refspec naming it, a glob
    refspec matching it, --all, --branches, or --mirror, or no refspec while the current
    branch's push target is it; instead, the same push to <branch>. Unknown (origin/HEAD
    unset, no upstream) allows; doctor reports an unset origin/HEAD"""
    call = git_call(cmd)
    if not config.default_branch or call is None or cmd.words[call.sub] != "push":
        return None
    positionals, options = _push_positionals(cmd.words, call.sub + 1)
    refspecs = positionals[1:]
    if not refspecs and "--tags" in options and not options & EVERY_BRANCH:
        return None  # tags only: not the current branch's push
    target = _git_out(ctx, call.where, "symbolic-ref", "--quiet", ORIGIN_HEAD)
    if target is None or not target.startswith("refs/remotes/origin/"):
        return None
    default = target.removeprefix("refs/remotes/origin/")
    if not refspecs and options & EVERY_BRANCH:  # every branch, the default one too
        words = [w for w in cmd.words if w.partition("=")[0] not in EVERY_BRANCH]
        words += [] if positionals else ["origin"]
        return replace(cmd, words=(*words, f"HEAD:{BRANCH}"))
    if not refspecs:
        if _git_out(ctx, call.where, "rev-parse", "--symbolic-full-name", "@{push}") != target:
            return None
        words = [*cmd.words] if positionals else [*cmd.words, "origin"]
        return replace(cmd, words=(*words, f"HEAD:{BRANCH}"))
    head: str | None = None
    out = list(cmd.words)
    hit = False
    for at in refspecs:
        word = out[at]
        dst = _destination(word)
        if dst in ("HEAD", "@"):
            if head is None:
                head = _git_out(ctx, call.where, "rev-parse", "--symbolic-full-name", "HEAD") or ""
            dst = head.removeprefix("refs/heads/")
        if dst == default or ("*" in dst and fnmatch.fnmatchcase(default, dst)):
            hit = True
            plus = "+" if word.startswith("+") else ""
            src = word.removeprefix("+").partition(":")[0]
            out[at] = f"{plus}{src}:{BRANCH}"
    return replace(cmd, words=tuple(_lease_to_branch(out, default))) if hit else None


COPIES = frozenset({"cp", "mv", "rsync"})
CP_VALUE_OPTIONS = frozenset({"-S", "--suffix"})
RSYNC_VALUE_OPTIONS = frozenset(
    {"-e", "--rsh", "-f", "--filter", "--exclude", "--include", "--exclude-from", "--include-from"}
    | {"--files-from", "--rsync-path", "-B", "--block-size", "-T", "--temp-dir", "--partial-dir"}
    | {"--backup-dir", "--compare-dest", "--copy-dest", "--link-dest", "--timeout", "--contimeout", "--port"}
    | {"--bwlimit", "-M", "--remote-option", "--info", "--debug", "--max-size", "--min-size", "--suffix"}
    | {"--password-file", "--out-format", "--log-file", "--log-file-format", "--sockopts", "--iconv"}
    | {"--chmod", "--chown", "--usermap", "--groupmap", "--checksum-choice", "--compress-choice"}
    | {"--compress-level", "--skip-compress", "--protocol", "--modify-window", "--max-delete", "--outbuf"}
    | {"--stop-after", "--stop-at", "--max-alloc", "--address", "--write-batch", "--only-write-batch"}
    | {"--read-batch", "--early-input"}
)
RSYNC_VALUE_SHORTS = "efBTM"


def _copy_args(cmd: Simple) -> tuple[list[str], str | None, list[int]]:
    """A cp, mv, or rsync's sources, its destination, and the sources' indexes in the words"""
    rsync = cmd.program == "rsync"
    values = RSYNC_VALUE_OPTIONS if rsync else CP_VALUE_OPTIONS
    shorts = RSYNC_VALUE_SHORTS if rsync else "St"
    target: str | None = None
    at: list[int] = []
    words = cmd.words
    options_end = False
    i = 1
    while i < len(words):
        word = words[i]
        long, eq, attached = word.partition("=")
        if options_end or not word.startswith("-") or word == "-":
            at.append(i)
        elif word == "--":
            options_end = True
        elif not rsync and word in ("-t", "--target-directory"):
            target = words[i + 1] if i + 1 < len(words) else None
            i += 1
        elif not rsync and eq and long == "--target-directory":
            target = attached
        elif word in values:
            i += 1
        elif re.fullmatch(r"-[A-Za-z]+", word):
            letters = word[1:]
            cut = next((k for k, ch in enumerate(letters) if ch in shorts), len(letters))
            if cut < len(letters):
                value = letters[cut + 1 :] or (words[i + 1] if i + 1 < len(words) else "")
                if letters[cut] == "t" and not rsync:
                    target = value
                if not letters[cut + 1 :]:
                    i += 1
        i += 1
    if target is None and at:
        target, at = words[at[-1]], at[:-1]
    return [words[k] for k in at], target, at


def _remote(path: str) -> bool:
    """rsync's host:path, user@host:path, or rsync://"""
    head = path.split("/", 1)[0]
    return "://" in path or (":" in head and not path.startswith(("./", "/")))


def _local(path: str, cwd: Path) -> Path:
    return Path(os.path.realpath(os.path.join(cwd, os.path.expandvars(os.path.expanduser(path)))))


def _glob_regex(glob: str) -> re.Pattern[str]:
    """A [hooks] private glob, relative to the repo root: ** crosses folders, * and ? don't, and
    a glob ending in /** matches its folder too"""
    out: list[str] = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    pattern = "".join(out)
    if glob.endswith("/**"):
        pattern = f"{pattern[: -len('/.*')]}(?:/.*)?"
    return re.compile(pattern)


WILDCARDS = "*?["


def _may_hold(parts: Sequence[str], glob: str, folder: bool) -> bool:
    """A source at parts may be, or hold, a path matching glob: compared folder by folder, a
    source's own shell wildcard matches any name (the shell expands it, the hook doesn't), a
    glob's ** matches whatever is below, and a folder holds what the glob names deeper"""
    segments = glob.strip("/").split("/")
    wild = False
    for k, part in enumerate(parts):
        if k >= len(segments):
            return False
        if "**" in segments[k]:
            return folder or wild or any(c in part for c in WILDCARDS)
        if any(c in part for c in WILDCARDS):
            wild = True
            if not any(c in segments[k] for c in WILDCARDS) and not fnmatch.fnmatchcase(segments[k], part):
                return False
        elif not _glob_regex(segments[k]).fullmatch(part):
            return False
    return len(parts) < len(segments) and (folder or wild) or (wild and len(parts) == len(segments))


def _private(path: Path, root: Path, globs: Sequence[str]) -> bool:
    """path, inside root, matches a glob or may hold one's files; a folder holding the repo
    holds them all"""
    if path != root and path in root.parents:
        return True
    rel = path.relative_to(root)
    text = "" if rel.as_posix() == "." else rel.as_posix()
    parts = rel.parts if text else ()
    folder = os.path.isdir(path)
    return any(_glob_regex(glob.strip("/")).fullmatch(text) or _may_hold(parts, glob, folder) for glob in globs)


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _private_check(cmd: Simple, config: Config, ctx: Context) -> Simple | str | None:
    """A cp, mv, or rsync of a [hooks] private path to a destination outside the repo; instead,
    the same copy without the private sources, or, when every source is private, to leave them"""
    if not config.private or cmd.program not in COPIES:
        return None
    root_at = repo_root(cmd.cwd)
    if root_at is None:
        return None
    root = Path(os.path.realpath(root_at))
    sources, target, at = _copy_args(cmd)
    if target is None or not sources:
        return None
    rsync = cmd.program == "rsync"
    if not (rsync and _remote(target)) and _inside(_local(target, cmd.cwd), root):
        return None
    leaks: set[int] = set()
    for k, source in zip(at, sources, strict=True):
        if rsync and _remote(source):
            continue
        path = _local(source, cmd.cwd)
        if (_inside(path, root) or path in root.parents) and _private(path, root, config.private):
            leaks.add(k)
    if not leaks:
        return None
    if len(leaks) == len(sources):  # nothing is left to copy: no command to run instead
        return f"leave {shlex.join(cmd.words[k] for k in sorted(leaks))} in the repo"
    return replace(cmd, words=tuple(word for k, word in enumerate(cmd.words) if k not in leaks))


TOKEN_VARIABLES = frozenset({"GH_TOKEN", "GITHUB_TOKEN"})


def _app_guards(cmd: Simple) -> bool:
    call = gh_call(cmd)
    return call is not None and not call.shipmill and is_gh_write(call.args(cmd))


def _app_check(cmd: Simple, config: Config, ctx: Context) -> Simple | None:
    """A gh write while app_id is set and the App is available to the session (spec 033);
    where it isn't, the person's own writes are theirs, and nothing is refused"""
    if config.app_id is None or not _app_guards(cmd) or not app_available(config.app_id, ctx.env):
        return None
    call = gh_call(cmd)
    assert call is not None
    kept = tuple(a for a in cmd.assignments if a.partition("=")[0] not in TOKEN_VARIABLES)
    return Simple(kept, (*shipmill(ctx.plugin), "gh", *call.args(cmd)), cmd.cwd)


# A session shipmill gate starts headless carries this in its --settings env (D-82); read from
# the hook's own environment only, never from a command's NAME=value words
GATE_SESSION = "SHIPMILL_GATE"


def gate_session(env: Mapping[str, str]) -> bool:
    return env.get(GATE_SESSION) == "1"


# What a gate session's `uv run` may start (D-82), besides [hooks] uv_run, the checkout's
# [project.scripts], and a path to a .py file
UV_RUN_PROGRAMS = frozenset({"python", "python3", "pytest", "ruff", "mypy"})
# uv's options, global and `uv run`'s, as uv 0.9 documents them: a flag, or one that takes the
# next word (or its own `=value`) as its value. An option not listed is refused, never guessed at,
# since a value option read as a flag would make its value the program
UV_FLAGS = frozenset(
    {"--quiet", "--verbose", "--native-tls", "--offline", "--no-cache", "--no-progress", "--no-config"}
    | {"--no-python-downloads", "--managed-python", "--no-managed-python", "--preview", "--no-preview"}
    | {"--show-settings", "--help", "--version", "--no-project", "--locked", "--frozen", "--no-sync"}
    | {"--isolated", "--active", "--no-active", "--all-extras", "--all-groups", "--no-dev", "--dev"}
    | {"--only-dev", "--no-default-groups", "--all-packages", "--no-editable", "--exact", "--no-env-file"}
    | {"--upgrade", "--reinstall", "--refresh", "--no-build-isolation", "--no-build", "--no-binary"}
    | {"--no-sources", "--compile-bytecode", "--no-index", "--script", "--gui-script", "--module"}
    | {"--system-certs"}
)
UV_VALUE_OPTIONS = frozenset(
    {"--cache-dir", "--color", "--config-file", "--directory", "--project", "--allow-insecure-host"}
    | {"--python-preference", "--extra", "--no-extra", "--group", "--no-group", "--only-group", "--with"}
    | {"--with-editable", "--with-requirements", "--env-file", "--package", "--python", "--index"}
    | {"--default-index", "--index-url", "--extra-index-url", "--find-links", "--index-strategy"}
    | {"--keyring-provider", "--resolution", "--prerelease", "--fork-strategy", "--exclude-newer"}
    | {"--exclude-newer-package", "--no-binary-package", "--no-build-package", "--reinstall-package"}
    | {"--refresh-package", "--upgrade-package", "--link-mode", "--config-setting", "--config-settings-package"}
    | {"--no-build-isolation-package", "--python-platform", "--no-editable-package", "--upgrade-group"}
    | {"--prerelease-package", "--no-sources-package"}
)
UV_SHORT_FLAGS = "qvnUsmhV"  # -q, -v, -n, -U, -s, -m, -h, -V; bundled as in -qq
UV_SHORT_VALUES = "pifPCw"  # -p, -i, -f, -P, -C, -w: the rest of the word, or the next word, is the value


def _uv_option(words: Sequence[str], i: int) -> int | None:
    """The index past the option at words[i] and its value; None when the hook doesn't know it"""
    word = words[i]
    name, eq, _ = word.partition("=")
    if word.startswith("--"):
        if eq:
            return i + 1 if name in UV_VALUE_OPTIONS else None
        if word in UV_FLAGS:
            return i + 1
        return i + 2 if word in UV_VALUE_OPTIONS else None
    letters = word[1:]
    for k, ch in enumerate(letters):
        if ch in UV_SHORT_VALUES:
            return i + 1 if letters[k + 1 :] else i + 2
        if ch not in UV_SHORT_FLAGS:
            return None
    return i + 1


def _is_option(word: str) -> bool:
    return word.startswith("-") and word != "-"


@dataclass(frozen=True)
class UvRun:
    """What a `uv run` starts: its program, None when it names none (uv run --help); or the
    first option the hook doesn't know"""

    program: str | None
    unknown: str | None


def uv_run(cmd: Simple) -> UvRun | None:
    """The `uv run` cmd is, with uv's options before the program skipped; None for any other
    uv command (uv sync, uv lock, uv pip) or another program"""
    if cmd.program != "uv":
        return None
    words = cmd.words
    unknown: str | None = None
    i = 1
    while i < len(words) and _is_option(words[i]):
        after = _uv_option(words, i)
        unknown = unknown or (words[i] if after is None else None)
        i = i + 1 if after is None else after
    if unknown is not None:  # its value may be the word read as the subcommand: refused wherever run follows
        return UvRun(None, unknown) if "run" in words[i:] else None
    if i >= len(words) or words[i] != "run":
        return None
    i += 1
    while i < len(words) and _is_option(words[i]):
        if words[i] == "--":
            i += 1
            break
        after = _uv_option(words, i)
        if after is None:
            return UvRun(None, words[i])
        i = after
    return UvRun(words[i] if i < len(words) else None, None)


UV_RUN_INSTEAD = (
    "run the program itself when the allowlist has it; otherwise stop, as for any denied tool call:"
    " the needs-decision protocol asks the maintainer, who may add the program to [hooks] uv_run in"
    f" {CONFIG} through a pull request"
)


def _uv_run_check(cmd: Simple, config: Config, ctx: Context) -> str | None:
    """D-82: in a gate session, a uv run of anything but python, pytest, ruff, mypy, a [hooks]
    uv_run program, a path to a .py file, or the checkout's [project.scripts] entry; a NAME=value
    word where the program goes is refused too. pyproject.toml is read only when the program is
    none of the others"""
    found = uv_run(cmd)
    if found is None:
        return None
    program = found.program
    if found.unknown is not None or program is None:
        return None if found.unknown is None else UV_RUN_INSTEAD
    if ASSIGNMENT.match(program):
        return UV_RUN_INSTEAD
    if program in UV_RUN_PROGRAMS or program in config.uv_run or program.endswith(".py"):
        return None
    root = repo_root(cmd.cwd)
    if "/" in program or root is None:
        return UV_RUN_INSTEAD
    scripts = ctx.configs.scripts(root)
    if isinstance(scripts, Broken):
        return f"fix {PYPROJECT} ({scripts.message}), then run: {cmd.text()}"
    return None if program in scripts else UV_RUN_INSTEAD


# In order: a refusal names the first rule that refuses, and its Instead line takes every rule's fix
RULES = (
    Rule(
        "rebase-merge",
        "land with a squash, or a merge commit for a stack's base; never rebase-merge",
        "D-96",
        _merge_guards("rebase"),
        _rebase_check,
    ),
    # after rebase-merge, whose fix under "merge" is --merge, which this rule then passes
    Rule(
        "merge-method",
        "merge-method",
        '[agents] merge = "merge", D-96',
        _merge_guards("squash"),
        _method_check,
    ),
    # force-push before default-branch-push: a force push to main names force-push, which has
    # no switch (S-026-6, the maintainer's answer on #470)
    Rule(
        "force-push",
        f"force-push only with a lease pinned to a commit, --force-with-lease=<ref>:{SHA}, where {SHA}"
        " is the remote branch's commit you last fetched (git rev-parse origin/<ref>)",
        "D-36",
        is_push,
        _force_check,
    ),
    Rule(
        "default-branch-push",
        "work lands on the default branch through a pull request; push a work branch and open one",
        "D-36",
        is_push,
        _default_check,
    ),
    Rule(
        "app-writes",
        "with [agents] app_id set and the App available here (its key on this host, or SHIPMILL_APP_KEY),"
        " every GitHub write goes as the App through shipmill gh, never plain gh or an inline GH_TOKEN",
        "D-14",
        _app_guards,
        _app_check,
    ),
    Rule(
        "private-paths",
        "a file matching a [hooks] private glob never leaves the repo",
        "D-36",
        lambda cmd: cmd.program in COPIES,
        _private_check,
    ),
    Rule(
        "uv-run",
        "in a headless session shipmill gate starts, uv run starts only python, pytest, ruff, mypy, a [project.scripts]"
        " entry, a .py file, or a [hooks] uv_run program; never env, sh, another program, or a NAME=value word",
        "D-82",
        lambda cmd: uv_run(cmd) is not None,
        _uv_run_check,
        gate=True,
    ),
)


@dataclass(frozen=True)
class Refusal:
    rule: str
    command: str
    text: str
    source: str
    instead: str

    def lines(self) -> list[str]:
        def one(line: str) -> str:
            return line.replace("\r", "\\r").replace("\n", "\\n")

        return [
            f"shipmill hook {self.rule}: {one(self.command)[:CUT]}",
            f"Rule: {one(self.text)} ({self.source})",
            f"Instead: {one(self.instead)}",
        ]


def judge(cmd: Simple, ctx: Context) -> Refusal | None:
    rules = [rule for rule in RULES if rule.guards(cmd) and (not rule.gate or gate_session(ctx.env))]
    if not rules:
        return None
    git = git_call(cmd)
    root = repo_root(git.where if git is not None else cmd.cwd)
    config = None if root is None else ctx.configs.at(root)
    if config is None:
        return None
    if isinstance(config, Broken):
        fix = f"fix {CONFIG}, then run: {cmd.text()}"
        return Refusal("config", cmd.text(), config.message, str(CONFIG), fix)
    first: Rule | None = None
    instead: Simple | str = cmd
    for rule in rules:
        if isinstance(instead, str):  # no command is left for a later rule to fix
            break
        fixed = rule.check(instead, config, ctx)
        if fixed is not None:
            first = first or rule
            instead = fixed
    if first is None:
        return None
    text = instead if isinstance(instead, str) else instead.text()
    return Refusal(first.name, cmd.text(), first.text, first.source, text)


# --- The modes -------------------------------------------------------------------------------


def pre(hook: HookInput, stderr: TextIO, ctx: Context) -> int:
    if hook.tool != "Bash":
        return 0
    command = hook.text("command")
    try:
        found = commands(command, hook.cwd)
    except ValueError:  # shlex can't split it: allowed (D-16)
        return 0
    for cmd in found:
        refusal = judge(cmd, ctx)
        if refusal is not None:
            stderr.write("".join(f"{line}\n" for line in refusal.lines()))
            return 2
    return 0


DIRECTION = "docs/product.md"
DIRECTION_DIR = "docs/product/"
RUBRIC = "REVIEW.md"


def check_for(path: Path) -> tuple[Path, str] | None:
    """The repo root and the check (product or review) an edit of path calls for; no subprocess"""
    root = repo_root(path.parent)
    if root is None:
        return None
    rel = path.relative_to(root).as_posix()
    if rel == DIRECTION or rel.startswith(DIRECTION_DIR):
        return root, "product"
    if path.name == RUBRIC:
        return root, "review"
    return None


def post(hook: HookInput, stderr: TextIO, ctx: Context) -> int:
    """After an Edit, Write, or MultiEdit of the direction or a REVIEW.md in a repo with
    [agents]: its check exiting 1 gives exit 2 with the check's output, so the model fixes the
    line; a check exiting 2, or one that can't start, gives exit 1, a non-blocking error"""
    if hook.tool not in EDITS:
        return 0
    path = Path(os.path.normpath(os.path.join(hook.cwd, hook.text("file_path"))))
    found = check_for(path)
    if found is None:
        return 0
    root, check = found
    config = ctx.configs.at(root)
    if config is None:
        return 0
    if isinstance(config, Broken):
        stderr.write(f"shipmill hook: {check} check didn't run: {config.message} ({CONFIG})\n")
        return 1
    command = (*shipmill(ctx.plugin), check, "check", "--repo", str(root))
    try:
        result = ctx.runner(command, root)
    except OSError as exc:
        stderr.write(f"shipmill hook: {shlex.join(command)} didn't start: {exc}\n")
        return 1
    if result.returncode == 0:
        return 0
    output = f"{result.stdout}{result.stderr}"
    stderr.write(output if not output or output.endswith("\n") else f"{output}\n")
    # A check that fails prints a line per problem to stdout; uvx that can't fetch shipmill
    # (offline) and a traceback exit 1 with stdout empty, so they didn't run, not a finding
    if result.returncode == 1 and result.stdout.strip():
        return 2
    stderr.write(f"shipmill hook: {shlex.join(command)} exited {result.returncode}\n")
    return 1


# --- The Stop hook (spec 062) ----------------------------------------------------------------

MAINTAINER = "SHIPMILL_MAINTAINER"  # the login the headless paragraph names, set by the gate
SESSION_ID = re.compile(r"[A-Za-z0-9-]+")
LOGIN = re.compile(r"[A-Za-z0-9-]+")
# A line that starts, past this markup, with one of ADDRESSES addresses the maintainer
ADDRESSES = (
    "For you",
    "For the maintainer",
    "For @",
    "Decision needed",
    "Needs your decision",
    "Action needed",
    "Your turn",
)
LINE_MARKUP = re.compile(r"^(?:[\s#>*_-]|\d+\.)*")
NEEDS_DECISION = "needs-decision"
RECORD = "shipmill-stop-{}"  # the refusal record, in the system's temporary directory
STOP_REFUSAL = Refusal(
    "request-on-github",
    "your final message asks @{login} for something, and this session filed no issue and labelled nothing"
    " needs-decision",
    "a headless session's request to the maintainer is on GitHub before it ends",
    "needs-decision.md, Gate sessions",
    "post each request as a needs-decision question on its item, or file an issue for one with no item;"
    " if each is already on GitHub, end with a line naming it as owner/repo#N. You can end after this.",
)


class Unreadable(ValueError):
    """What the Stop hook can't read: exit 1, and the session ends unchecked"""


@dataclass(frozen=True)
class StopInput:
    session_id: object
    transcript_path: object
    cwd: Path
    active: bool  # stop_hook_active: the session already continues after a refusal
    last_message: str | None  # last_assistant_message, when the input carries it as a string


def parse_stop(data: Mapping[str, object]) -> StopInput:
    cwd = data.get("cwd")
    if cwd is not None and (not isinstance(cwd, str) or not os.path.isabs(cwd)):
        raise BadInput("the input's cwd is not an absolute path")
    active = data.get("stop_hook_active", False)
    if not isinstance(active, bool):
        raise BadInput("the input's stop_hook_active is not true or false")
    last = data.get("last_assistant_message")
    return StopInput(
        data.get("session_id"),
        data.get("transcript_path"),
        Path(cwd) if cwd else Path.cwd(),
        active,
        last if isinstance(last, str) else None,
    )


def addresses(text: str, login: str) -> bool:
    """The final text names @<login>, in any case and not followed by another login character,
    or starts a line, past the listed markup, with one of ADDRESSES as whole words: an email
    address such as dev@<login>.io names no login, and a line starting For your starts no phrase"""
    if re.search(rf"(?<![A-Za-z0-9_.+-])@{re.escape(login)}(?![A-Za-z0-9-])", text, re.IGNORECASE):
        return True
    phrases = [phrase.casefold() for phrase in ADDRESSES]

    def starts(line: str, phrase: str) -> bool:
        rest = line[len(phrase) :]
        return line.startswith(phrase) and (phrase.endswith("@") or not rest[:1].isalnum())

    lines = [LINE_MARKUP.sub("", line).casefold() for line in text.splitlines()]
    return any(starts(line, phrase) for line in lines for phrase in phrases)


def read_transcript(path: object) -> list[Mapping[str, object]]:
    """The transcript's entries; Unreadable when it is missing or a line isn't a JSON object"""
    if not isinstance(path, str) or not path:
        raise Unreadable("the input has no transcript_path")
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Unreadable(f"the transcript can't be read: {exc}") from None
    entries: list[Mapping[str, object]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Unreadable(f"the transcript's line {number} is not JSON: {exc}") from None
        if not isinstance(entry, dict):
            raise Unreadable(f"the transcript's line {number} is not a JSON object")
        entries.append(entry)
    return entries


def _blocks(entry: Mapping[str, object], role: str) -> list[Mapping[str, object]]:
    """The content blocks of a main-session entry of role; none for a subagent's (sidechain)"""
    message = entry.get("message")
    if entry.get("type") != role or entry.get("isSidechain") is True or not isinstance(message, dict):
        return []
    content = message.get("content")
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def final_text(entries: Sequence[Mapping[str, object]]) -> str:
    """The text blocks of the last assistant entry; Claude Code writes one entry per block, so
    the entries before it that share its message id are the same message"""
    found = [entry for entry in entries if _blocks(entry, "assistant")]
    if not found:
        raise Unreadable("the transcript has no assistant entry")
    last = found[-1]
    message = last.get("message")
    last_id = message.get("id") if isinstance(message, dict) else None
    same: list[Mapping[str, object]] = [last]
    if last_id is not None:
        for entry in reversed(found[:-1]):
            other = entry.get("message")
            if not isinstance(other, dict) or other.get("id") != last_id:
                break
            same.insert(0, entry)
    texts: list[str] = []
    for entry in same:
        for block in _blocks(entry, "assistant"):
            value = block.get("text")
            if block.get("type") == "text" and isinstance(value, str):
                texts.append(value)
    text = "\n".join(texts)
    if not text.strip():
        raise Unreadable("the transcript's last assistant entry holds no text")
    return text


def _labels(args: Sequence[str]) -> list[str]:
    """The labels each --add-label of gh's arguments names, a comma-separated list split"""
    found: list[str] = []
    for i, word in enumerate(args):
        if word == "--add-label" and i + 1 < len(args):
            found += args[i + 1].split(",")
        elif word.startswith("--add-label="):
            found += word.partition("=")[2].split(",")
    return [label.strip() for label in found]


def is_request(command: str, cwd: Path) -> bool:
    """A gh write, plain or through shipmill gh, that puts a request on GitHub: an issue created,
    or an issue or pull request labelled needs-decision"""
    try:
        found = commands(command, cwd)
    except ValueError:  # shlex can't split it: no request the hook can read
        return False
    for cmd in found:
        call = gh_call(cmd)
        if call is None:
            continue
        args = call.args(cmd)
        group, sub = gh_command(args)
        if (group, sub) in (("issue", "create"), ("issue", "new")):  # new is gh's alias of create
            return True
        if (group, sub) in (("issue", "edit"), ("pr", "edit")) and NEEDS_DECISION in _labels(args):
            return True
    return False


def requested(entries: Sequence[Mapping[str, object]], cwd: Path) -> bool:
    """The session's transcript holds a request on GitHub whose tool result isn't an error"""
    calls: dict[str, str] = {}  # a Bash tool_use's id: its command
    succeeded: set[str] = set()
    for entry in entries:
        for block in _blocks(entry, "assistant"):
            tool_input = block.get("input")
            if block.get("type") != "tool_use" or block.get("name") != "Bash" or not isinstance(tool_input, dict):
                continue
            command = tool_input.get("command")
            if isinstance(command, str):
                calls[str(block.get("id"))] = command
        for block in _blocks(entry, "user"):
            if block.get("type") == "tool_result" and block.get("is_error") is not True:
                succeeded.add(str(block.get("tool_use_id")))
    return any(is_request(command, cwd) for use, command in calls.items() if use in succeeded)


def record(folder: Path, session_id: str) -> bool:
    """Create the refusal record exclusively; False when it exists or can't be created"""
    try:
        fd = os.open(folder / RECORD.format(session_id), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError:
        return False
    os.close(fd)
    return True


def stop(data: Mapping[str, object], stderr: TextIO, ctx: Context, temp: Path) -> int:
    """Spec 062: in a headless gate session of a repo with [agents], refuse once a stop whose
    final text addresses the maintainer while the session put no request on GitHub"""
    if data["hook_event_name"] != "Stop" or not gate_session(ctx.env):
        return 0
    hook = parse_stop(data)
    root = repo_root(hook.cwd)
    config = None if root is None else ctx.configs.at(root)
    if config is None or hook.active:
        return 0
    if isinstance(config, Broken):
        raise Unreadable(f"{config.message} ({CONFIG})")
    session = hook.session_id
    if not isinstance(session, str) or not SESSION_ID.fullmatch(session):
        raise Unreadable("the input's session_id is not letters, digits, and dashes")
    login = ctx.env.get(MAINTAINER, "")
    if not LOGIN.fullmatch(login):
        raise Unreadable(f"{MAINTAINER} is not set to a GitHub login")
    entries: list[Mapping[str, object]] | None = None
    text = hook.last_message
    if text is None:
        entries = read_transcript(hook.transcript_path)
        text = final_text(entries)
    if not addresses(text, login):
        return 0
    if entries is None:
        entries = read_transcript(hook.transcript_path)
    if requested(entries, hook.cwd) or not record(temp, session):
        return 0
    refusal = replace(STOP_REFUSAL, command=STOP_REFUSAL.command.format(login=login))
    stderr.write("".join(f"{line}\n" for line in refusal.lines()))
    return 2


def stop_input(text: str) -> Mapping[str, object]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BadInput(f"stdin is not JSON: {exc}") from None
    if not isinstance(data, dict):
        raise BadInput("stdin is not a JSON object")
    if not isinstance(data.get("hook_event_name"), str):
        raise BadInput("the input has no hook_event_name string")
    return data


def main(
    argv: Sequence[str],
    stdin: TextIO,
    stderr: TextIO,
    runner: Runner = run,
    read_config: ReadConfig = read_text,
    plugin: Path = PLUGIN_JSON,
    env: Mapping[str, str] | None = None,
    temp: Path | None = None,
) -> int:
    """env is the hook's own environment, os.environ unless a test passes one (spec 033); temp
    is where the Stop hook keeps its refusal records, the system's temporary directory unless a
    test passes one (spec 062)"""
    if len(argv) != 1 or argv[0] not in (*EVENTS, "stop"):
        stderr.write("usage: delivery.py pre|post|stop, with Claude Code's hook input on stdin (specs 026, 062)\n")
        return 1
    if argv[0] == "stop":  # exits 0, 1, or its own refusal's 2; never 2 for what it can't read
        try:
            ctx = Context(runner, Configs(read_config), plugin, os.environ if env is None else env)
            return stop(stop_input(stdin.read()), stderr, ctx, Path(tempfile.gettempdir()) if temp is None else temp)
        except (BadInput, Unreadable) as exc:
            one = str(exc).replace("\r", "\\r").replace("\n", "\\n")
            stderr.write(f"shipmill hook: {one}; this session ends unchecked\n")
            return 1
    try:
        hook = parse_input(stdin.read())
        if hook.event != EVENTS[argv[0]]:
            raise BadInput(f"`{argv[0]}` reads a {EVENTS[argv[0]]} input, got {hook.event}")
        ctx = Context(runner, Configs(read_config), plugin, os.environ if env is None else env)
        if argv[0] == "post":
            return post(hook, stderr, ctx)
        return pre(hook, stderr, ctx)
    except BadInput as exc:
        stderr.write(f"shipmill hook: {exc}\n")
        return 1
    except PluginError as exc:  # read only when the CLI runs or a refusal names it (spec 031)
        stderr.write(f"shipmill hook: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8"), sys.stderr))
