"""Spec 080: what the checks gating a merge prove. The first part sorts a workflow job's
commands (S-080-3 to S-080-7): each `run:` step is split into parts, each part past its leading
assignments and wrappers is looked up by its program in a table of kinds, and a check's kinds
are those of its jobs' parts. A program the table doesn't hold is `unknown`, never guessed.

The second part reads what gates a merge to the default branch (S-080-1, S-080-2, S-080-8 to
S-080-13): the contexts the rulesets and classic protection require, read through a
RulesReader, which only reads (S-080-16), each matched to the jobs of the pull-request workflows
that report it, and the reading judged at a land level.
"""

import functools
import json
import re
import shlex
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from shipmill.autonomy import Autonomy
from shipmill.errors import ReleaseError
from shipmill.landing import RulesReader
from shipmill.workflows import (
    SUFFIXES,
    WORKFLOWS_DIR,
    Job,
    Step,
    calls,
    events,
    has_matrix,
    is_workflow,
    jobs,
    reported_name,
    steps,
)


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


POSIX_SHELLS = ("bash", "sh")


def _gates(step: Step) -> bool:
    """Whether a failing part fails the step and its job: not under a `continue-on-error` that
    may be true, nor in a shell other than bash or sh (pwsh's step fails on its last command's
    exit alone, and python's script holds no shell commands)"""
    shell = step.shell.split(maxsplit=1)[0] if step.shell and step.shell.strip() else None
    return not step.continue_on_error and (shell is None or shell in POSIX_SHELLS)


def read_steps(found: Iterable[Step], root: Path) -> Reading:
    """The commands of the steps' `run:` scripts, each `package.json` read from root, and the
    actions of their `uses:`; a step whose failure fails no job gives each part `unknown`"""
    commands: list[Command] = []
    actions: list[str] = []
    for step in found:
        if step.uses is not None:
            actions.append(_action(step.uses))
        if step.run is None:
            continue
        load = functools.cache(functools.partial(package_scripts, root, step.working_directory))
        gates = _gates(step)
        for part in parts(step.run):
            commands += classify(part, load) if gates else [Command(part, Kind.UNKNOWN)]
    return Reading(tuple(commands), tuple(actions))


def read(text: str, job: Job, root: Path) -> Reading:
    """A workflow job's reading, its `package.json` files read from the checkout at root"""
    return read_steps(steps(text, job), root)


# --- The required checks (S-080-1) -------------------------------------------------------------

CLASSIC = "classic protection"
STATUS_CHECKS = "required_status_checks"  # the ruleset rule, and classic protection's key


@dataclass(frozen=True, slots=True)
class Required:
    """A context a merge to the branch waits for, with every source that requires it: a
    ruleset as `ruleset "<name>"`, and `classic protection`"""

    context: str
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Contexts:
    """The required contexts that were read, and what couldn't be read, each said in a phrase"""

    required: tuple[Required, ...]
    unread: tuple[str, ...]


def _contexts(found: object) -> list[str] | None:
    """The contexts of a `required_status_checks` list of objects with a `context`; None when it
    isn't one"""
    if not isinstance(found, list) or not all(isinstance(c, Mapping) for c in found):
        return None
    contexts = [c.get("context") for c in found]
    return [str(c) for c in contexts] if all(isinstance(c, str) for c in contexts) else None


def required_contexts(reader: RulesReader | None, repo: str | None, branch: str) -> Contexts:
    """The contexts every active ruleset's `required_status_checks` rule and classic protection
    require on the branch, each listed once with its sources; reader None: gh isn't installed,
    repo None: the origin isn't a GitHub repository. A read that fails, or an answer that isn't
    the shape GitHub documents, is unread and the rest is still read"""
    if reader is None:
        return Contexts((), ("can't read the required checks: gh isn't installed",))
    if repo is None:
        return Contexts((), ("can't read the required checks: this checkout's origin isn't a GitHub repository",))
    sources: dict[str, list[str]] = {}
    unread: list[str] = []

    def add(context: str, source: str) -> None:
        listed = sources.setdefault(context, [])
        if source not in listed:
            listed.append(source)

    try:
        rules: Sequence[Mapping[str, Any]] = reader.branch_rules(repo, branch)
    except ReleaseError as exc:
        unread.append(f"can't read {branch}'s rulesets: {exc}")
        rules = []
    names: dict[int, str] = {}
    for rule in rules:
        if rule.get("type") != STATUS_CHECKS:
            continue
        label = _ruleset(reader, repo, rule.get("ruleset_id"), names, unread)
        parameters = rule.get("parameters")
        contexts = _contexts(parameters.get(STATUS_CHECKS) if isinstance(parameters, Mapping) else None)
        if contexts is None:
            unread.append(f"can't read the checks {label} requires: GitHub's answer lists none")
            continue
        for context in contexts:
            add(context, label)
    try:
        classic = reader.protection(repo, branch)
    except ReleaseError as exc:
        unread.append(f"can't read {branch}'s classic protection: {exc}")
        classic = None
    status = classic.body.get(STATUS_CHECKS) if classic is not None and classic.body is not None else None
    if isinstance(status, Mapping):
        listed = status.get("contexts", [])
        checks = _contexts(status.get("checks", []))
        if not isinstance(listed, list) or not all(isinstance(c, str) for c in listed) or checks is None:
            unread.append(f"can't read the checks {CLASSIC} requires: GitHub's answer isn't a list of them")
        else:
            for context in [*listed, *checks]:
                add(context, CLASSIC)
    return Contexts(tuple(Required(c, tuple(s)) for c, s in sources.items()), tuple(unread))


def _ruleset(reader: RulesReader, repo: str, ruleset_id: object, names: dict[int, str], unread: list[str]) -> str:
    """A ruleset as a source, `ruleset "<name>"`, its name read once per run; `ruleset <id>`
    when the name can't be read, which is unread"""
    if not isinstance(ruleset_id, int):
        unread.append("can't tell which ruleset requires a check: GitHub's answer names no ruleset id")
        return "a ruleset"
    if ruleset_id not in names:
        try:
            name = reader.ruleset(repo, ruleset_id).get("name")
        except ReleaseError as exc:
            unread.append(f"can't read the name of ruleset {ruleset_id}: {exc}")
            name = None
        names[ruleset_id] = f'ruleset "{name}"' if isinstance(name, str) else f"ruleset {ruleset_id}"
    return names[ruleset_id]


# --- The jobs behind each (S-080-2) ------------------------------------------------------------

PULL_REQUEST_EVENTS = frozenset({"pull_request", "pull_request_target", "merge_group"})
LOCAL_CALL = "./"
UNMATCHED = "no job in .github/workflows reports it by a name its text tells"


@dataclass(frozen=True, slots=True)
class Reporter:
    """A job that reports a check on a pull request: the workflow file whose steps it runs, the
    check's name (`<caller> / <called job>` for a job of a local reusable workflow), whether a
    matrix adds ` (<values>)` to it, and its reading"""

    workflow: str
    job: str
    matrix: bool
    reading: Reading

    def reports(self, context: str) -> bool:
        if self.matrix:
            return context.startswith(f"{self.job} (") and context.endswith(")")
        return context == self.job

    def __str__(self) -> str:
        return f"{self.workflow} job {self.job}"


def _text(path: Path, root: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseError(
            f"{path.relative_to(root).as_posix()} is not UTF-8 ({exc}), so its jobs can't be read"
        ) from None


def _read(text: str, job: Job, root: Path, path: Path) -> Reading:
    """A job's reading; a failure names the workflow file it came from"""
    try:
        return read(text, job, root)
    except ReleaseError as exc:
        raise ReleaseError(f"{path.relative_to(root).as_posix()} job {job.id}: {exc}") from None


def reporters(root: Path) -> tuple[Reporter, ...]:
    """The jobs of `.github/workflows/` whose workflow runs on a pull request, a job of a local
    reusable workflow one level down for each that calls one; a job whose name holds an
    expression, or one that calls a remote workflow, reports nothing a text tells"""
    folder = root / WORKFLOWS_DIR
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix in SUFFIXES) if folder.is_dir() else []
    return tuple(reporter for path in files for reporter in _workflow(root, path))


def _workflow(root: Path, path: Path) -> Iterator[Reporter]:
    text = _text(path, root)
    if not events(text) & PULL_REQUEST_EVENTS:
        return
    for job in jobs(text):
        name = reported_name(text, job)
        called = calls(text, job)
        if name is None:
            continue
        if called is None:
            yield Reporter(path.name, name, has_matrix(text, job), _read(text, job, root, path))
            continue
        local = called.removeprefix(LOCAL_CALL)
        target = root / local
        if not called.startswith(LOCAL_CALL) or not is_workflow(local) or not target.is_file():
            continue
        inner = _text(target, root)
        for called_job in jobs(inner):
            called_name = reported_name(inner, called_job)
            if called_name is None or calls(inner, called_job) is not None:
                continue  # followed one level only
            reading = _read(inner, called_job, root, target)
            yield Reporter(target.name, f"{name} / {called_name}", has_matrix(inner, called_job), reading)


# --- The judgement (S-080-8 to S-080-13) -------------------------------------------------------

ROW = "merge-checks"
SHOWN = 5  # commands named per kind, and unknown ones, on a check's line
SHOWN_KINDS = (*PROVING, Kind.BUILD)
FIX = 'require one that runs tests, a type check, or a lint, or set [autonomy] land = "propose"'


def land_level(value: str) -> Autonomy:
    """A `--land` value, one of the levels"""
    try:
        return Autonomy(value)
    except ValueError:
        levels = ", ".join(level.value for level in Autonomy)
        raise ReleaseError(f"--land {value!r} isn't a level: use one of {levels}") from None


@dataclass(frozen=True, slots=True)
class Check:
    """A required context and the jobs that report it, none when no job matches"""

    required: Required
    jobs: tuple[Reporter, ...]

    @property
    def coverage(self) -> Coverage:
        return coverage(c for job in self.jobs for c in job.reading.commands)

    def label(self) -> str:
        return f"`{self.required.context}`"

    def line(self) -> str:
        head = f"{self.label()} ({', '.join(self.required.sources)})"
        if not self.jobs:
            return f"{head}: {Kind.UNKNOWN}: {UNMATCHED}"
        commands = [c for job in self.jobs for c in job.reading.commands]
        sections = [
            f"{kind} ({_named([c.text for c in commands if c.kind is kind])})"
            for kind in SHOWN_KINDS
            if any(c.kind is kind for c in commands)
        ]
        said = [", ".join(sections)] if sections else []
        unknown = [c.text for c in commands if c.kind is Kind.UNKNOWN]
        if unknown:
            said.append(f"{Kind.UNKNOWN}: {_named(unknown)}")
        actions = list(dict.fromkeys(a for job in self.jobs for a in job.reading.actions))
        if actions:
            said.append(f"actions not read: {', '.join(actions)}")
        jobs_said = ", ".join(str(job) for job in self.jobs)
        return f"{head}: {jobs_said}: {'; '.join(said) if said else 'runs no command'}"

    def record(self) -> dict[str, object]:
        found = self.coverage
        return {
            "context": self.required.context,
            "sources": list(self.required.sources),
            "jobs": [_job_record(job) for job in self.jobs],
            "kinds": [str(kind) for kind in found.kinds],
            "reads": str(found),
            "note": None if self.jobs else UNMATCHED,
        }


def _job_record(job: Reporter) -> dict[str, object]:
    return {
        "workflow": job.workflow,
        "job": job.job,
        "matrix": job.matrix,
        "commands": [{"text": c.text, "kind": str(c.kind)} for c in job.reading.commands],
        "actions": list(job.reading.actions),
    }


def _named(texts: Sequence[str]) -> str:
    """At most SHOWN of the texts, each once, then `and N more`"""
    unique = list(dict.fromkeys(texts))
    shown = unique[:SHOWN]
    if len(unique) > SHOWN:
        shown.append(f"and {len(unique) - SHOWN} more")
    return ", ".join(shown)


def _count(n: int) -> str:
    return f"{n} check" if n == 1 else f"{n} checks"


@dataclass(frozen=True, slots=True)
class Report:
    """The reading judged at a land level: a line per required check, then the summing line"""

    branch: str
    land: Autonomy
    checks: tuple[Check, ...]
    unrequired: tuple[Reporter, ...]
    unread: tuple[str, ...]

    @property
    def proving(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.coverage.proves)

    def _facts(self) -> str:
        if not self.checks:
            return f"{self.branch} requires no status check; land is {self.land}"
        kinds = coverage(c for check in self.proving for job in check.jobs for c in job.reading.commands)
        if self.proving:
            proves = f"{len(self.proving)} {'proves' if len(self.proving) == 1 else 'prove'} ({kinds})"
        else:
            proves = f"none proves ({self._unproven()})"
        return f"{self.branch} requires {_count(len(self.checks))}; {proves}; land is {self.land}"

    def _unproven(self) -> str:
        return ", ".join(f"{c.label()} {c.coverage}" for c in self.checks)

    def _also(self) -> str:
        if not self.unrequired:
            return ""
        jobs_said = ", ".join(f"{job} ({coverage(job.reading.commands)})" for job in self.unrequired)
        return f"; these jobs run on pull requests and prove something: {jobs_said}"

    def last(self) -> tuple[str, str]:
        """The summing line's status and detail: a WARN for a read that failed, at every level;
        under act a WARN when nothing is required or nothing required proves; else a PASS"""
        if self.unread:
            return "WARN", f"{'; '.join(self.unread)}; the checks stay unjudged; {self._facts()}"
        if self.land is Autonomy.ACT and not self.checks:
            detail = (
                f"no status check is required on {self.branch}, so a pull request can merge on whichever checks"
                f" reported: {FIX}"
            )
            return "WARN", detail + self._also()
        if self.land is Autonomy.ACT and not self.proving:
            detail = (
                f"{self.branch} requires {_count(len(self.checks))} and none runs tests, a type check, a lint, or an"
                f" import-boundary check ({self._unproven()}): {FIX}"
            )
            return "WARN", detail + self._also()
        return "PASS", self._facts()

    def lines(self) -> list[tuple[str, str]]:
        return [("PASS", check.line()) for check in self.checks] + [self.last()]

    def record(self) -> dict[str, object]:
        status, summary = self.last()
        return {
            "branch": self.branch,
            "land": str(self.land),
            "status": status,
            "summary": summary,
            "required": [check.record() for check in self.checks],
            "unrequired": [
                {
                    "workflow": job.workflow,
                    "job": job.job,
                    "kinds": [str(k) for k in coverage(job.reading.commands).kinds],
                }
                for job in self.unrequired
            ],
            "unread": list(self.unread),
        }


def report(root: Path, repo: str | None, branch: str, land: Autonomy, reader: RulesReader | None) -> Report:
    """What gates a merge to the branch, judged at the land level: the required contexts read
    through the reader (None: gh isn't installed) from repo (None: no GitHub origin), each matched
    to the jobs of the checkout's pull-request workflows. Reads only; writes nothing (S-080-16)"""
    contexts = required_contexts(reader, repo, branch)
    found = reporters(root)
    checks = tuple(Check(r, tuple(job for job in found if job.reports(r.context))) for r in contexts.required)
    matched = {job for check in checks for job in check.jobs}
    unrequired = tuple(job for job in found if job not in matched and coverage(job.reading.commands).proves)
    return Report(branch, land, checks, unrequired, contexts.unread)
