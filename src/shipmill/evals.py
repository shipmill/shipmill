"""The agents' eval suite, `evals/`, checked without a model (spec 025).

`claude plugin eval` runs the suite; this module only checks that it is well formed, so a
malformed case shows on the pull request that adds it. A case is a directory under `evals/`
holding a `prompt.md` or a `case.yaml`, as the runner reads it; `evals/cases.toml` lists each
one with what shipmill needs beyond the runner's format:

    [[case]]
    path = "github-issue-triage/feature-maintainer-filed"
    skill = "github-issue-triage"
    kind = "verdict"
    source = "shipmill/shipmill#380"
    commit = "f8c08ec"

A malformed `cases.toml` is bad input (ReleaseError, exit 2); every other fault is a
Violation naming the case and the rule it breaks (exit 1). The case files are YAML; the
package has no YAML library, so `_Yaml` reads the block subset the runner's cases use and
refuses, as a violation, anything outside it. `gate_short` names the kinds the suite holds
fewer cases of than `GATE`, the first suite's counts; the gate turns on once it names none.

`compare` is the gate against the default branch: it reads two runner results,
`aggregate-result.json`, and judges the head's against the base's from the per-run grader
results alone. Of each result (`schemaVersion` 1) it reads only these keys, and ignores the
rest:

    {"schemaVersion": 1, "partial": false,
     "cases": [{"name": "feature-maintainer-filed",
                "dir": "evals/github-issue-triage/feature-maintainer-filed",
                "runsPerCase": 3,
                "arms": {"with": [{"error": null, "skippedPaidGraders": false,
                                   "graders": [{"name": "verdict", "passed": true},
                                               {"name": "note", "passed": false, "scored": false}]}]}}]}

A case is keyed by its `dir` relative to `evals/`, so two skills' cases of one `name` stay
apart. A run is one entry of `arms.with`; it fails when it carries an `error`, is `aborted`,
or skipped its paid graders, and otherwise passes only when every scored grader passed. A run
stopped at its budget sets `partial: true` with `partialReason: "cost_ceiling"`; the file
names no planned run count, so the budget line's planned count is each case's `runsPerCase`,
summed. A run stopped for another reason is never compared either (exit 2). A missing or
malformed result is bad input (ReleaseError, exit 2) naming the file and the fault.
"""

import json
import re
import tomllib
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from pathlib import Path, PurePosixPath

from shipmill.errors import ReleaseError
from shipmill.gitrepo import Git

SUITE = PurePosixPath("evals")
MANIFEST = SUITE / "cases.toml"
PROMPT = "prompt.md"
CASE = "case.yaml"
GRADERS = "graders"
NOT_CASES = frozenset({"results", "mocks", "bin"})  # the runner's output, its mocks, the gh stub
MAX_TURNS = 40
MAX_TIMEOUT_SECONDS = 900
RUNNER_MAX_TURNS = 10  # the runner's defaults, when a case sets neither
RUNNER_TIMEOUT_SECONDS = 300
DETERMINISTIC = frozenset({"regex", "tool_used", "tool_order", "file_exists"})
JUDGED = frozenset({"llm", "baseline"})  # a judge model votes
FIELDS = ("path", "skill", "kind", "source", "commit")

_ISSUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+#[1-9][0-9]*")
_SHA = re.compile(r"[0-9a-f]{7,40}")
_NAME = re.compile(r"[A-Za-z0-9._-]+")
_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]+(.*))?")

Resolves = Callable[[str], bool]
"""Whether a commit sha names a commit in the repository"""


class Kind(StrEnum):
    VERDICT = "verdict"
    DECISION = "decision"
    FINDING = "finding"
    FIX = "fix"


@dataclass(frozen=True, slots=True)
class Violation:
    """A rule a case of the suite breaks"""

    case: PurePosixPath  # relative to the repo root, such as evals/<skill>/<case>
    rule: str

    def __str__(self) -> str:
        return f"{self.case}: {self.rule}"


@dataclass(frozen=True, slots=True)
class Entry:
    """One [[case]] of cases.toml, its values as written; check() judges them"""

    path: PurePosixPath  # relative to evals/
    skill: str
    kind: str
    source: str
    commit: str


@dataclass(frozen=True, slots=True)
class Report:
    cases: int
    violations: tuple[Violation, ...]
    entries: tuple[Entry, ...]


# The first suite's counts (spec 025): until the suite holds them, the gate is off and the
# evals pull request job reports its comparison and exits 0 (S-025-16)
GATE: Mapping[Kind, int] = {Kind.VERDICT: 8, Kind.DECISION: 4, Kind.FINDING: 4, Kind.FIX: 4}


@dataclass(frozen=True, slots=True)
class Short:
    """A kind the suite holds fewer cases of than the gate asks"""

    kind: Kind
    has: int
    needs: int

    def __str__(self) -> str:
        return f"{self.kind}: {self.has} of {self.needs}"


def gate_short(entries: tuple[Entry, ...]) -> tuple[Short, ...]:
    """The kinds short of the gate's counts, in the table's order; empty once the gate is on.
    An entry of an unknown kind counts for none"""
    counts = {kind: sum(1 for e in entries if e.kind == kind.value) for kind in GATE}
    return tuple(Short(kind, counts[kind], need) for kind, need in GATE.items() if counts[kind] < need)


def git_resolves(root: Path) -> Resolves:
    git = Git(root)
    return lambda sha: git.ok("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")


def check(root: Path, resolves: Resolves | None = None) -> Report | None:
    """The suite's violations, or None for an empty suite: no evals/ yet, or an evals/ with
    only the shared tools (bin/, graders/, scaffold.sh) and neither a case directory nor a
    cases.toml. Raises ReleaseError on a malformed cases.toml"""
    suite = root / SUITE
    if not suite.is_dir():
        return None
    found = set(_case_dirs(suite, PurePosixPath()))
    manifest = root / MANIFEST
    if not found and not manifest.exists():
        return None
    resolve = resolves if resolves is not None else git_resolves(root)
    violations: list[Violation] = []
    if manifest.is_file():
        entries = read_manifest(manifest)
    else:
        entries = ()
        violations.append(Violation(MANIFEST, "missing; it lists every case under evals/"))
    listed = {e.path for e in entries}
    for path in sorted(found - listed):
        violations.append(Violation(SUITE / path, f"a case directory not listed in {MANIFEST}"))
    for entry in entries:
        if entry.path not in found:
            rule = f"listed in {MANIFEST}, but no directory there holds a {PROMPT} or a {CASE}"
            violations.append(Violation(SUITE / entry.path, rule))
            continue
        violations.extend(Violation(SUITE / entry.path, r) for r in _case_rules(root, entry, resolve))
    return Report(len(entries), tuple(violations), entries)


def read_manifest(path: Path) -> tuple[Entry, ...]:
    """cases.toml's entries; ReleaseError naming the fault when it is malformed"""
    name = MANIFEST.as_posix()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ReleaseError(f"{name} is not valid TOML: {exc}") from None
    extra = sorted(set(raw) - {"case"})
    if extra:
        raise ReleaseError(f"{name} holds only [[case]] entries; got {', '.join(extra)}")
    cases = raw.get("case", [])
    if not isinstance(cases, list):
        raise ReleaseError(f"{name}: case is a list of [[case]] tables")
    entries: list[Entry] = []
    seen: set[PurePosixPath] = set()
    for number, item in enumerate(cases, 1):
        where = f"{name}: [[case]] {number}"
        if not isinstance(item, dict):
            raise ReleaseError(f"{where} is not a table")
        missing = [f for f in FIELDS if f not in item]
        unknown = sorted(set(item) - set(FIELDS))
        if missing or unknown:
            got = "; ".join(
                part
                for part in (
                    f"missing {', '.join(missing)}" if missing else "",
                    f"unknown {', '.join(unknown)}" if unknown else "",
                )
                if part
            )
            raise ReleaseError(f"{where} has exactly the keys {', '.join(FIELDS)}; {got}")
        for field in FIELDS:
            if not isinstance(item[field], str) or not item[field]:
                raise ReleaseError(f"{where}: {field} is a non-empty string; got {item[field]!r}")
        text: str = item["path"]
        if not case_path_ok(text):
            raise ReleaseError(f"{where}: path is relative to evals/, such as <skill>/<case>; got {text!r}")
        case_path = PurePosixPath(text)
        if case_path in seen:
            raise ReleaseError(f"{where}: path {text!r} is listed twice")
        seen.add(case_path)
        entries.append(Entry(case_path, item["skill"], item["kind"], item["source"], item["commit"]))
    return tuple(entries)


def _case_dirs(folder: Path, at: PurePosixPath) -> Iterator[PurePosixPath]:
    """Every case directory under folder, relative to evals/: one holding a prompt.md or a
    case.yaml. Nothing inside a case is another case, as the runner reads it"""
    for child in sorted(folder.iterdir()):
        if not child.is_dir() or child.is_symlink() or child.name.startswith("."):
            continue
        if at == PurePosixPath() and child.name in NOT_CASES:
            continue
        if child.name == GRADERS:  # shared graders, evals/graders/ or a skill's: never a case
            continue
        path = at / child.name
        if (child / PROMPT).is_file() or (child / CASE).is_file():
            yield path
        else:
            yield from _case_dirs(child, path)


def _case_rules(root: Path, entry: Entry, resolves: Resolves) -> list[str]:
    rules: list[str] = []
    skill_ok = bool(_NAME.fullmatch(entry.skill)) and entry.skill not in (".", "..")
    if not skill_ok or not (root / "skills" / entry.skill).is_dir():
        rules.append(f"skill {entry.skill!r} is not a directory under skills/")
    kinds = ", ".join(k.value for k in Kind)
    kind = Kind(entry.kind) if entry.kind in {k.value for k in Kind} else None
    if kind is None:
        rules.append(f"kind {entry.kind!r} is not one of {kinds}")
    if not _source_ok(root, entry.source):
        rules.append(f"source {entry.source!r} is neither owner/repo#N nor the path of a file under docs/postmortems/")
    if not _SHA.fullmatch(entry.commit) or not resolves(entry.commit):
        rules.append(f"commit {entry.commit!r} does not resolve to a commit in this repository (a 7 to 40 digit sha)")
    case = root / SUITE / entry.path
    try:
        settings = _settings(case)
    except _Unread as exc:
        return [*rules, str(exc)]
    if entry.skill not in settings.tags:
        rules.append(f"tags {list(settings.tags)} do not name the skill {entry.skill!r}")
    for field, value, ceiling in (
        ("max_turns", settings.max_turns, MAX_TURNS),
        ("timeout_seconds", settings.timeout_seconds, MAX_TIMEOUT_SECONDS),
    ):
        if value > ceiling:
            rules.append(f"{field} is {value}, above the ceiling of {ceiling}")
    if settings.scaffold is not None:
        rules.extend(_scaffold_rules(case, settings.scaffold))
    if settings.slash and settings.skill_graded:
        rules.append(
            f"{PROMPT} opens with a slash command, which loads the skill inline with no Skill call,"
            " so a tool_used grader counting Skill calls can never pass"
        )
    if not settings.graders:
        rules.append(f"no grader, in {GRADERS}/*.md or in {CASE}")
    elif kind is not Kind.FINDING and not DETERMINISTIC & set(settings.graders):
        rules.append(
            f"no deterministic grader ({', '.join(sorted(DETERMINISTIC))}); only a finding case may rest on a judge"
        )
    return rules


def _scaffold_rules(case: Path, scaffold: str) -> list[str]:
    """The runner runs only a scaffold_script inside the case's directory (#929): a path
    with `..` or an absolute one fails every run of the case before its first turn"""
    path = PurePosixPath(scaffold)
    if path.is_absolute() or ".." in path.parts:
        return [
            f"context.scaffold_script {scaffold!r} escapes the case directory; name a script inside it,"
            " such as scaffold.sh calling ../../scaffold.sh"
        ]
    if not (case / path).is_file():
        return [f"context.scaffold_script {scaffold!r} is not a file in the case directory"]
    return []


def _source_ok(root: Path, source: str) -> bool:
    if _ISSUE.fullmatch(source):
        return True
    parts = source.split("/")
    if parts[:2] != ["docs", "postmortems"] or len(parts) < 3:
        return False
    if any(p in ("", ".", "..") for p in parts):
        return False
    return (root / source).is_file()


@dataclass(frozen=True, slots=True)
class _Settings:
    tags: tuple[str, ...]
    max_turns: int
    timeout_seconds: int
    graders: tuple[str, ...]  # each grader's type
    scaffold: str | None  # case.yaml's context.scaffold_script, as written
    slash: bool  # prompt.md's body opens with a slash command
    skill_graded: bool  # a tool_used grader counts Skill calls


class _Unread(Exception):
    """A case file this check can't read; reported as the case's violation"""


def _settings(case: Path) -> _Settings:
    """The case's tags, limits, and grader types as the runner would take them: prompt.md's
    frontmatter over case.yaml's fields, then the runner's defaults; graders from case.yaml and
    graders/*.md"""
    front: dict[str, object] = {}
    if (case / PROMPT).is_file():
        front = _frontmatter(case / PROMPT, PROMPT)
    spec: dict[str, object] = {}
    if (case / CASE).is_file():
        spec = _Yaml(_text(case / CASE), CASE).mapping()
    execution = spec.get("execution", {})
    if not isinstance(execution, dict):
        raise _Unread(f"{CASE}: execution is a mapping")
    context = spec.get("context", {})
    if not isinstance(context, dict):
        raise _Unread(f"{CASE}: context is a mapping")
    scaffold = context.get("scaffold_script")
    if scaffold is not None and (not isinstance(scaffold, str) or not scaffold):
        raise _Unread(f"{CASE}: context.scaffold_script is a path; got {scaffold!r}")

    def pick(key: str, nested: dict[str, object]) -> object:
        return front[key] if key in front else nested.get(key)

    tags = _list(pick("tags", spec), "tags")
    max_turns = _int(pick("max_turns", execution), "max_turns", RUNNER_MAX_TURNS)
    timeout = _int(pick("timeout_seconds", execution), "timeout_seconds", RUNNER_TIMEOUT_SECONDS)
    graders: list[str] = []
    skill_graded = False
    listed = spec.get("graders", [])
    if not isinstance(listed, list):
        raise _Unread(f"{CASE}: graders is a list of graders")
    for number, grader in enumerate(listed, 1):
        if not isinstance(grader, dict):
            raise _Unread(f"{CASE}: grader {number} is a mapping with a type")
        graders.append(_type(grader, f"{CASE}: grader {number}"))
        skill_graded = skill_graded or _counts_skill(grader)
    folder = case / GRADERS
    if folder.is_dir():
        for file in sorted(folder.glob("*.md")):
            name = f"{GRADERS}/{file.name}"
            if not file.is_file():  # a FIFO or /dev/zero would block or never end the read
                raise _Unread(f"{name} is not a regular file")
            front_matter = _frontmatter(file, name)
            graders.append(_type(front_matter, name))
            skill_graded = skill_graded or _counts_skill(front_matter)
    slash = (case / PROMPT).is_file() and _body(case / PROMPT).startswith("/")
    return _Settings(tags, max_turns, timeout, tuple(graders), scaffold, slash, skill_graded)


def _counts_skill(grader: dict[str, object]) -> bool:
    return grader.get("type") == "tool_used" and grader.get("tool") == "Skill"


def _body(path: Path) -> str:
    """A prompt's text after its frontmatter, leading blank lines dropped"""
    lines = _text(path).splitlines()
    if lines and lines[0].rstrip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), len(lines) - 1)
        lines = lines[end + 1 :]
    return "\n".join(lines).lstrip()


def _type(grader: dict[str, object], where: str) -> str:
    value = grader.get("type")
    known = DETERMINISTIC | JUDGED
    if not isinstance(value, str) or value not in known:
        raise _Unread(f"{where}: type is one of {', '.join(sorted(known))}; got {value!r}")
    return value


def _list(value: object, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _Unread(f"{key} is a list of names; got {value!r}")
    return tuple(str(v) for v in value)


def _int(value: object, key: str, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise _Unread(f"{key} is a whole number from 1; got {value!r}")
    return int(value)


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise _Unread(f"{path.name} is not UTF-8") from None


def _frontmatter(path: Path, name: str) -> dict[str, object]:
    """The mapping between a file's leading `---` lines; empty without them"""
    lines = _text(path).splitlines()
    if not lines or lines[0].rstrip() != "---":
        return {}
    for end in range(1, len(lines)):
        if lines[end].rstrip() == "---":
            return _Yaml("\n".join(lines[1:end]), name).mapping()
    raise _Unread(f"{name}: the frontmatter has no closing ---")


class _Yaml:
    """A strict reader of the block YAML subset the runner's case files use: nested block
    mappings and sequences, `|` and `>` block scalars, plain and quoted scalars, and flow
    lists of plain scalars. A scalar is kept as its text (quotes removed); a flow mapping or
    a multi-line scalar is kept as raw text, since no rule reads one. Anything else raises
    _Unread naming the file and line"""

    def __init__(self, text: str, name: str) -> None:
        self.name = name
        self.lines: list[tuple[int, int, str]] = []  # (line number, indent, content)
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            body = line.lstrip(" ")
            if body.startswith("\t"):
                raise self.error(number, "indent with spaces, not tabs")
            self.lines.append((number, len(line) - len(body), body.rstrip()))
        self.at = 0

    def error(self, number: int, why: str) -> _Unread:
        return _Unread(f"{self.name}: line {number}: {why}")

    def mapping(self) -> dict[str, object]:
        if not self.lines:
            return {}
        node = self._block(self.lines[0][1])
        if self.at < len(self.lines):
            raise self.error(self.lines[self.at][0], "indented less than the document's first line")
        if not isinstance(node, dict):
            raise self.error(self.lines[0][0], "the document is a mapping of key: value lines")
        return node

    def _block(self, indent: int) -> object:
        _, _, content = self.lines[self.at]
        if content == "-" or content.startswith("- "):
            return self._sequence(indent)
        return self._mapping(indent)

    def _mapping(self, indent: int) -> dict[str, object]:
        node: dict[str, object] = {}
        while self.at < len(self.lines):
            number, at, content = self.lines[self.at]
            if at < indent:
                break
            if at > indent:
                raise self.error(number, "indented deeper than its mapping's keys")
            if content == "-" or content.startswith("- "):
                break
            found = _KEY.fullmatch(content)
            if found is None:
                raise self.error(number, "not a `key: value` line")
            key, raw = found.group(1), (found.group(2) or "").strip()
            if key in node:
                raise self.error(number, f"{key} is set twice")
            self.at += 1
            node[key] = self._value(number, indent, raw)
        return node

    def _sequence(self, indent: int) -> list[object]:
        node: list[object] = []
        while self.at < len(self.lines):
            number, at, content = self.lines[self.at]
            if at != indent or not (content == "-" or content.startswith("- ")):
                if at > indent:
                    raise self.error(number, "indented deeper than its list's items")
                break
            rest = content[1:].lstrip(" ")
            if rest and _KEY.fullmatch(rest):  # `- key: value` opens a mapping at the key's column
                self.lines[self.at] = (number, at + len(content) - len(rest), rest)
                node.append(self._mapping(self.lines[self.at][1]))
                continue
            self.at += 1
            node.append(self._value(number, indent, rest))
        return node

    def _value(self, number: int, indent: int, raw: str) -> object:
        nested = self.at < len(self.lines) and (
            self.lines[self.at][1] > indent
            or (self.lines[self.at][1] == indent and self.lines[self.at][2].startswith("- ") and raw == "")
        )
        if raw == "":
            return self._block(self.lines[self.at][1]) if nested else None
        if re.fullmatch(r"[|>][-+]?", raw):
            return "\n".join(self._deeper(indent))

        def fail(why: str) -> _Unread:
            return self.error(number, why)

        text = _strip_comment(raw, fail)
        more = list(self._deeper(indent))  # a plain scalar or flow collection that runs on
        if more:
            return " ".join([text, *more])
        if text.startswith("["):
            if not text.endswith("]"):
                raise fail("a flow list closes with ] on its own line")
            inner = text[1:-1].strip()
            items = [_unquote(i.strip(), fail) for i in inner.split(",")] if inner else []
            if any(not i for i in items):
                raise fail("a flow list holds plain names, such as [a, b]")
            return items
        if text.startswith("{"):
            return text  # a flow mapping, such as a grader's target; no rule reads one
        return _unquote(text, fail)

    def _deeper(self, indent: int) -> Iterator[str]:
        while self.at < len(self.lines) and self.lines[self.at][1] > indent:
            yield self.lines[self.at][2]
            self.at += 1


def _strip_comment(raw: str, error: Callable[[str], _Unread]) -> str:
    if raw[0] in "'\"":
        close = _closing_quote(raw)
        if close is None:
            raise error("a quoted scalar is not closed on its line")
        rest = raw[close + 1 :].strip()
        if rest and not rest.startswith("#"):
            raise error("text after a quoted scalar")
        return raw[: close + 1]
    found = re.search(r"\s#", raw)
    return raw if found is None else raw[: found.start()].rstrip()


def _closing_quote(raw: str) -> int | None:
    quote = raw[0]
    index = 1
    while index < len(raw):
        char = raw[index]
        if quote == '"' and char == "\\":
            index += 2
            continue
        if char == quote:
            if quote == "'" and raw[index + 1 : index + 2] == "'":  # '' is an escaped quote
                index += 2
                continue
            return index
        index += 1
    return None


def _unquote(text: str, error: Callable[[str], _Unread]) -> str:
    if text[:1] in ("'", '"'):
        if _closing_quote(text) != len(text) - 1:
            raise error(f"a malformed quoted scalar: {text}")
        inner = text[1:-1]
        return inner.replace("''", "'") if text[0] == "'" else inner
    return text


TOLERANCE = Fraction(1, 20)  # the suite's pass rate may drop by 0.05, no more
BUDGET_STOP = "cost_ceiling"  # the partialReason of a run stopped at --max-cost-usd
REGRESSED_AT = Fraction(1, 3)  # a case that passed every base run regresses at 1 of 3 or fewer
OWN_PASS = Fraction(2, 3)  # a new or changed case passes 2 of 3 runs on its own


@dataclass(frozen=True, slots=True)
class Rate:
    """Passing runs over runs"""

    passed: int
    runs: int

    @property
    def value(self) -> Fraction:
        return Fraction(self.passed, self.runs)

    @property
    def perfect(self) -> bool:
        return self.passed == self.runs

    def __str__(self) -> str:
        return f"{self.passed}/{self.runs}"


@dataclass(frozen=True, slots=True)
class Result:
    """One runner result: each case's passing runs, and whether the run stopped at its budget"""

    cases: Mapping[PurePosixPath, Rate]  # by path, relative to evals/
    runs_planned: int  # each case's runsPerCase, summed: the file names no other planned count
    budget_reached: bool  # partial, with partialReason "cost_ceiling"

    @property
    def runs_done(self) -> int:
        return sum(r.runs for r in self.cases.values())


class Move(StrEnum):
    REGRESSED = "regressed"
    NEW_FAILING = "new failing"
    IMPROVED = "improved"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class Moved:
    """A case that moved between the base and the head"""

    move: Move
    path: PurePosixPath
    base: Rate | None
    head: Rate | None

    def __str__(self) -> str:
        if self.base is not None and self.head is not None and self.move is not Move.NEW_FAILING:
            return f"{self.move} {self.path}: {self.base} -> {self.head}"
        if self.head is not None:
            return f"{self.move} {self.path}: {self.head}"
        return f"{self.move} {self.path}"


@dataclass(frozen=True, slots=True)
class Comparison:
    moved: tuple[Moved, ...]
    base: Rate  # the suite's, over the cases both hold that the head didn't change
    head: Rate
    tolerance: Fraction

    @property
    def suite_worse(self) -> bool:
        if not self.base.runs or not self.head.runs:
            return False
        return self.head.value < self.base.value - self.tolerance

    @property
    def failed(self) -> bool:
        return self.suite_worse or any(m.move in (Move.REGRESSED, Move.NEW_FAILING) for m in self.moved)


def budget_reached(base: Result, head: Result) -> str | None:
    """The line that fails the gate when either run stopped at its budget, so partial results
    are never compared (S-025-14); None when both ran in full"""
    for result in (head, base):
        if result.budget_reached:
            return f"evals: budget reached after {result.runs_done} of {result.runs_planned} runs"
    return None


def compare(
    base: Result, head: Result, changed: frozenset[PurePosixPath] = frozenset(), tolerance: Fraction = TOLERANCE
) -> Comparison:
    """The head judged against the base (S-025-8). A case the head changed, or the base lacks,
    is judged on its own; the suite's pass rates count the other cases both hold"""
    moved: list[Moved] = []
    base_passed = base_runs = head_passed = head_runs = 0
    for path in sorted(head.cases):
        now = head.cases[path]
        before = base.cases.get(path)
        if before is None or path in changed:
            if now.value < OWN_PASS:
                moved.append(Moved(Move.NEW_FAILING, path, before, now))
            continue
        base_passed, base_runs = base_passed + before.passed, base_runs + before.runs
        head_passed, head_runs = head_passed + now.passed, head_runs + now.runs
        if before.perfect and now.value <= REGRESSED_AT:
            moved.append(Moved(Move.REGRESSED, path, before, now))
        elif before.value <= REGRESSED_AT and now.perfect:
            moved.append(Moved(Move.IMPROVED, path, before, now))
    moved.extend(Moved(Move.REMOVED, p, base.cases[p], None) for p in sorted(set(base.cases) - set(head.cases)))
    order = list(Move)
    moved.sort(key=lambda m: order.index(m.move))  # stable: by path within each move
    return Comparison(tuple(moved), Rate(base_passed, base_runs), Rate(head_passed, head_runs), tolerance)


def read_result(path: Path) -> Result:
    """A runner's aggregate-result.json; ReleaseError naming the file and the fault when it is
    missing or malformed"""
    name = str(path)

    def fail(why: str) -> ReleaseError:
        return ReleaseError(f"{name}: {why}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise fail("no such file") from None
    except IsADirectoryError:
        raise fail("a directory, not a runner's aggregate-result.json") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise fail(f"not valid JSON: {exc}") from None
    if not isinstance(raw, dict):
        raise fail("the result is a JSON object")
    version = raw.get("schemaVersion")
    if version != 1 or isinstance(version, bool):
        raise fail(f"schemaVersion is 1, the runner format this reads; got {version!r}")
    stopped = raw.get("partial")
    if not isinstance(stopped, bool):
        raise fail(f"partial is true or false; got {stopped!r}")
    if stopped:
        reason = raw.get("partialReason")
        if reason != BUDGET_STOP:
            raise fail(f"partial: the run stopped early ({reason!r}), not at its budget, so it is never compared")
    cases = raw.get("cases")
    if not isinstance(cases, list):
        raise fail(f"cases is a list of cases; got {cases!r}")
    rates: dict[PurePosixPath, Rate] = {}
    planned = 0
    for number, case in enumerate(cases, 1):
        where = f"case {number}"
        if not isinstance(case, dict):
            raise fail(f"{where} is an object with a name, a dir, and its runs")
        if not isinstance(case.get("name"), str) or not case["name"]:
            raise fail(f"{where}: name is a non-empty string; got {case.get('name')!r}")
        where = f"case {case['name']!r}"
        text = case.get("dir")
        inside = text.removeprefix(f"{SUITE}/") if isinstance(text, str) else None
        if inside is None or inside == text or not case_path_ok(inside):
            raise fail(f"{where}: dir is the case's directory under evals/, such as evals/<skill>/<case>; got {text!r}")
        case_path = PurePosixPath(inside)
        if case_path in rates:
            raise fail(f"{where}: dir {text!r} is listed twice")
        per_case = case.get("runsPerCase")
        if not isinstance(per_case, int) or isinstance(per_case, bool) or per_case < 1:
            raise fail(f"{inside}: runsPerCase is a whole number from 1; got {per_case!r}")
        planned += per_case
        arms = case.get("arms")
        runs = arms.get("with") if isinstance(arms, dict) else None
        if not isinstance(runs, list) or (not runs and not stopped):
            raise fail(f"{inside}: arms.with is a list of at least one run; got {runs!r}")
        if runs:
            passed = sum(_run_passed(run, f"{inside}: run {n}", fail) for n, run in enumerate(runs, 1))
            rates[case_path] = Rate(passed, len(runs))
    if not rates and not stopped:
        raise fail("cases holds no case, so there is nothing to compare")
    return Result(rates, planned, stopped)


def case_path_ok(text: str) -> bool:
    """A case's path as cases.toml writes it: relative to evals/, such as <skill>/<case>"""
    return all(p not in ("", ".", "..") and _NAME.fullmatch(p) for p in text.split("/"))


def _run_passed(run: object, where: str, fail: Callable[[str], ReleaseError]) -> bool:
    """Whether a run passed: every scored grader passed (S-025-9). A run that carries an `error`
    (an API error leaves no grader results), was `aborted`, or skipped its paid graders failed.
    A grader is scored unless it says `"scored": false`; a run with no scored grader is
    malformed, never a pass"""
    if not isinstance(run, dict):
        raise fail(f"{where} is an object with its grader results")
    for flag in ("aborted", "skippedPaidGraders"):
        if not isinstance(run.get(flag, False), bool):
            raise fail(f"{where}: {flag} is true or false; got {run[flag]!r}")
    if run.get("error") is not None or run.get("aborted", False) or run.get("skippedPaidGraders", False):
        return False
    graders = run.get("graders")
    if not isinstance(graders, list):
        raise fail(f"{where}: graders is a list of grader results; got {graders!r}")
    scored: list[bool] = []
    for number, grader in enumerate(graders, 1):
        at = f"{where}: grader {number}"
        if not isinstance(grader, dict):
            raise fail(f"{at} is an object with a name and passed")
        if not isinstance(grader.get("name"), str) or not grader["name"]:
            raise fail(f"{at}: name is a non-empty string; got {grader.get('name')!r}")
        passed = grader.get("passed")
        if not isinstance(passed, bool):
            raise fail(f"{at}: passed is true or false; got {passed!r}")
        counts = grader.get("scored", True)
        if not isinstance(counts, bool):
            raise fail(f"{at}: scored is true or false; got {counts!r}")
        if counts:
            scored.append(passed)
    if not scored:
        raise fail(f"{where}: no scored grader, so the run neither passed nor failed")
    return all(scored)


# `explain` (D-72, #950): why each case of one run did not pass, from the run's own files and
# with no model call. Of each run it reads, beside what `_run_passed` reads, `turns`,
# `costUsd`, `durationSeconds`, `tracePath`, and each grader's `explanation`. A trace is the
# session's JSON lines; its last assistant text is a line `{"type": "assistant", "message":
# {"content": [{"type": "text", "text": ...}]}}`. With a traces directory, run n of a case's
# trace is `<traces>/<case>/run-<n>.jsonl` and the case's `.eval/gh.jsonl` logs, one per
# workspace, are `<traces>/<case>/gh-*.jsonl`, as the evals workflow copies them; without
# one, a run's trace is its `tracePath` and no log is read.
NO_MISS = "no-miss"  # the shared grader that fails a run on a `miss` in .eval/gh.jsonl
SHOWN = 300  # the characters of an error, an explanation, or a message a line shows
# "pattern not found in file <f>" is the runner's regex grader on a file it read, so no harness
_UNREAD_TARGET = re.compile(
    r"no such file|(?<!pattern )not found|does not exist|ENOENT|could not read|cannot read|can't read|unreadable",
    re.I,
)
_API_ERROR = re.compile(r"\bAPI error\b|\boverloaded|\brate.?limit", re.I)
_SCAFFOLD = re.compile(r"scaffold|fixture", re.I)


class Verdict(StrEnum):
    HARNESS = "harness"
    AGENT = "agent"


@dataclass(frozen=True, slots=True)
class Grade:
    name: str
    passed: bool
    scored: bool
    explanation: str


@dataclass(frozen=True, slots=True)
class Run:
    """One run of a case, as `explain` reads it"""

    number: int  # from 1, its place in arms.with
    passed: bool
    error: str | None
    aborted: bool
    skipped_paid: bool
    turns: float | None
    cost: float | None
    seconds: float | None
    trace: str | None  # tracePath, as written
    grades: tuple[Grade, ...]

    @property
    def failed_grades(self) -> tuple[Grade, ...]:
        return tuple(g for g in self.grades if not g.passed)

    def verdict(self) -> tuple[Verdict, str]:
        """Harness or agent, and why: the first rule that holds, in this order. A failed run
        no harness rule places reads agent, with the reason it fell through"""
        error = self.error or ""
        failed = [g for g in self.failed_grades if g.scored]
        if _API_ERROR.search(error):
            return Verdict.HARNESS, "an API error"
        if _SCAFFOLD.search(error):
            return Verdict.HARNESS, "the scaffold or the case's fixture failed"
        if error and not self.turns:
            return Verdict.HARNESS, "the session never took a turn"
        if any(g.name == NO_MISS for g in failed):
            return Verdict.HARNESS, "a gh read with no recording (a miss in .eval/gh.jsonl)"
        unread = [g.name for g in failed if _UNREAD_TARGET.search(g.explanation)]
        if unread:
            return Verdict.HARNESS, f"a grader can't read its target: {', '.join(unread)}"
        if self.skipped_paid:
            return Verdict.HARNESS, "its paid graders were skipped"
        if error:
            return Verdict.AGENT, f"the session ran and stopped: {_line(error)}"
        if failed:
            return Verdict.AGENT, f"the session ran and graders failed: {', '.join(g.name for g in failed)}"
        why = "aborted, with no error and no failed grader" if self.aborted else "no error and no failed grader"
        return Verdict.AGENT, f"it fell through every harness rule: {why}"


@dataclass(frozen=True, slots=True)
class CaseRuns:
    path: PurePosixPath  # relative to evals/
    runs: tuple[Run, ...]

    @property
    def failed(self) -> tuple[Run, ...]:
        return tuple(r for r in self.runs if not r.passed)


@dataclass(frozen=True, slots=True)
class Explained:
    """One runner result, every case's runs; `stopped` is the partialReason of a run stopped early"""

    cases: tuple[CaseRuns, ...]
    stopped: str | None


def read_runs(path: Path) -> Explained:
    """A runner's aggregate-result.json for `explain`: every case and run, a partial one too;
    ReleaseError naming the file and the fault when it is missing or malformed"""
    name = str(path)

    def fail(why: str) -> ReleaseError:
        return ReleaseError(f"{name}: {why}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise fail("no such file") from None
    except IsADirectoryError:
        raise fail("a directory, not a runner's aggregate-result.json") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise fail(f"not valid JSON: {exc}") from None
    if not isinstance(raw, dict):
        raise fail("the result is a JSON object")
    version = raw.get("schemaVersion")
    if version != 1 or isinstance(version, bool):
        raise fail(f"schemaVersion is 1, the runner format this reads; got {version!r}")
    partial = raw.get("partial")
    if not isinstance(partial, bool):
        raise fail(f"partial is true or false; got {partial!r}")
    reason = raw.get("partialReason")
    stopped = (reason if isinstance(reason, str) and reason else "no partialReason") if partial else None
    cases = raw.get("cases")
    if not isinstance(cases, list):
        raise fail(f"cases is a list of cases; got {cases!r}")
    read: list[CaseRuns] = []
    seen: set[PurePosixPath] = set()
    for number, case in enumerate(cases, 1):
        if not isinstance(case, dict) or not isinstance(case.get("name"), str) or not case["name"]:
            raise fail(f"case {number} is an object with a non-empty name, a dir, and its runs")
        text = case.get("dir")
        inside = text.removeprefix(f"{SUITE}/") if isinstance(text, str) else None
        if inside is None or inside == text or not case_path_ok(inside):
            raise fail(
                f"case {case['name']!r}: dir is the case's directory under evals/, such as evals/<skill>/<case>;"
                f" got {text!r}"
            )
        case_path = PurePosixPath(inside)
        if case_path in seen:
            raise fail(f"case {case['name']!r}: dir {text!r} is listed twice")
        seen.add(case_path)
        arms = case.get("arms")
        runs = arms.get("with") if isinstance(arms, dict) else None
        if not isinstance(runs, list):
            raise fail(f"{inside}: arms.with is a list of runs; got {runs!r}")
        read.append(
            CaseRuns(case_path, tuple(_run(run, n, f"{inside}: run {n}", fail) for n, run in enumerate(runs, 1)))
        )
    return Explained(tuple(read), stopped)


def _run(raw: object, number: int, where: str, fail: Callable[[str], ReleaseError]) -> Run:
    if not isinstance(raw, dict):
        raise fail(f"{where} is an object with its grader results")
    error = raw.get("error")
    if error is not None and not isinstance(error, str):
        raise fail(f"{where}: error is text or null; got {error!r}")
    trace = raw.get("tracePath")
    if trace is not None and not isinstance(trace, str):
        raise fail(f"{where}: tracePath is a path or null; got {trace!r}")
    numbers: dict[str, float | None] = {}
    for key in ("turns", "costUsd", "durationSeconds"):
        value = raw.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int | float) or value < 0):
            raise fail(f"{where}: {key} is a number from 0; got {value!r}")
        numbers[key] = None if value is None else float(value)
    grades: list[Grade] = []
    listed = raw.get("graders", [])
    if not isinstance(listed, list):
        raise fail(f"{where}: graders is a list of grader results; got {listed!r}")
    for n, grader in enumerate(listed, 1):
        at = f"{where}: grader {n}"
        if not isinstance(grader, dict) or not isinstance(grader.get("name"), str) or not grader["name"]:
            raise fail(f"{at} is an object with a non-empty name")
        passed, scored = grader.get("passed"), grader.get("scored", True)
        if not isinstance(passed, bool) or not isinstance(scored, bool):
            raise fail(f"{at}: passed and scored are true or false; got {passed!r}, {scored!r}")
        explanation = grader.get("explanation")
        if explanation is not None and not isinstance(explanation, str):
            raise fail(f"{at}: explanation is text; got {explanation!r}")
        grades.append(Grade(grader["name"], passed, scored, explanation or ""))
    # an errored, aborted, or half-graded run fails before its graders are read (S-025-9)
    errored = error is not None or raw.get("aborted") is True or raw.get("skippedPaidGraders") is True
    passed_run = False if errored else _run_passed(raw, where, fail)
    return Run(
        number,
        passed_run,
        error,
        raw.get("aborted") is True,
        raw.get("skippedPaidGraders") is True,
        numbers["turns"],
        numbers["costUsd"],
        numbers["durationSeconds"],
        trace,
        tuple(grades),
    )


def explain(result: Explained, traces: Path | None) -> str:
    """The Markdown section for the job summary: one entry per case with a failed run, each
    failed run's verdict and why, its error, failed graders, turns, cost, duration, and the
    last assistant message of its trace; a missing or unreadable trace is said on its line"""
    ran = [c for c in result.cases if c.runs]
    failing = [c for c in ran if c.failed]
    lines: list[str] = []
    if not failing:
        lines.append(f"### evals: every case passed ({len(ran)} of {len(ran)})")
    else:
        lines += [
            f"### evals: why {len(failing)} of {len(ran)} cases did not pass",
            "",
            "Each verdict is read from the run's own files, with no model call: **harness** when the harness"
            " failed the run, **agent** when the session ran and did the wrong thing.",
        ]
    for case in failing:
        logs = _gh_logs(traces / case.path) if traces is not None else None
        verdicts = [run.verdict() for run in case.failed]
        harness = any(v is Verdict.HARNESS for v, _ in verdicts) or bool(logs and logs.misses)
        passed = len(case.runs) - len(case.failed)
        lines += [
            "",
            f"#### {case.path}: {Verdict.HARNESS if harness else Verdict.AGENT}, {passed}/{len(case.runs)} runs passed",
            "",
        ]
        for run, (verdict, why) in zip(case.failed, verdicts, strict=True):
            lines.append(f"- Run {run.number}: **{verdict}**, {why}. {_spent(run)}")
            if run.error:
                lines.append(f"  - error: {_line(run.error)}")
            for grade in run.failed_grades:
                scored = "" if grade.scored else " (not scored)"
                lines.append(f"  - grader {grade.name} failed{scored}: {_line(grade.explanation) or 'no explanation'}")
            lines.append("  - " + _last_message(run, traces / case.path if traces is not None else None))
        if logs is not None:
            lines.append(f"- gh.jsonl: {logs}")
    not_run = [c for c in result.cases if not c.runs]
    if not_run:
        lines += ["", f"Not run, the run stopped first ({result.stopped}): {', '.join(str(c.path) for c in not_run)}"]
    return "\n".join(lines) + "\n"


def _spent(run: Run) -> str:
    turns = "turns unknown" if run.turns is None else f"{run.turns:g} turns"
    cost = "cost unknown" if run.cost is None else f"{run.cost:.2f} USD"
    seconds = "duration unknown" if run.seconds is None else f"{run.seconds:g} s"
    return f"{turns}, {cost}, {seconds}"


def _line(text: str) -> str:
    """Text on one line, cut to SHOWN characters"""
    flat = " ".join(text.split())
    return flat if len(flat) <= SHOWN else flat[: SHOWN - 1] + "…"


def _last_message(run: Run, case_traces: Path | None) -> str:
    """The run's last assistant text, or the line saying why there is none"""
    if case_traces is not None:
        trace = case_traces / f"run-{run.number}.jsonl"
        if not trace.is_file():
            return "trace: none in --traces for this run"
    elif run.trace is None:
        return "trace: the run names no tracePath"
    else:
        trace = Path(run.trace)
        if not trace.is_file():
            return f"trace: {trace} is missing"
    try:
        text = trace.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"trace: {trace.name} is not UTF-8"
    last: str | None = None
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return f"trace: line {number} of {trace.name} is not JSON"
        said = _assistant_text(entry)
        if said:
            last = said
    if last is None:
        return f"trace: {trace.name} holds no assistant text"
    return f"last message: {_line(last)}"


def _assistant_text(entry: object) -> str:
    if not isinstance(entry, dict) or entry.get("type") != "assistant":
        return ""
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    texts = [
        b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
    ]
    return "\n".join(texts)


@dataclass(frozen=True, slots=True)
class _GhLogs:
    logs: int
    misses: int
    first: str | None  # the first miss's call
    unread: tuple[str, ...]  # a log's line that isn't a JSON object

    def __str__(self) -> str:
        if not self.logs:
            return "no log in --traces"
        plural = "log" if self.logs == 1 else "logs"
        said = f"{self.misses} miss{'' if self.misses == 1 else 'es'} in {self.logs} {plural}"
        if self.first is not None:
            said += f", the first `{self.first}`"
        if self.unread:
            said += f"; unreadable: {', '.join(self.unread)}"
        return said


def _gh_logs(case_traces: Path) -> _GhLogs:
    files = sorted(case_traces.glob("gh-*.jsonl")) if case_traces.is_dir() else []
    misses = 0
    first: str | None = None
    unread: list[str] = []
    for file in files:
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            unread.append(f"{file.name} is not UTF-8")
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                unread.append(f"{file.name} line {number}")
                continue
            if not isinstance(entry, dict):
                unread.append(f"{file.name} line {number}")
                continue
            if entry.get("kind") == "miss":
                misses += 1
                args = entry.get("args")
                if first is None and isinstance(args, list):
                    first = _line("gh " + " ".join(str(a) for a in args)).replace("`", "'")
    return _GhLogs(len(files), misses, first, tuple(unread))
