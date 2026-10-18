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
refuses, as a violation, anything outside it.
"""

import re
import tomllib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum
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


def git_resolves(root: Path) -> Resolves:
    git = Git(root)
    return lambda sha: git.ok("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")


def check(root: Path, resolves: Resolves | None = None) -> Report | None:
    """The suite's violations, or None when the repository has no evals/ yet (an empty
    suite). Raises ReleaseError on a malformed cases.toml"""
    suite = root / SUITE
    if not suite.is_dir():
        return None
    resolve = resolves if resolves is not None else git_resolves(root)
    found = set(_case_dirs(suite, PurePosixPath()))
    violations: list[Violation] = []
    manifest = root / MANIFEST
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
    return Report(len(entries), tuple(violations))


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
        parts = text.split("/")
        if any(p in ("", ".", "..") or not _NAME.fullmatch(p) for p in parts):
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
    if not settings.graders:
        rules.append(f"no grader, in {GRADERS}/*.md or in {CASE}")
    elif kind is not Kind.FINDING and not DETERMINISTIC & set(settings.graders):
        rules.append(
            f"no deterministic grader ({', '.join(sorted(DETERMINISTIC))}); only a finding case may rest on a judge"
        )
    return rules


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

    def pick(key: str, nested: dict[str, object]) -> object:
        return front[key] if key in front else nested.get(key)

    tags = _list(pick("tags", spec), "tags")
    max_turns = _int(pick("max_turns", execution), "max_turns", RUNNER_MAX_TURNS)
    timeout = _int(pick("timeout_seconds", execution), "timeout_seconds", RUNNER_TIMEOUT_SECONDS)
    graders: list[str] = []
    listed = spec.get("graders", [])
    if not isinstance(listed, list):
        raise _Unread(f"{CASE}: graders is a list of graders")
    for number, grader in enumerate(listed, 1):
        if not isinstance(grader, dict):
            raise _Unread(f"{CASE}: grader {number} is a mapping with a type")
        graders.append(_type(grader, f"{CASE}: grader {number}"))
    folder = case / GRADERS
    if folder.is_dir():
        for file in sorted(folder.glob("*.md")):
            name = f"{GRADERS}/{file.name}"
            graders.append(_type(_frontmatter(file, name), name))
    return _Settings(tags, max_turns, timeout, tuple(graders))


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
