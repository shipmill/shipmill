"""shipmill's delivery hooks for Claude Code (spec 026, D-36)

`delivery.py pre` reads a PreToolUse input for Bash and refuses a command the delivery rules
forbid, in a repo whose .github/shipmill.toml has an [agents] section: exit 2 with three lines
on stderr, the refused command, the rule, and the command to run instead. `delivery.py post`
reads a PostToolUse input for Edit, Write, and MultiEdit. Exit 0 allows; exit 1 means the
input wasn't the hook JSON. hooks/hooks.json runs it through `uv run --no-project`.

Stdlib only and Python 3.11+ (tomllib), since the plugin can't import the installed shipmill.
The hooks catch an agent's mistake: a command shlex can't split, and `bash -c`, `eval`,
`$(...)`, and here-documents, pass; the trust filter (D-16) is the control against hostile
text. No command but a `git push` may start a process, and each call reads a repo's config at
most once.
"""

from __future__ import annotations

import io
import json
import os
import re
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TextIO

CONFIG = Path(".github") / "shipmill.toml"
# Runs anywhere the hook does: the hook itself needs uv, and a headless session's allowlist
# has `Bash(uvx *)` but no bare shipmill
SHIPMILL = ("uvx", "--from", "git+https://github.com/shipmill/shipmill@v0", "shipmill")
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
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ConfigError("[hooks] is not a table")
    unknown = sorted(set(hooks) - {"default_branch", "private"})
    if unknown:
        raise ConfigError(f"[hooks] has an unknown key: {unknown[0]}")
    default_branch = hooks.get("default_branch", True)
    if not isinstance(default_branch, bool):
        raise ConfigError(f"[hooks] default_branch must be true or false, got {default_branch!r}")
    private = hooks.get("private", [])
    if not isinstance(private, list) or not all(isinstance(glob, str) and glob for glob in private):
        raise ConfigError(f"[hooks] private must be a list of globs, got {private!r}")
    return Config(app_id, default_branch, tuple(private))


@dataclass(frozen=True)
class Broken:
    message: str


@dataclass
class Configs:
    """Each repo's config, read at most once per call"""

    read: ReadConfig
    seen: dict[Path, Config | Broken | None] = field(default_factory=dict)

    def at(self, root: Path) -> Config | Broken | None:
        if root not in self.seen:
            self.seen[root] = self._load(root)
        return self.seen[root]

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


def gh_call(cmd: Simple) -> GhCall | None:
    program = cmd.program
    if program == "gh":
        return GhCall(False, 1)
    if program == "shipmill":
        start = _shipmill_gh(cmd.words, 0)
        return None if start is None else GhCall(True, start)
    if program in ("uvx", "uv"):  # uvx --from <spec> shipmill gh ...
        for at in range(1, len(cmd.words)):
            start = _shipmill_gh(cmd.words, at) if os.path.basename(cmd.words[at]) == "shipmill" else None
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


def _api_write(args: Sequence[str]) -> bool:
    """`gh api`: -X other than GET, or a field or --input without -X GET; for graphql, a query
    that holds mutation. A query read from a file (`-F query=@file`) or --input counts as a
    write, since the hook reads no file: `shipmill gh` runs a read as well"""
    method: str | None = None
    fields: list[tuple[str, str]] = []
    has_input = False
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
            fields.append((word, value))
            i += 1
        elif eq and long in ("--field", "--raw-field"):
            fields.append((long, attached))
        elif word[:2] in ("-f", "-F") and len(word) > 2:
            fields.append((word[:2], word[2:]))
        elif word == "--input" or long == "--input":
            has_input = True
            i += 0 if eq else 1
        elif word in API_VALUE_OPTIONS:
            i += 1
        elif not word.startswith("-") and endpoint is None:
            endpoint = word
        i += 1
    if endpoint == "graphql":
        queries = [(flag, v.partition("=")[2]) for flag, v in fields if v.partition("=")[0] == "query"]
        from_file = any(flag in ("-F", "--field") and q.startswith("@") for flag, q in queries)
        return has_input or from_file or any("mutation" in q for _, q in queries)
    if method is not None:
        return method.upper() != "GET"
    return bool(fields) or has_input


def is_gh_write(args: Sequence[str]) -> bool:
    group, sub = gh_command(args)
    if group == "api":
        return _api_write(args)
    return sub in GH_WRITES.get(group, frozenset())


# --- The rules -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Context:
    runner: Runner  # for the git push rules that read the remote's default branch
    configs: Configs


@dataclass(frozen=True)
class Rule:
    name: str
    text: str  # the Rule line
    source: str  # where it is written
    guards: Callable[[Simple], bool]  # the rule judges this command, so a broken config refuses it
    # the command to run instead, or what to do when no command is left; None allows
    check: Callable[[Simple, Config, Context], Simple | str | None]


def _with_args(cmd: Simple, call: GhCall, args: Sequence[str]) -> Simple:
    return replace(cmd, words=(*cmd.words[: call.start], *args))


MERGE_VALUE_OPTIONS = frozenset(
    {"-b", "--body", "-F", "--body-file", "-t", "--subject", "-A", "--author-email", "--match-head-commit"}
    | GH_VALUE_OPTIONS
)
MERGE_VALUE_SHORTS = "bFtAR"


def _merge_squash(args: Sequence[str]) -> list[str] | None:
    """gh pr merge's arguments with --squash for --rebase or -r; None when it doesn't rebase"""
    out: list[str] = []
    rebase = False
    i = 0
    while i < len(args):
        word = args[i]
        if word in ("--rebase", "--rebase=true"):
            rebase = True
        elif re.fullmatch(r"-[A-Za-z]+", word):  # -r, or bundled as in -dr
            letters = word[1:]
            cut = next((k for k, ch in enumerate(letters) if ch in MERGE_VALUE_SHORTS), len(letters))
            rebase = rebase or "r" in letters[:cut]
            kept = letters[:cut].replace("r", "") + letters[cut:]
            if kept:
                out.append(f"-{kept}")
            if cut == len(letters) - 1:  # a value option last: its value is the next word
                out.extend(args[i + 1 : i + 2])
                i += 1
        elif word in MERGE_VALUE_OPTIONS:
            out.extend(args[i : i + 2])
            i += 1
        else:
            out.append(word)
        i += 1
    return [*out, "--squash"] if rebase else None


def _rebase_guards(cmd: Simple) -> bool:
    call = gh_call(cmd)
    if call is None:
        return False
    args = call.args(cmd)
    return gh_command(args) == ("pr", "merge") or (
        gh_command(args)[0] == "api" and any("merge_method=rebase" in word for word in args)
    )


def _rebase_check(cmd: Simple, config: Config, ctx: Context) -> Simple | None:
    call = gh_call(cmd)
    if call is None:
        return None
    args = call.args(cmd)
    group, sub = gh_command(args)
    if (group, sub) == ("pr", "merge"):
        squash = _merge_squash(args)
        return None if squash is None else _with_args(cmd, call, squash)
    if group == "api" and any("merge_method=rebase" in word for word in args):
        return _with_args(cmd, call, [word.replace("merge_method=rebase", "merge_method=squash") for word in args])
    return None


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


def _default_check(cmd: Simple, config: Config, ctx: Context) -> Simple | None:
    """A push to the default branch, the target of origin/HEAD: a refspec naming it, or no
    refspec while the current branch's push target is it; instead, the same push to <branch>.
    Unknown (origin/HEAD unset, no upstream) allows; doctor reports an unset origin/HEAD"""
    call = git_call(cmd)
    if not config.default_branch or call is None or cmd.words[call.sub] != "push":
        return None
    positionals, options = _push_positionals(cmd.words, call.sub + 1)
    refspecs = positionals[1:]
    if not refspecs and options & {"--tags", "--all", "--branches", "--mirror"}:
        return None  # not the current branch's push; --all and --mirror are out of this rule
    target = _git_out(ctx, call.where, "symbolic-ref", "--quiet", ORIGIN_HEAD)
    if target is None or not target.startswith("refs/remotes/origin/"):
        return None
    default = target.removeprefix("refs/remotes/origin/")
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
        if dst == default:
            hit = True
            plus = "+" if word.startswith("+") else ""
            src = word.removeprefix("+").partition(":")[0]
            out[at] = f"{plus}{src}:{BRANCH}"
    return replace(cmd, words=tuple(out)) if hit else None


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


def _prefix(glob: str) -> tuple[str, ...]:
    """The glob's folders before its first wildcard"""
    parts = glob.strip("/").split("/")
    return tuple(next((parts[:k] for k, part in enumerate(parts) if any(c in part for c in "*?[")), parts))


def _private(rel: Path, globs: Sequence[str]) -> bool:
    """rel, relative to the repo root, matches a glob or is a folder holding one's files"""
    text = rel.as_posix()
    text = "" if text == "." else text
    parts = () if not text else rel.parts
    for glob in globs:
        if _glob_regex(glob.strip("/")).fullmatch(text):
            return True
        prefix = _prefix(glob)
        if prefix and prefix[: len(parts)] == parts:
            return True
    return False


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
        if _inside(path, root) and _private(path.relative_to(root), config.private):
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
    if config.app_id is None or not _app_guards(cmd):
        return None
    call = gh_call(cmd)
    assert call is not None
    kept = tuple(a for a in cmd.assignments if a.partition("=")[0] not in TOKEN_VARIABLES)
    return Simple(kept, (*SHIPMILL, "gh", *call.args(cmd)), cmd.cwd)


# In order: a refusal names the first rule that refuses, and its Instead line takes every rule's fix
RULES = (
    Rule(
        "rebase-merge",
        "land with a squash, or a merge commit for a stack's base; never rebase-merge",
        "D-33",
        _rebase_guards,
        _rebase_check,
    ),
    Rule(
        "default-branch-push",
        "work lands on the default branch through a pull request; push a work branch and open one",
        "D-36",
        is_push,
        _default_check,
    ),
    Rule(
        "force-push",
        f"force-push only with a lease pinned to a commit, --force-with-lease=<ref>:{SHA}, where {SHA}"
        " is the remote branch's commit you last fetched (git rev-parse origin/<ref>)",
        "D-36",
        is_push,
        _force_check,
    ),
    Rule(
        "app-writes",
        "with [agents] app_id set, every GitHub write goes as the App through shipmill gh,"
        " never plain gh or an inline GH_TOKEN",
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
    rules = [rule for rule in RULES if rule.guards(cmd)]
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


def post(hook: HookInput) -> int:
    """After an Edit, Write, or MultiEdit; no path has a check yet"""
    if hook.tool in EDITS:
        hook.text("file_path")
    return 0


def main(
    argv: Sequence[str],
    stdin: TextIO,
    stderr: TextIO,
    runner: Runner = run,
    read_config: ReadConfig = read_text,
) -> int:
    if len(argv) != 1 or argv[0] not in EVENTS:
        stderr.write("usage: delivery.py pre|post, with Claude Code's hook input on stdin (spec 026)\n")
        return 1
    try:
        hook = parse_input(stdin.read())
        if hook.event != EVENTS[argv[0]]:
            raise BadInput(f"`{argv[0]}` reads a {EVENTS[argv[0]]} input, got {hook.event}")
        if argv[0] == "post":
            return post(hook)
        return pre(hook, stderr, Context(runner, Configs(read_config)))
    except BadInput as exc:
        stderr.write(f"shipmill hook: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8"), sys.stderr))
