"""Spec 080: what the checks gating a merge prove. This part sorts a workflow job's commands
(S-080-3 to S-080-7): each `run:` step is split into parts, each part past its leading
assignments and wrappers is looked up by its program in a table of kinds, and a check's kinds
are those of its jobs' parts. A program the table doesn't hold is `unknown`, never guessed.
"""

import functools
import json
import re
import shlex
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from shipmill.errors import ReleaseError
from shipmill.workflows import Job, Step, steps


class Kind(StrEnum):
    """What a command proves, or that it builds, or that nothing tells"""

    TESTS = "tests"
    TYPE_CHECK = "type check"
    LINT = "lint"
    IMPORT_BOUNDARIES = "import boundaries"
    BUILD = "build"
    UNKNOWN = "unknown"


PROVING = (Kind.TESTS, Kind.TYPE_CHECK, Kind.LINT, Kind.IMPORT_BOUNDARIES)

# A program read with any arguments
PROGRAMS: Mapping[str, Kind] = {
    **dict.fromkeys(
        ("pytest", "unittest", "jest", "vitest", "mocha", "rspec", "phpunit", "ctest"),
        Kind.TESTS,
    ),
    **dict.fromkeys(("mypy", "pyright", "basedpyright", "pyre", "pytype", "tsc", "vue-tsc", "flow"), Kind.TYPE_CHECK),
    **dict.fromkeys(
        ("ruff", "flake8", "pylint", "eslint", "biome", "oxlint", "prettier", "stylelint", "golangci-lint")
        + ("staticcheck", "rubocop", "shellcheck", "actionlint", "hadolint", "yamllint", "markdownlint")
        + ("ktlint", "swiftlint", "clang-tidy"),
        Kind.LINT,
    ),
    **dict.fromkeys(("lint-imports", "depcruise", "dependency-cruiser"), Kind.IMPORT_BOUNDARIES),
    "webpack": Kind.BUILD,
}

# A program read with its first argument
SUBCOMMANDS: Mapping[tuple[str, str], Kind] = {
    **dict.fromkeys(
        (("go", "test"), ("cargo", "test"), ("cargo", "nextest"), ("playwright", "test"), ("cypress", "run"))
        + (("dotnet", "test"), ("swift", "test"), ("mix", "test"), ("deno", "test"), ("mvn", "test"))
        + (("mvn", "verify"), ("gradle", "test"), ("gradle", "check")),
        Kind.TESTS,
    ),
    **dict.fromkeys((("ty", "check"), ("cargo", "check"), ("srb", "tc"), ("steep", "check")), Kind.TYPE_CHECK),
    **dict.fromkeys(
        (("go", "vet"), ("cargo", "clippy"), ("cargo", "fmt"), ("pre-commit", "run")),
        Kind.LINT,
    ),
    ("tach", "check"): Kind.IMPORT_BOUNDARIES,
    **dict.fromkeys(
        (("uv", "build"), ("hatch", "build"), ("poetry", "build"), ("pip", "wheel"), ("cargo", "build"))
        + (("go", "build"), ("docker", "build"), ("docker", "buildx"), ("mvn", "compile"), ("mvn", "package"))
        + (("gradle", "assemble"), ("dotnet", "build"), ("next", "build"), ("vite", "build")),
        Kind.BUILD,
    ),
}

MODULES: Mapping[str, Kind] = {"build": Kind.BUILD}  # a module read only after `python -m`
ALIASES: Mapping[str, str] = {"./gradlew": "gradle", "./mvnw": "mvn"}
PYTHONS = ("python", "python3")
PACKAGE_MANAGERS = ("npm", "pnpm", "yarn", "bun")

# The wrappers skipped before a part's program, each with its options that take the next word
_UV = frozenset({"--with", "--with-editable", "--with-requirements", "--python", "-p", "--from", "--index"})
_UV_RUN = _UV | {"--package", "--extra", "--group", "--only-group", "--no-group", "--env-file", "--directory"}
WRAPPERS: Mapping[tuple[str, ...], frozenset[str]] = {
    ("uv", "run"): _UV_RUN | {"--project", "--default-index", "--extra-index-url", "--index-url", "--config-file"},
    ("uvx",): _UV,
    ("npx",): frozenset({"-p", "--package", "-w", "--workspace"}),
    ("bunx",): frozenset({"-p", "--package"}),
    ("pnpm", "exec"): frozenset({"-F", "--filter", "-C", "--dir"}),
    ("pnpm", "dlx"): frozenset({"--package"}),
    ("yarn", "dlx"): frozenset({"-p", "--package"}),
    ("poetry", "run"): frozenset({"-C", "--directory", "-P", "--project"}),
    ("pdm", "run"): frozenset({"-p", "--project"}),
    ("hatch", "run"): frozenset(),
    ("pipenv", "run"): frozenset(),
    ("bundle", "exec"): frozenset({"--gemfile"}),
    ("sudo",): frozenset({"-u", "--user", "-g", "--group", "-C", "-D", "-h", "-p", "-r", "-t", "-T", "-U"}),
    ("time",): frozenset({"-f", "--format", "-o", "--output"}),
    ("timeout",): frozenset({"-k", "--kill-after", "-s", "--signal"}),  # then its duration
}

# The shell's own words that lead a command, and those that make a whole part, which runs nothing
_LEADING = frozenset({"then", "else", "do", "{", "("})
_CLOSING = frozenset({"then", "else", "fi", "do", "done", "esac", "}", ")"})
# A condition's or a negated command's exit never fails the step, so the part stays `unknown`
_CONDITION = frozenset({"if", "elif", "while", "until", "!"})
_SHELL = _LEADING | _CLOSING | _CONDITION
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_HEREDOC = re.compile(r"<<-?[ \t]*(?P<quote>['\"]?)(?P<word>[\w.-]+)(?P=quote)")
_NEWLINES = re.compile(r"[ \t]*\n\s*")
_EXPRESSION = "${{"
_EXPRESSIONS = re.compile(r"\$\{\{.*?\}\}")


@dataclass(frozen=True, slots=True)
class Command:
    """A part of a job's `run:` steps and its kind; a package manager's script reads as
    `<part>: <a part of the script's command>`"""

    text: str
    kind: Kind


@dataclass(frozen=True, slots=True)
class Reading:
    """A job's commands, in its steps' order, and the actions its `uses:` steps name, which are
    never read"""

    commands: tuple[Command, ...]
    actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Coverage:
    """A check's kinds (S-080-7): the proving ones its parts have, in PROVING's order; else
    whether a part builds"""

    kinds: tuple[Kind, ...]
    build: bool

    @property
    def proves(self) -> bool:
        return bool(self.kinds)

    def __str__(self) -> str:
        if self.kinds:
            return ", ".join(self.kinds)
        return "build only" if self.build else str(Kind.UNKNOWN)


def coverage(commands: Iterable[Command]) -> Coverage:
    """The kinds of a check whose jobs run the commands"""
    found = {command.kind for command in commands}
    return Coverage(tuple(k for k in PROVING if k in found), Kind.BUILD in found)


# --- The parts of a script ----------------------------------------------------------------------


def parts(script: str) -> list[str]:
    """The parts of a `run:` script: its commands split on newlines, `&&`, `||`, `;`, and `|`
    outside quotes, substitutions, and backticks, without comments, blank lines, or the lines of a
    heredoc; a line ending in `\\` goes on to the next one, and a part's newlines inside quotes
    read as spaces"""
    found: list[str] = []
    buf: list[str] = []
    heredocs: list[str] = []
    quote = ""
    depth = 0  # how deep in $( ... ) the scan is
    tick = False
    i = 0

    def end() -> None:
        text = _NEWLINES.sub(" ", "".join(buf)).strip()
        if text:
            found.append(text)
        buf.clear()

    while i < len(script):
        ch = script[i]
        if ch == "\\" and quote != "'":
            if not script.startswith("\\\n", i):
                buf.append(script[i : i + 2])
                i += 2
                continue
            i += 2
            while i < len(script) and script[i] in " \t":  # the next line's indentation
                i += 1
            if buf and not buf[-1][-1:].isspace():
                buf.append(" ")
            continue
        if quote:
            buf.append(ch)
            quote = "" if ch == quote else quote
            i += 1
            continue
        if ch in "'\"":
            quote = ch
        elif script.startswith(("$(", "<(", ">("), i):  # a command or process substitution
            depth += 1
            buf.append(script[i : i + 2])
            i += 2
            continue
        elif ch == "`":
            tick = not tick
        elif depth and ch == "(":
            depth += 1
        elif depth and ch == ")":
            depth -= 1
        elif depth or tick:
            pass
        elif ch == "#" and (not buf or buf[-1][-1:].isspace()):
            while i < len(script) and script[i] != "\n":
                i += 1
            continue
        elif ch == "\n":
            end()
            i = _past_heredocs(script, i + 1, heredocs)
            heredocs.clear()
            continue
        elif script.startswith(("&&", "||"), i):
            end()
            i += 2
            continue
        elif ch in ";|":
            end()
            i += 2 if script.startswith("|&", i) else 1
            continue
        elif script.startswith("<<<", i):  # a here-string, read in its line
            buf.append("<<<")
            i += 3
            continue
        elif (doc := _HEREDOC.match(script, i)) is not None:
            heredocs.append(doc["word"])
            buf.append(doc.group(0))
            i = doc.end()
            continue
        buf.append(ch)
        i += 1
    end()
    return found


def _past_heredocs(script: str, i: int, words: Sequence[str]) -> int:
    """Where the script goes on past the bodies of the heredocs a line opened, from i"""
    for word in words:
        while i < len(script):
            nl = script.find("\n", i)
            line, i = (script[i:], len(script)) if nl < 0 else (script[i:nl], nl + 1)
            if line.strip() == word:
                break
    return i


# --- The kind of a part --------------------------------------------------------------------------


def _past_options(words: Sequence[str], valued: frozenset[str]) -> list[str]:
    """The words past the options that lead them, and the values of those in valued"""
    i = 0
    while i < len(words) and words[i].startswith("-") and words[i] != "-":
        if words[i] == "--":
            i += 1
            break
        i += 2 if words[i] in valued else 1
    return list(words[i:])


def _program(words: Sequence[str]) -> tuple[list[str], bool]:
    """The words of a part past its leading assignments, the shell's leading words, and the
    wrappers with their options; and whether the last wrapper was `python -m`"""
    rest = list(words)
    module = False
    while rest:
        head = rest[0]
        if _ASSIGNMENT.match(head) or head in _LEADING:
            rest = rest[1:]
            continue
        two = tuple(rest[:2])
        if head in PYTHONS and two[1:] == ("-m",):
            rest, module = rest[2:], True
            continue
        key = two if two in WRAPPERS else (head,) if (head,) in WRAPPERS else None
        if key is None:
            break
        rest = _past_options(rest[len(key) :], WRAPPERS[key])
        if key == ("timeout",):
            rest = rest[1:]
        module = False
    return rest, module


def _arguments(words: Sequence[str]) -> list[str]:
    """A program's arguments that aren't options"""
    return [w for w in words[1:] if not w.startswith("-")]


def lookup(words: Sequence[str], module: bool = False) -> Kind:
    """The kind of a program and its arguments, by the table; `unknown` when it holds neither"""
    if not words:
        return Kind.UNKNOWN
    program = ALIASES.get(words[0], words[0])
    if module and program in MODULES:
        return MODULES[program]
    if program in PROGRAMS:
        return PROGRAMS[program]
    args = _arguments(words)
    return SUBCOMMANDS.get((program, args[0]), Kind.UNKNOWN) if args else Kind.UNKNOWN


def _script(words: Sequence[str]) -> str | None:
    """The script a package manager's `test` or `run <script>` runs; None for anything else"""
    if not words or words[0] not in PACKAGE_MANAGERS:
        return None
    args = _arguments(words)
    if args[:1] == ["test"]:
        return "test"
    if args[:1] == ["run"] and len(args) > 1:
        return args[1]
    return None


Scripts = Mapping[str, str]  # a package.json's `scripts`


def package_scripts(root: Path, working_directory: str | None) -> Scripts | None:
    """The `scripts` of the package.json in a step's working directory (the root without one);
    None when there is no such file, or the directory is an expression. A package.json that
    isn't JSON, or whose scripts aren't strings, fails naming it"""
    if working_directory is not None and _EXPRESSION in working_directory:
        return None
    path = (root / working_directory if working_directory else root) / "package.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ReleaseError(f"{path} is not JSON ({exc}), so its scripts can't be read") from None
    if not isinstance(data, dict):
        raise ReleaseError(f"{path} is not a JSON object, so its scripts can't be read")
    scripts = data.get("scripts", {})
    if not isinstance(scripts, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in scripts.items()):
        raise ReleaseError(f"{path}: scripts is not an object of strings")
    return scripts


def _words(part: str) -> list[str] | None:
    """A part's words, each `${{ ... }}` expression one word, as GitHub fills it in before the
    shell reads the line; None when shlex can't split it"""
    try:
        return shlex.split(_EXPRESSIONS.sub("${{}}", part))
    except ValueError:
        return None


def classify(part: str, load: Callable[[], Scripts | None]) -> list[Command]:
    """A part's commands: itself with its kind, or for a package manager's script, each part of
    the script's command (S-080-5), its package.json's scripts from load, called only then; none
    for a part that is only the shell's own words. A script that is missing, or that runs another
    script, is `unknown`"""
    words = _words(part)
    if words is None:
        return [Command(part, Kind.UNKNOWN)]
    if words and all(w in _SHELL for w in words):
        return []
    rest, module = _program(words)
    name = _script(rest)
    if name is None:
        return [Command(part, lookup(rest, module))]
    scripts = load()
    command = scripts.get(name) if scripts is not None else None
    if command is None:
        return [Command(part, Kind.UNKNOWN)]
    found: list[Command] = []
    for inner in parts(command):
        inner_words = _words(inner)
        if inner_words is None:
            found.append(Command(f"{part}: {inner}", Kind.UNKNOWN))
            continue
        inner_rest, inner_module = _program(inner_words)
        nested = _script(inner_rest) is not None
        found.append(Command(f"{part}: {inner}", Kind.UNKNOWN if nested else lookup(inner_rest, inner_module)))
    return found or [Command(part, Kind.UNKNOWN)]


def _action(uses: str) -> str:
    """An action's name, without its `@ref`"""
    return uses.split("@", 1)[0]


def read_steps(found: Iterable[Step], root: Path) -> Reading:
    """The commands of the steps' `run:` scripts, each `package.json` read from root, and the
    actions of their `uses:`"""
    commands: list[Command] = []
    actions: list[str] = []
    for step in found:
        if step.uses is not None:
            actions.append(_action(step.uses))
        if step.run is None:
            continue
        load = functools.cache(functools.partial(package_scripts, root, step.working_directory))
        for part in parts(step.run):
            commands += classify(part, load)
    return Reading(tuple(commands), tuple(actions))


def read(text: str, job: Job, root: Path) -> Reading:
    """A workflow job's reading, its `package.json` files read from the checkout at root"""
    return read_steps(steps(text, job), root)
