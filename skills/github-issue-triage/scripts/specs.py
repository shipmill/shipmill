#!/usr/bin/env python3
"""Keep a repo's feature specs: files docs/specs/NNN-<slug>.md, each merged through a pull
request before its build starts, with numbered acceptance criteria S-NNN-k.

Usage:
  specs.py new [--dir D] [--title T] SLUG
  specs.py check [--dir D] [--decisions F]
  specs.py find [--dir D] TERM...
  specs.py criteria [--dir D] NNN
  specs.py coverage [--dir D] [--root R] [--spec NNN]...
  specs.py split [--dir D] [--repo OWNER/REPO] [--group K,K...]... [--after B:A]... [--milestone T] [--json] NNN
  specs.py same-approval [--base REF] SPEC ANSWERED_HEAD HEAD
  specs.py contradictions [--base REF] [--decisions F] [--json] SPEC

A spec has a title line, a status line, and fixed sections, in this order:

  # S-007: <title>

  status: draft             (draft, approved, built, or stopped)
  serves: G-1, G-2          (the goals of docs/product.md it serves, or "quality bar")

  ## Problem
  ## Behaviour              (name touched paths and areas in backticks)
  ## Acceptance criteria    (- S-007-1: <checkable statement>, numbered from 1)
  ## Out of scope
  ## Decisions relied on    (- D-5 ..., or - none)
  ## Issues                 (- owner/repo#N: S-007-1, S-007-2: each build issue and the
                            criteria it delivers, filled in once the build issues exist)
  ## Verification           (once built: each criterion id, how it was checked on main;
                            a stopped spec may leave the section out)

new       write the next spec from D/TEMPLATE.md (or the built-in template), replacing
          S-NNN and <title>; prints the new path
check     every spec is well formed: its file name, title, and sections; criterion ids
          unique and sequential; the decisions it names exist in the log and are active;
          a built spec lists its issues and names every criterion under Verification;
          once an approved or built spec lists build issues, each criterion is assigned
          to exactly one of them, save a dropped one (its text starts "dropped in #N"),
          which needs no build issue and may be in one. When the repo has a direction,
          docs/product.md, every spec but a built one has a serves: line right after its
          status, naming goal ids the direction lists (moved sections in docs/product/
          read too) or "quality bar", and a draft or approved one names no goal the
          direction records as met or dropped (spec 106); without one, the line isn't
          checked. A draft may
          keep the template's placeholder text (D/TEMPLATE.md, or the built-in template:
          each paragraph of a section, word for word, past "- none"); an approved spec
          may not in Problem, Behaviour, Acceptance criteria, or Out of scope, and a built
          spec in no section. No folder D: "no specs", exit 0
find      specs whose Behaviour touches a TERM (a path matches a backticked path, glob,
          or directory there; any term matches as a substring of the section).
          `find $(git diff --name-only origin/main...)` lists the specs a diff touches
criteria  print one spec's acceptance criteria (NNN, 7, or S-007)
coverage  for every built spec (or each --spec, whatever its status), list each criterion
          and the tests under R (default .) that prove it. A test proves S-007-2 by its
          name (test_s007_2_..., in Go TestS007_2...) or by a comment line naming the id
          after "proves:" (several ids may follow, comma-separated). Test files are read
          as text: Python test_*.py and *_test.py; JS/TS *.test.* and *.spec.* and files
          under __tests__; Go *_test.go; every Rust .rs file. Hidden folders and
          node_modules, target, vendor, venv, dist, build are skipped, and so are the
          lines inside a Python multi-line string (a fixture, not a test). A dropped
          criterion needs no test and prints as dropped. No folder
          D (and no --spec): "no specs", exit 0
split    propose the build issues of an approved spec, for the criteria its Issues
          section doesn't assign yet, dropped ones aside: one issue per --group of criterion numbers (default:
          all of them in one), in the order given, each depending on the earlier groups
          named by --after B:A (B depends on A). Prints each issue's title and body, whose
          "Depends on #{Bk}" lines and the Issues lines to add name the issues by key
          until they are filed: replace {Bk} with each issue's number as it is created.
          --milestone T puts each in milestone T (a "milestone:" line, and a "milestone"
          key in --json); without it none has one. --json prints the same as one JSON object
same-approval
          whether a trusted answer given at a spec pull request's ANSWERED_HEAD still
          covers its HEAD (D-81): compares the pull request's own change to SPEC at each
          head, `git diff $(git merge-base REF <head>) <head> -- SPEC` (REF the default
          branch, default origin/main), so main's changes a rebase brought in don't count.
          Only format is left out: rewrapped text and whitespace (a list item's or paragraph's
          indent and a fenced code block's lines are kept as they are), the status: line, a
          section that is empty or holds exactly the template's placeholder (D/TEMPLATE.md
          at REF, or the built-in one), the same D-n ids in another shape under
          Decisions relied on, and a D-n the pull request claims (a heading its change to
          the decisions log adds, matched by its title) renumbered, with the lines citing
          it. Exit 1 prints each remaining difference by section: what changed since the
          answer. Run it in the repo's checkout
contradictions
          what one spec's Behaviour and Acceptance criteria name in code spans that the
          code at REF (default origin/main) or the decisions log lacks (spec 099): a path
          not in REF's tree (a bare file name is looked up anywhere in it; a span holding
          < > { } * ? [ # or :// is no path), a subcommand or --flag of the repo's own
          command (a [project.scripts] entry of pyproject.toml, or a script file, after a
          `uvx NAME==VERSION` or `uv run [options] python` prefix) that appears as no quoted
          string literal in its source, a D-n the log (--decisions F, default the one check
          reads, from the working tree) lacks or marks superseded, unless its line says it
          supersedes. Names on a Behaviour line starting `Adds:` are never missing; while
          the spec is not on REF, an added path or flagless command REF already has is
          `already exists`. The code is read through git at REF only, never the working
          tree. One `<spec>:<line>: <kind>: <name>: <other side>` line each, or `no
          contradictions found`; --json prints one object. check doesn't run it

Exit 0 on success (find: at least one match; same-approval: only the format changed), 1
when check (or criteria or split, for its spec) finds a problem, find matches nothing,
coverage finds a criterion with no test (or a test naming a criterion its spec lacks),
same-approval finds a change beyond format, or contradictions finds one, 2 on bad input.
Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import bisect
import difflib
import fnmatch
import json
import os
import re
import subprocess
import sys
import tokenize
from collections.abc import Callable
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any

from decisions import CANDIDATES as DECISION_LOGS
from decisions import HEADING as DECISION_HEADING
from decisions import parse as parse_log

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: [project.scripts] is read line by line instead
    tomllib = None

DEFAULT_DIR = Path("docs/specs")
NOT_SPECS = ("TEMPLATE.md", "README.md")
NAME = re.compile(r"^(\d{3,})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TITLE = re.compile(r"^# S-(\d{3,}): (\S.*)$")
SECTIONS = (
    "Problem",
    "Behaviour",
    "Acceptance criteria",
    "Out of scope",
    "Decisions relied on",
    "Issues",
    "Verification",
)
STATUS = re.compile(r"^status: (\S+)$")
# stopped (spec 106): its project was stopped; it needs no Verification and is never split
STATUSES = ("draft", "approved", "built", "stopped")
# The goals a spec serves, on the line right after its status (spec 024): goal ids, or the
# quality bar. Checked only when the repo has a direction, and never on a built spec
SERVES = re.compile(r"^serves:(.*)$")
QUALITY_BAR = "quality bar"
GOAL_ID = re.compile(r"^G-[1-9][0-9]*$")
# The direction (spec 024), read the way `shipmill product ids` reads it: each list
# section's `- <prefix>-<n>: <text>` items, a section moved to docs/product/<file>.md
# through its one `See [<section>](product/<file>.md).` line read from that file; any other
# line, such as a goal's `  measure: ...` line (spec 027) or a component goal's
# `  serves: ...` line naming its product's goals (spec 071), holds no id and is skipped
DIRECTION = Path("docs/product.md")
DIRECTION_PREFIXES = {"Users": "U", "Goals": "G", "Non-goals": "N", "Quality bar": "Q"}
DIRECTION_HEADING = re.compile(r"^(#{1,6})(?:[ \t]+(.*))?$")
DIRECTION_ITEM = re.compile(r"^- ([A-Za-z]+)-([1-9][0-9]*): \S")
DIRECTION_MOVED = re.compile(r"^See \[([^\]]+)\]\(product/([A-Za-z0-9][A-Za-z0-9_-]*\.md)\)\.$")
# The sections an approved spec must have filled in past the template's placeholders; a
# built spec must have filled in every section (Issues and Verification come last)
FILLED_WHEN_APPROVED = ("Problem", "Behaviour", "Acceptance criteria", "Out of scope")
CRITERION = re.compile(r"^- S-(\d{3,})-(\d+): (\S.*)$")
# A criterion dropped by a later change keeps its id and says so first: "dropped in #81, see
# S-007-5". It needs no test, no build issue, and a Verification line such as "dropped in #81"
DROPPED = re.compile(r"^dropped in (?:[\w.-]+/[\w.-]+)?#\d+\b")
DECISION_ITEM = re.compile(r"^- D-(\d+)\b")
ISSUE_ITEM = re.compile(r"^- ((?:[\w.-]+/[\w.-]+)?#\d+)(?::[ \t]*(.*))?$")
ASSIGNED = re.compile(r"^S-(\d{3,})-(\d+)$")
REPO = re.compile(r"^[\w.-]+/[\w.-]+$")
UNASSIGNED = "is in no build issue under Issues"
ID = re.compile(r"^(?:S-)?(\d+)$")
# same-approval (#1007, D-81): what is only format in a spec pull request's change
PREAMBLE = "(title)"  # the lines before the first section
STATUS_ANY = re.compile(r"^status:")
LIST_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]")
FENCE = re.compile(r"^[ \t]*(```|~~~)")
DECISION_ID = re.compile(r"(?<![\w-])D-(\d+)(?!\d)")
# Reports one problem at a line of the spec being parsed
ProblemSink = Callable[[int, str], None]

# Coverage: a test names the criterion it proves, S-007-2, as test_s007_2_... (group 1 the
# test, 2 the spec, 3 the criterion), or a comment line says "proves: S-007-2, S-007-3"
PY_NAME = re.compile(r"^[ \t]*(?:async[ \t]+)?def[ \t]+(test_s(\d{3,})_(\d+)(?!\d)\w*)[ \t]*\(", re.MULTILINE)
JS_NAME = re.compile(
    r"^[ \t]*(?:(?:it|test)(?:\.\w+)*[ \t]*\([ \t]*['\"`]((?:test_)?s(\d{3,})_(\d+)(?!\d)[^'\"`\n]*)"
    r"|(?:export[ \t]+)?(?:async[ \t]+)?function[ \t]+(test_s(\d{3,})_(\d+)(?!\d)\w*)[ \t]*\()",
    re.MULTILINE,
)
GO_NAME = re.compile(r"^[ \t]*func[ \t]+(Test_?[Ss](\d{3,})_(\d+)(?!\d)\w*)[ \t]*\(", re.MULTILINE)
RS_NAME = re.compile(
    r"^[ \t]*(?:pub[ \t]+)?(?:async[ \t]+)?fn[ \t]+(test_s(\d{3,})_(\d+)(?!\d)\w*)[ \t]*\(", re.MULTILINE
)
HASH_PROVES = re.compile(r"^[ \t]*#[ \t]*proves:[ \t]*(.+)$", re.MULTILINE)
SLASH_PROVES = re.compile(r"^[ \t]*//[ \t]*proves:[ \t]*(.+)$", re.MULTILINE)
PROVEN_ID = re.compile(r"S-(\d{3,})-(\d+)(?!\d)")
JS_SUFFIXES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")
SKIP_DIRS = {"node_modules", "target", "vendor", "venv", "dist", "build", "__pycache__"}
SKIP_ROOT_DIRS = {"tmp"}  # scratch space: agents' worktrees and drafts, whose tests aren't the repo's
TEMPLATE = """\
# S-NNN: <title>

status: draft

## Problem

Who needs this and what goes wrong without it, in a few sentences. Link the issue it came
from.

## Behaviour

What the feature does, as users and other tools see it: commands, flags, outputs, files,
defaults, and errors. Name every path or area it touches in backticks, such as
`src/pkg/cli.py` or `CLI flags`, so `specs.py find` lists this spec for a change there.

## Acceptance criteria

Each criterion is one checkable statement with its own id, numbered from 1. A test that
proves one names the id.

- S-NNN-1: <a statement a test can check, e.g. "tool run exits 2 when the config is missing">

## Out of scope

- <what this spec deliberately leaves out, and where it went>

## Decisions relied on

- none

## Issues

The build issues, filled in once they are filed: one `- owner/repo#N: S-NNN-1, S-NNN-2` per
line, naming the criteria that issue delivers. Each criterion belongs to exactly one.

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
"""


@dataclass
class Criterion:
    number: int
    text: str
    line: int
    end: int = 0  # its last line, past the first when it wraps

    def __post_init__(self) -> None:
        self.end = self.end or self.line

    @property
    def dropped(self) -> bool:
        return DROPPED.match(self.text) is not None


@dataclass
class BuildIssue:
    ref: str  # owner/repo#N or #N
    criteria: list[int]  # the criterion numbers it delivers
    line: int


@dataclass
class Spec:
    path: Path
    number: int
    slug: str
    title: str = ""
    status: str = ""
    status_line: int = 0
    serves: str | None = None  # the text after "serves:", None without the line
    serves_line: int = 0
    sections: dict[str, list[tuple[int, str]]] = field(default_factory=dict)
    criteria: list[Criterion] = field(default_factory=list)
    decisions: list[tuple[int, int]] = field(default_factory=list)  # (D-n, line)
    issues: list[BuildIssue] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"S-{self.number:03d}"

    def text(self, section: str) -> str:
        return "\n".join(line for _, line in self.sections.get(section, []))


class SpecError(Exception):
    pass


def spec_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise SpecError(f"no {directory}: nothing has been specified yet")
    return sorted(p for p in directory.glob("*.md") if p.name not in NOT_SPECS)


def parse(path: Path, text: str | None = None) -> tuple[Spec | None, list[str]]:
    """The spec, and every format problem found in it; text is the file's, read from path
    without it (github-ship-watch reads a spec of the default branch through git, spec 053)"""
    name = NAME.match(path.name)
    if name is None:
        return None, [f"{path}: not named NNN-<slug>.md (lowercase words joined by '-')"]
    spec = Spec(path, int(name.group(1)), name.group(2))
    problems: list[str] = []

    def problem(line: int, message: str) -> None:
        problems.append(f"{path}:{line}: {message}")

    current: str | None = None
    seen: list[str] = []
    if text is None:
        text = path.read_text(encoding="utf-8")
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            current = line[3:].strip()
            if current not in SECTIONS:
                problem(n, f"unknown section '{current}'; a spec has: {', '.join(SECTIONS)}")
            elif current in seen:
                problem(n, f"repeats the section '{current}'")
            seen.append(current)
            spec.sections.setdefault(current, [])
            continue
        if current is None:
            title = TITLE.match(line)
            status = STATUS.match(line)
            serves = SERVES.match(line)
            if serves and spec.serves is None and spec.status_line and n == spec.status_line + 1:
                spec.serves, spec.serves_line = serves.group(1).strip(), n
            elif serves:
                problem(n, "a 'serves:' line goes right after the status line, once")
            elif title and not spec.title:
                spec.title = title.group(2).strip()
                if int(title.group(1)) != spec.number:
                    problem(n, f"the title says S-{title.group(1)}, the file name {spec.id}")
            elif status and spec.title and not spec.status:
                spec.status, spec.status_line = status.group(1), n
                if spec.status not in STATUSES:
                    problem(n, f"status must be one of {', '.join(STATUSES)}, got '{spec.status}'")
            elif line.strip():
                problem(n, f"expected '# {spec.id}: <title>' and then the sections")
            continue
        spec.sections[current].append((n, line))
        wrapped = current == "Acceptance criteria" and spec.criteria and spec.criteria[-1].end == n - 1
        if line.startswith("# "):
            problem(n, "a second title line")
        elif line.startswith("- "):
            item(spec, current, n, line, problem)
        elif wrapped and line[:1] in (" ", "\t") and line.strip():
            # A criterion wrapped onto an indented line goes on
            spec.criteria[-1].text += " " + line.strip()
            spec.criteria[-1].end = n
    if not spec.title:
        problem(1, f"no title line '# {spec.id}: <title>'")
    if not spec.status:
        problem(1, f"no status line ('status: {'|'.join(STATUSES)}') after the title")
    if spec.status == "built":
        if not spec.issues:
            problem(1, "built, but lists no build issues")
        verified = {
            int(m.group(2)) for m in PROVEN_ID.finditer(spec.text("Verification")) if int(m.group(1)) == spec.number
        }
        for criterion in spec.criteria:
            if criterion.number not in verified:
                problem(1, f"built, but Verification doesn't name {spec.id}-{criterion.number}")
    for section in SECTIONS:
        if section not in seen and not (section == "Verification" and spec.status == "stopped"):
            problem(1, f"missing the section '{section}'")
    # a stopped spec may leave Verification out (spec 106); the rest keep their order
    wanted = [s for s in SECTIONS if s in seen] if spec.status == "stopped" else list(SECTIONS)
    if len(seen) == len(wanted) and set(seen) == set(wanted) and seen != wanted:
        problem(1, f"sections out of order; a spec has: {', '.join(SECTIONS)}")
    if "Acceptance criteria" in seen and not spec.criteria:
        problem(1, "no acceptance criteria")
    for expected, criterion in enumerate(spec.criteria, 1):
        if criterion.number != expected:
            problem(criterion.line, f"expected {spec.id}-{expected}; criterion ids run 1..n in order")
    none = [n for n, line in spec.sections.get("Decisions relied on", []) if line.strip() == "- none"]
    if none and spec.decisions:
        problem(none[0], "'- none' next to named decisions")
    check_assignment(spec, problem)
    return spec, problems


def item(spec: Spec, section: str, n: int, line: str, problem: ProblemSink) -> None:
    """One list item of a section that has a fixed item format"""
    if section == "Acceptance criteria":
        criterion = CRITERION.match(line)
        if criterion is None:
            problem(n, f"a criterion must read '- {spec.id}-<k>: <statement>'")
        elif int(criterion.group(1)) != spec.number:
            problem(n, f"criterion S-{criterion.group(1)}-{criterion.group(2)} in spec {spec.id}")
        else:
            spec.criteria.append(Criterion(int(criterion.group(2)), criterion.group(3).strip(), n))
    elif section == "Decisions relied on":
        decision = DECISION_ITEM.match(line)
        if decision:
            spec.decisions.append((int(decision.group(1)), n))
        elif line.strip() != "- none":
            problem(n, "a decision must read '- D-<n>' (a title may follow), or '- none'")
    elif section == "Issues":
        build_issue(spec, n, line, problem)


def build_issue(spec: Spec, n: int, line: str, problem: ProblemSink) -> None:
    """One line of the Issues section: a build issue and the criteria it delivers"""
    match = ISSUE_ITEM.match(line.strip())
    if match is None:
        problem(n, f"an issue must read '- owner/repo#N: {spec.id}-1, {spec.id}-2' (or '- #N: ...')")
        return
    numbers = []
    for name in (match.group(2) or "").split(","):
        if not name.strip():
            continue
        criterion = ASSIGNED.match(name.strip())
        if criterion is None:
            problem(n, f"{name.strip()!r} is not a criterion id; list them as {spec.id}-1, {spec.id}-2")
        elif int(criterion.group(1)) != spec.number:
            problem(n, f"names {name.strip()}, a criterion of another spec than {spec.id}")
        else:
            numbers.append(int(criterion.group(2)))
    spec.issues.append(BuildIssue(match.group(1), numbers, n))


def check_assignment(spec: Spec, problem: ProblemSink) -> None:
    """Once an approved or built spec lists its build issues, each criterion is delivered by
    exactly one of them. An approved spec with no build issues yet hasn't been split"""
    if spec.status not in ("approved", "built") or not spec.issues:
        return
    known = {c.number for c in spec.criteria}
    owner: dict[int, str] = {}
    refs: set[str] = set()
    for issue in spec.issues:
        if issue.ref in refs:
            problem(issue.line, f"lists {issue.ref} twice")
        refs.add(issue.ref)
        if not issue.criteria:
            problem(issue.line, f"{issue.ref} names no criteria; write '- {issue.ref}: {spec.id}-1, ...'")
        for number in issue.criteria:
            if number not in known:
                problem(issue.line, f"{issue.ref} names {spec.id}-{number}, which the spec lacks")
            elif number in owner:
                problem(issue.line, f"{spec.id}-{number} is in both {owner[number]} and {issue.ref}")
            else:
                owner[number] = issue.ref
    for criterion in spec.criteria:
        if criterion.number not in owner and not criterion.dropped:
            problem(criterion.line, f"{spec.id}-{criterion.number} {UNASSIGNED}")


def decision_states(given: str | None) -> dict[int, str | None] | None:
    """Each D-n in the log, mapped to the entry superseding it (None when active); None
    when there is no log"""
    path = Path(given) if given else next((p for p in DECISION_LOGS if p.is_file()), None)
    if path is None:
        return None
    if not path.is_file():
        raise SpecError(f"no decisions log at {path}")
    entries, _ = parse_log(path.read_text(encoding="utf-8"))
    return {e.number: e.fields.get("Superseded by") for e in entries}


def template(directory: Path) -> str:
    """The template `new` writes a spec from: D/TEMPLATE.md, or the built-in one"""
    path = directory / "TEMPLATE.md"
    return path.read_text(encoding="utf-8") if path.is_file() else TEMPLATE


def placeholders(text: str, spec_id: str) -> dict[str, list[list[str]]]:
    """Each section's placeholder paragraphs in the template text (runs of non-blank
    lines, S-NNN read as the spec's id), past a bare "- none", which is a real answer"""
    found: dict[str, list[list[str]]] = {}
    current: str | None = None
    paragraph: list[str] = []

    def close() -> None:
        if current in SECTIONS and paragraph and paragraph != ["- none"]:
            found.setdefault(current, []).append(list(paragraph))
        paragraph.clear()

    for line in text.replace("S-NNN", spec_id).splitlines():
        if line.startswith("## "):
            close()
            current = line[3:].strip()
        elif line.strip():
            paragraph.append(line.rstrip())
        else:
            close()
    close()
    return found


def placeholder_problems(spec: Spec, template_text: str) -> list[str]:
    """A placeholder paragraph of the template left word for word in a section the
    spec's status says is filled in"""
    if spec.status == "approved":
        sections: tuple[str, ...] = FILLED_WHEN_APPROVED
    elif spec.status == "built":
        sections = SECTIONS
    else:
        return []
    problems = []
    for section, paragraphs in placeholders(template_text, spec.id).items():
        if section not in sections:
            continue
        lines = spec.sections.get(section, [])
        body = [line.rstrip() for _, line in lines]
        for paragraph in paragraphs:
            at = next(
                (i for i in range(len(body) - len(paragraph) + 1) if body[i : i + len(paragraph)] == paragraph), None
            )
            if at is not None:
                problems.append(
                    f"{spec.path}:{lines[at][0]}: {spec.status}, but '{section}' still holds the template's "
                    f"placeholder: {paragraph[0]}"
                )
    return problems


def load(directory: Path) -> tuple[list[Spec], list[str]]:
    specs: list[Spec] = []
    problems: list[str] = []
    template_text = template(directory)
    for path in spec_files(directory):
        spec, found = parse(path)
        problems += found
        if spec is not None:
            specs.append(spec)
            problems += placeholder_problems(spec, template_text)
    numbers: dict[int, Path] = {}
    for spec in specs:
        if spec.number in numbers:
            problems.append(f"{spec.path}: {spec.id} is also {numbers[spec.number]}")
        numbers.setdefault(spec.number, spec.path)
    return specs, problems


def check_decisions(specs: list[Spec], log: dict[int, str | None] | None) -> list[str]:
    problems = []
    for spec in specs:
        for number, line in spec.decisions:
            where = f"{spec.path}:{line}"
            if log is None:
                problems.append(f"{where}: names D-{number}, but there is no decisions log")
            elif number not in log:
                problems.append(f"{where}: names D-{number}, which the decisions log lacks")
            elif log[number] is not None:
                problems.append(f"{where}: names D-{number}, superseded by {log[number]}")
    return problems


def direction_lines(root: Path) -> list[tuple[str, str]] | None:
    """Each line of the direction at root/docs/product.md under an item section, with the
    section, moved sections' files read in their place; None when the repo has no direction. A
    moved section whose file is missing is refused, since its items can't be read"""
    path = root / DIRECTION
    if not path.is_file():
        return None
    found: list[tuple[str, str]] = []
    section: str | None = None
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.rstrip()
        heading = DIRECTION_HEADING.match(line)
        if heading:
            section = (heading.group(2) or "").strip() if len(heading.group(1)) == 2 else None
            continue
        if section is None or section not in DIRECTION_PREFIXES:
            continue
        moved = DIRECTION_MOVED.match(line)
        if moved is None:
            found.append((section, line))
            continue
        linked = path.parent / "product" / moved.group(2)
        if not linked.is_file():
            raise SpecError(f"{DIRECTION}:{n}: '## {section}' moved to {linked.relative_to(root)}, which doesn't exist")
        found += [(section, moved_line.rstrip()) for moved_line in linked.read_text(encoding="utf-8").splitlines()]
    return found


def direction_ids(root: Path) -> set[str] | None:
    """Every item id the direction at root/docs/product.md lists, moved sections included,
    as `shipmill product ids` lists them; None when the repo has no direction. Its other
    rules are `shipmill product check`'s"""
    lines = direction_lines(root)
    if lines is None:
        return None
    ids: set[str] = set()
    for section, line in lines:
        ids |= direction_items(line, section)
    return ids


# A goal's end, the maintainer's record (spec 106): `. Met: <date>` or `. Dropped: <date>: <reason>`
# right after a goal of kind goal's horizon, as src/shipmill/product.py reads it; `shipmill
# product check` holds its form
GOAL_ENDED = re.compile(
    r"\. By: (?:[0-9]{4}-[0-9]{2}-[0-9]{2}|v?[0-9]+\.[0-9]+\.[0-9]+)\. (?:Met|Dropped): [0-9]{4}-[0-9]{2}-[0-9]{2}"
)


def ended_goals(root: Path) -> set[str]:
    """The goals the direction records as met or dropped (spec 106), as G-n ids"""
    ended: set[str] = set()
    for section, line in direction_lines(root) or []:
        item = DIRECTION_ITEM.match(line)
        if section == "Goals" and item is not None and GOAL_ENDED.search(line) is not None:
            ended.add(f"{item.group(1)}-{int(item.group(2))}")
    return ended


def direction_items(line: str, section: str) -> set[str]:
    """The id of a direction item on this line, when it is one of the section's prefix"""
    item = DIRECTION_ITEM.match(line)
    if item is None or item.group(1) != DIRECTION_PREFIXES[section]:
        return set()
    return {f"{item.group(1)}-{int(item.group(2))}"}


def check_serves(specs: list[Spec], ids: set[str] | None, ended: frozenset[str] = frozenset()) -> list[str]:
    """With a direction, every spec not yet built names the goals it serves, G-n ids the
    direction lists or `quality bar`, and a draft or approved one no goal in ended, the goals
    recorded as met or dropped (S-106-3); a built spec, and any spec without a direction, passes"""
    if ids is None:
        return []
    problems = []
    for spec in specs:
        if spec.status == "built":
            continue
        if spec.serves is None:
            problems.append(
                f"{spec.path}:{spec.status_line or 1}: no 'serves:' line after the status; name the goals it "
                f"serves from {DIRECTION} ('serves: G-1, G-2') or 'serves: {QUALITY_BAR}'"
            )
            continue
        where = f"{spec.path}:{spec.serves_line}"
        names = [name.strip() for name in spec.serves.split(",")]
        if names == [QUALITY_BAR]:
            continue
        if not all(names):
            problems.append(f"{where}: 'serves:' names goal ids separated by commas, or '{QUALITY_BAR}' alone")
            continue
        for name in names:
            if GOAL_ID.match(name) is None:
                problems.append(f"{where}: serves {name!r}; a spec serves goal ids (G-n) or '{QUALITY_BAR}' alone")
            elif name not in ids:
                problems.append(f"{where}: serves {name}, which {DIRECTION} doesn't list")
            elif name in ended and spec.status in ("draft", "approved"):
                problems.append(
                    f"{where}: serves {name}, which {DIRECTION} records as met or dropped; a spec still "
                    f"{spec.status} serves only a goal still open (spec 106)"
                )
    return problems


def touches(spec: Spec, term: str) -> bool:
    behaviour = spec.text("Behaviour")
    for token in re.findall(r"`([^`]+)`", behaviour):
        if term == token or fnmatch.fnmatch(term, token) or term.startswith(token.rstrip("*").rstrip("/") + "/"):
            return True
    return term.lower() in behaviour.lower()


def new(directory: Path, slug: str, title: str | None) -> int:
    if not SLUG.match(slug):
        raise SpecError(f"slug must be lowercase words joined by '-', got {slug!r}")
    existing = [NAME.match(p.name) for p in directory.glob("*.md")] if directory.is_dir() else []
    taken = [m for m in existing if m]
    clash = next((m.group(0) for m in taken if m.group(2) == slug), None)
    if clash:
        raise SpecError(f"{directory / clash} already has the slug {slug!r}")
    template_text = template(directory)
    for placeholder in ("S-NNN", "<title>"):
        if placeholder not in template_text:
            raise SpecError(f"{directory / 'TEMPLATE.md'} lacks the placeholder {placeholder!r}")
    number = max((int(m.group(1)) for m in taken), default=0) + 1
    text = template_text.replace("S-NNN", f"S-{number:03d}").replace(
        "<title>", title or slug.replace("-", " ").capitalize()
    )
    path = directory / f"{number:03d}-{slug}.md"
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(path)
    return 0


def criteria(directory: Path, wanted: str) -> int:
    match = ID.match(wanted)
    if match is None:
        raise SpecError(f"a spec is named NNN, 7, or S-007, got {wanted!r}")
    specs, _ = load(directory)
    spec = next((s for s in specs if s.number == int(match.group(1))), None)
    if spec is None:
        raise SpecError(f"no spec S-{int(match.group(1)):03d} in {directory}")
    _, problems = parse(spec.path)
    problems += placeholder_problems(spec, template(directory))
    for criterion in spec.criteria:
        print(f"{spec.id}-{criterion.number}: {criterion.text}")
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


def test_files(root: Path) -> list[tuple[Path, list[re.Pattern[str]]]]:
    """Each test file under root, with the patterns that find its proofs"""
    found = []
    for folder, dirs, files in os.walk(root):
        skip = SKIP_DIRS | SKIP_ROOT_DIRS if Path(folder) == root else SKIP_DIRS
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in skip)
        for name in sorted(files):
            path = Path(folder) / name
            if name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py")):
                found.append((path, [PY_NAME, HASH_PROVES]))
            elif name.endswith(JS_SUFFIXES) and (
                ".test." in name or ".spec." in name or "__tests__" in path.relative_to(root).parts
            ):
                found.append((path, [JS_NAME, SLASH_PROVES]))
            elif name.endswith("_test.go"):
                found.append((path, [GO_NAME, SLASH_PROVES]))
            elif name.endswith(".rs"):
                found.append((path, [RS_NAME, SLASH_PROVES]))
    return found


def string_lines(path: Path, text: str) -> set[int]:
    """The lines of a Python file that sit inside a multi-line string, past its first"""
    inside: set[int] = set()
    opened: list[int] = []
    try:
        for token in tokenize.generate_tokens(StringIO(text).readline):
            kind = tokenize.tok_name[token.type]
            if token.type == tokenize.STRING:
                inside.update(range(token.start[0] + 1, token.end[0] + 1))
            elif kind.endswith("STRING_START"):  # an f-string (3.12+) or t-string (3.14+)
                opened.append(token.start[0])
            elif kind.endswith("STRING_END") and opened:
                inside.update(range(opened.pop() + 1, token.end[0] + 1))
    except (tokenize.TokenError, SyntaxError) as exc:
        raise SpecError(f"{path}: not valid Python, so its tests can't be read: {exc}") from exc
    return inside


def proofs(root: Path) -> dict[tuple[int, int], list[str]]:
    """(spec, criterion) to the places that prove it: "path:line test_name" for a named
    test, "path:line" for a comment"""
    found: dict[tuple[int, int], list[str]] = {}
    for path, patterns in test_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        where = path.relative_to(root).as_posix()
        quoted = string_lines(path, text) if path.suffix == ".py" else set()
        for pattern in patterns:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                if line in quoted:
                    continue  # a fixture inside a multi-line string, not a test
                groups = [g for g in match.groups() if g is not None]
                if pattern in (HASH_PROVES, SLASH_PROVES):
                    ids = [(int(m.group(1)), int(m.group(2))) for m in PROVEN_ID.finditer(groups[0])]
                    for key in ids:
                        found.setdefault(key, []).append(f"{where}:{line}")
                else:
                    name, spec, criterion = groups[:3]
                    found.setdefault((int(spec), int(criterion)), []).append(f"{where}:{line} {name}")
    return found


def coverage(directory: Path, root: Path, wanted: list[str]) -> int:
    if not root.is_dir():
        raise SpecError(f"no folder {root} to look for tests in")
    if not wanted and not directory.is_dir():
        print("no specs")
        return 0
    specs, problems = load(directory)
    numbers = []
    for name in wanted:
        match = ID.match(name)
        if match is None:
            raise SpecError(f"a spec is named NNN, 7, or S-007, got {name!r}")
        numbers.append(int(match.group(1)))
    missing_specs = sorted(set(numbers) - {s.number for s in specs})
    if missing_specs:
        raise SpecError(f"no spec {', '.join(f'S-{n:03d}' for n in missing_specs)} in {directory}")
    chosen = [s for s in specs if s.number in numbers] if numbers else [s for s in specs if s.status == "built"]
    if not chosen:
        print("no built specs")
        return 0
    found = proofs(root)
    failed = False
    for spec in chosen:
        print(f"{spec.id}: {spec.title} ({spec.status or 'no status'})")
        for problem in problems:
            if problem.startswith(f"{spec.path}:"):
                print(f"  {problem}")
                failed = True
        for criterion in spec.criteria:
            places = sorted(found.get((spec.number, criterion.number), []))
            print(f"  {spec.id}-{criterion.number}: {criterion.text}")
            for place in places:
                print(f"    {place}")
            if not places and criterion.dropped:
                print("    dropped, no test needed")
            elif not places:
                print("    no test proves it")
                failed = True
        known = {c.number for c in spec.criteria}
        for (number, criterion), places in sorted(found.items()):
            if number == spec.number and criterion not in known:
                print(f"  {spec.id}-{criterion}: no such criterion, yet named by {', '.join(places)}")
                failed = True
    return 1 if failed else 0


def criterion_number(spec: Spec, name: str) -> int:
    """A criterion named as 3 or S-007-3"""
    text = name.strip()
    full = ASSIGNED.match(text)
    if full and int(full.group(1)) == spec.number:
        return int(full.group(2))
    if text.isdigit():
        return int(text)
    raise SpecError(f"a criterion of {spec.id} is named k or {spec.id}-k, got {text!r}")


def groups_of(spec: Spec, groups: list[str], unassigned: list[int], assigned: dict[int, str]) -> list[list[int]]:
    """Each --group's criterion numbers (default: every unassigned criterion in one), each
    unassigned criterion in exactly one"""
    chosen = [[criterion_number(spec, n) for n in g.split(",") if n.strip()] for g in groups] or [unassigned]
    known = {c.number for c in spec.criteria}
    dropped = {c.number for c in spec.criteria if c.dropped}
    seen: dict[int, int] = {}
    for k, group in enumerate(chosen, 1):
        if not group:
            raise SpecError(f"--group {k} names no criteria")
        for number in group:
            if number not in known:
                raise SpecError(f"--group {k}: {spec.id} has no criterion {spec.id}-{number}")
            if number in dropped:
                raise SpecError(f"--group {k}: {spec.id}-{number} is dropped; no build issue delivers it")
            if number in assigned:
                raise SpecError(f"--group {k}: {spec.id}-{number} is already in {assigned[number]}")
            if number in seen:
                raise SpecError(f"{spec.id}-{number} is in both --group {seen[number]} and --group {k}")
            seen[number] = k
    left = [n for n in unassigned if n not in seen]
    if left:
        raise SpecError(f"{', '.join(f'{spec.id}-{n}' for n in left)} in no --group; each criterion needs one")
    return chosen


def dependencies(after: list[str], count: int) -> dict[int, list[int]]:
    """Each build issue (1..count) to the earlier ones it depends on, from --after B:A"""
    depends: dict[int, list[int]] = {k: [] for k in range(1, count + 1)}
    for edge in after:
        match = re.match(r"^(\d+):(\d+)$", edge.strip())
        if match is None:
            raise SpecError(f"--after is B:A (build issue B depends on A, numbered as the groups), got {edge!r}")
        later, earlier = int(match.group(1)), int(match.group(2))
        if later not in depends or earlier not in depends:
            raise SpecError(f"--after {edge}: the groups are numbered 1 to {count}")
        if earlier >= later:
            raise SpecError(f"--after {edge}: a build issue depends only on an earlier group; give them in build order")
        if earlier not in depends[later]:
            depends[later].append(earlier)
    return {k: sorted(v) for k, v in depends.items()}


def task_graph(
    spec: Spec, groups: list[str], after: list[str], repo: str | None, milestone: str | None = None
) -> list[dict[str, Any]]:
    """The build issues proposed for an approved spec's criteria that no build issue has yet,
    in the order to file them. Each names the others by key, {B1}, until they have numbers,
    and carries the feature issue's milestone when one is given"""
    if spec.status != "approved":
        raise SpecError(f"{spec.id} is {spec.status or 'without a status'}; only an approved spec is split")
    if repo is not None and REPO.match(repo) is None:
        raise SpecError(f"--repo must be owner/repo, got {repo!r}")
    if milestone is not None and (not milestone.strip() or milestone != milestone.strip() or "\n" in milestone):
        raise SpecError(f"--milestone must be a milestone's title, one line without outer spaces, got {milestone!r}")
    assigned = {n: issue.ref for issue in spec.issues for n in issue.criteria}
    unassigned = [c.number for c in spec.criteria if c.number not in assigned and not c.dropped]
    chosen = groups_of(spec, groups, unassigned, assigned)
    depends = dependencies(after, len(chosen))
    texts = {c.number: c.text for c in spec.criteria}
    prefix = repo or ""
    issues = []
    for k, group in enumerate(chosen, 1):
        ids = [f"{spec.id}-{n}" for n in group]
        body = [
            f"Builds part of spec {spec.id}, `{spec.path.as_posix()}`: the acceptance criteria below. Each needs a "
            f"test that names its id (`test_s{spec.number:03d}_<k>_...`, or a `proves: {ids[0]}` comment line).",
            "",
            *(f"- {spec.id}-{n}: {texts[n]}" for n in group),
        ]
        if depends[k]:
            body += ["", *(f"Depends on {prefix}#{{B{d}}}" for d in depends[k])]
        issue: dict[str, Any] = {
            "key": f"B{k}",
            "title": f"{spec.title} ({', '.join(ids)})",
            "body": "\n".join(body) + "\n",
            "criteria": ids,
            "depends_on": [f"B{d}" for d in depends[k]],
            "issues_line": f"- {prefix}#{{B{k}}}: {', '.join(ids)}",
        }
        if milestone is not None:
            issue["milestone"] = milestone
        issues.append(issue)
    return issues


def split(
    directory: Path,
    wanted: str,
    groups: list[str],
    after: list[str],
    repo: str | None,
    as_json: bool,
    milestone: str | None = None,
) -> int:
    match = ID.match(wanted)
    if match is None:
        raise SpecError(f"a spec is named NNN, 7, or S-007, got {wanted!r}")
    specs, _ = load(directory)
    spec = next((s for s in specs if s.number == int(match.group(1))), None)
    if spec is None:
        raise SpecError(f"no spec S-{int(match.group(1)):03d} in {directory}")
    if spec.status == "stopped":  # S-106-20: its project was stopped; nothing is built for it
        raise SpecError(f"{spec.id} is stopped; a stopped spec is never split into build issues")
    # A criterion in no build issue yet is what split is for; any other problem stops it
    problems = [p for p in parse(spec.path)[1] if not p.endswith(UNASSIGNED)]
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{spec.id} must pass check before it is split", file=sys.stderr)
        return 1
    open_criteria = [c for c in spec.criteria if not c.dropped]
    if spec.status == "approved" and all(any(c.number in i.criteria for i in spec.issues) for c in open_criteria):
        if groups or after:
            raise SpecError(f"every criterion of {spec.id} is in a build issue already; there is nothing to group")
        print(f"{spec.id}: every criterion is in a build issue already")
        return 0
    issues = task_graph(spec, groups, after, repo, milestone)
    if as_json:
        print(json.dumps({"spec": spec.id, "path": spec.path.as_posix(), "issues": issues}, indent=2))
        return 0
    print(f"{spec.id}: {len(issues)} build issue(s) for {spec.path.as_posix()}, to file in this order.")
    print("Replace each {Bk} with that issue's number once it is filed.")
    for issue in issues:
        depends = ", ".join(issue["depends_on"]) or "nothing"
        on = f"milestone: {issue['milestone']}\n" if "milestone" in issue else ""
        print(f"\n=== {issue['key']} (depends on {depends})\ntitle: {issue['title']}\n{on}\n{issue['body']}", end="")
    print("\nThe spec's Issues section, once they are filed:\n")
    for issue in issues:
        print(issue["issues_line"])
    return 0


def git(*args: str) -> str:
    """git's output in the current directory; a failure is bad input"""
    done = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", check=False)
    if done.returncode != 0:
        raise SpecError(f"git {' '.join(args)}: {done.stderr.strip() or f'exit {done.returncode}'}")
    return done.stdout


def commit_of(ref: str) -> str:
    """The commit a ref names"""
    if not ref or ref.startswith("-"):
        raise SpecError(f"unknown commit {ref!r}")
    done = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if done.returncode != 0:
        raise SpecError(f"unknown commit {ref!r}")
    return done.stdout.strip()


def file_at(commit: str, path: str) -> str | None:
    """A file's text at a commit, None when the commit hasn't it"""
    done = subprocess.run(["git", "cat-file", "-e", f"{commit}:{path}"], capture_output=True, check=False)
    return git("show", f"{commit}:{path}") if done.returncode == 0 else None


def blocks(text: str) -> dict[str, list[str]]:
    """Each section's paragraphs and list items, whitespace folded so that a rewrapped one
    reads the same, under PREAMBLE before the first section; the status line is left out.
    A block keeps its first line's indent, so a list item moved in or out of a nested list
    differs, and a fenced code block's lines are kept as they are, indent and all"""
    found: dict[str, list[str]] = {PREAMBLE: []}
    current = PREAMBLE
    block: list[str] = []
    fence = ""

    def close() -> None:
        if block:
            first = block[0].expandtabs(4)
            indent = first[: len(first) - len(first.lstrip())]
            found[current].append(indent + " ".join(" ".join(block).split()))
        block.clear()

    for line in text.splitlines():
        opened = FENCE.match(line)
        if fence:
            if line.strip():
                found[current].append(line.rstrip())
            if opened and opened.group(1) == fence:
                fence = ""
        elif opened:
            close()
            fence = opened.group(1)
            found[current].append(line.rstrip())
        elif line.startswith("## "):
            close()
            current = line[3:].strip()
            found.setdefault(current, [])
        elif not line.strip() or (current == PREAMBLE and STATUS_ANY.match(line)):
            close()
        else:
            if LIST_ITEM.match(line):
                close()
            block.append(line)
    close()
    return found


def format_free(text: str, placeholder: dict[str, list[str]]) -> dict[str, list[str]]:
    """The spec's blocks past what is only format: a section empty or holding exactly the
    template's placeholder counts as absent, and Decisions relied on as the D-n ids it names"""
    found = blocks(text)
    for section, body in found.items():
        if section == "Decisions relied on":
            found[section] = [f"D-{n}" for n in sorted({int(n) for n in DECISION_ID.findall(" ".join(body))})]
        elif body == placeholder.get(section, []):
            found[section] = []
    return found


def claimed(base: str, head: str, read: Callable[[str, str], str | None] = file_at) -> dict[int, str]:
    """The decisions (D-n to title) the log has at head and not at its merge base: the ones
    the pull request claims; read(commit, path) is a file's text at a commit, None without it
    (pr_gate.py reads them from its checkout)"""
    for log in DECISION_LOGS:
        text = read(head, log.as_posix())
        if text is None:
            continue
        before = {m.group(1) for m in map(DECISION_HEADING.match, (read(base, log.as_posix()) or "").splitlines()) if m}
        added = (m for m in map(DECISION_HEADING.match, text.splitlines()) if m and m.group(1) not in before)
        return {int(m.group(1)): m.group(2).strip() for m in added}
    return {}


def renumbering(answered: dict[int, str], now: dict[int, str]) -> dict[int, int]:
    """Each D-n the pull request claimed at the answer, to the number the same claim (by its
    title, one of a kind on both sides) has now, when it changed"""
    moved = {}
    for number, title in answered.items():
        then = [n for n, t in answered.items() if t == title]
        later = [n for n, t in now.items() if t == title]
        if len(then) == len(later) == 1 and later[0] != number:
            moved[number] = later[0]
    return moved


def change(before: list[str], after: list[str]) -> tuple[list[str], list[str]]:
    """The blocks a patch from before to after removes, and the ones it adds"""
    removed: list[str] = []
    added: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=before, b=after, autojunk=False).get_opcodes():
        if tag != "equal":
            removed += before[i1:i2]
            added += after[j1:j2]
    return removed, added


def minus(items: list[str], taken: list[str]) -> list[str]:
    """items without taken, each taken once, in items' order"""
    left = list(taken)
    kept = []
    for item in items:
        if item in left:
            left.remove(item)
        else:
            kept.append(item)
    return kept


def same_approval(path: str, answered_ref: str, head_ref: str, base_ref: str) -> int:
    name = NAME.match(Path(path).name)
    if name is None or Path(path).name in NOT_SPECS or Path(path).is_absolute():
        raise SpecError(f"{path} is not a spec: a spec is docs/specs/NNN-<slug>.md, relative to the repo")
    answered, head, base = commit_of(answered_ref), commit_of(head_ref), commit_of(base_ref)
    texts = {}
    for ref, commit in ((answered_ref, answered), (head_ref, head)):
        text = file_at(commit, path)
        if text is None:
            raise SpecError(f"{path} is not a spec at {ref}: the commit hasn't the file")
        texts[ref] = text
    answered_base = git("merge-base", base, answered).strip()
    head_base = git("merge-base", base, head).strip()
    spec_id = f"S-{int(name.group(1)):03d}"
    # the default branch's template, never the pull request's own: its head could make any
    # section's text the placeholder and so drop it
    template_text = file_at(base, (Path(path).parent / "TEMPLATE.md").as_posix()) or TEMPLATE
    placeholder = blocks(template_text.replace("S-NNN", spec_id))
    moved = renumbering(claimed(answered_base, answered), claimed(head_base, head))
    answered_text = DECISION_ID.sub(lambda m: f"D-{moved.get(int(m.group(1)), int(m.group(1)))}", texts[answered_ref])
    then = (format_free(file_at(answered_base, path) or "", placeholder), format_free(answered_text, placeholder))
    now = (format_free(file_at(head_base, path) or "", placeholder), format_free(texts[head_ref], placeholder))
    names = [s for s in (PREAMBLE, *SECTIONS) if any(s in side for side in (*then, *now))]
    names += sorted({s for side in (*then, *now) for s in side} - set(names))
    differences: dict[str, list[str]] = {}
    for section in names:
        removed_then, added_then = change(then[0].get(section, []), then[1].get(section, []))
        removed_now, added_now = change(now[0].get(section, []), now[1].get(section, []))
        if (removed_then, added_then) == (removed_now, added_now):
            continue
        gone = minus(added_then, added_now) + minus(removed_now, removed_then)
        new = minus(added_now, added_then) + minus(removed_then, removed_now)
        lines = [f"  - {block}" for block in gone] + [f"  + {block}" for block in new]
        differences[section] = lines or ["  the same lines, in another order"]
    if not differences:
        print(
            f"{path}: the pull request's change is the same at {head_ref} as at {answered_ref}; only its format changed"
        )
        return 0
    print(f"{path}: changed since the answer, at {answered_ref}, to {head_ref} (- at the answer, + now):")
    for section, lines in differences.items():
        print(f"## {section}")
        for line in lines:
            print(line)
    return 1


# contradictions (spec 099): what a spec's Behaviour and Acceptance criteria name in code spans
# that the code at REF or the decisions log lacks
CHECKED_SECTIONS = ("Behaviour", "Acceptance criteria")
SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)
ADDS = "Adds:"
NOT_A_PATH = ("<", ">", "{", "}", "*", "?", "[", "#", "://")
# A name, a dot, and a file's extension, so that a code name (`Policy.parse`), a host
# (`github.com`), or a version (`0.19.0`, `X.Y.Z`) reads as no path
EXTENSION = re.compile(
    r"^.+\.(?:md|mdx|rst|txt|py|pyi|json|jsonl|toml|ya?ml|lock|cfg|ini|conf|env|sh|bash|zsh|ps1|[cm]?js|jsx|"
    r"[cm]?ts|tsx|vue|svelte|html|s?css|svg|png|jpe?g|gif|ico|pdf|xml|plist|[ct]sv|sql|log|t?gz|tar|zip|whl|"
    r"rs|go|mod|sum|rb|pl|php|lua|java|kt|swift|[ch]|cc|[ch]pp|cs|tf|hcl|pem|crt|patch|diff|tmpl|j2|ipynb|"
    r"service|timer)$",
    re.IGNORECASE,
)
OUTSIDE = ("~", "/")  # a home or absolute path: never in the repo's tree
UVX_PIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]*\])?==\S+$")
PYTHONS = ("python", "python3")
SUBCOMMAND = re.compile(r"^[a-z][a-z0-9-]*$")
FLAG = re.compile(r"(?<![\w-])(--[a-z0-9][a-z0-9-]*)")
SCRIPT_SUFFIXES = (".py", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl")
EXECUTABLE = "100755"
SUPERSEDE = re.compile(r"supersed", re.IGNORECASE)
SCRIPTS_TABLE = re.compile(r"^\s*\[\s*project\.scripts\s*\]\s*(?:#.*)?$")
TABLE_HEADER = re.compile(r"^\s*\[")
SCRIPT_ENTRY = re.compile(r"^\s*[\"']?([A-Za-z0-9_.-]+)[\"']?\s*=\s*(?:\"([^\"\\]*)\"|'([^']*)')\s*(?:#.*)?$")


@dataclass
class Finding:
    line: int
    kind: str
    name: str
    other: str


@dataclass
class Span:
    line: int
    text: str
    adds: bool  # on a Behaviour line starting `Adds:`


@dataclass
class Command:
    word: str  # the command as the span writes it
    subcommand: str | None
    flags: list[str]


class Tree:
    """The files of a commit, read through git: never the working tree"""

    def __init__(self, commit: str, base: str) -> None:
        self.commit, self.base = commit, base
        self.modes: dict[str, str] = {}
        for entry in git("ls-tree", "-r", "--full-tree", "-z", commit).split("\0"):
            if not entry:
                continue
            meta, path = entry.split("\t", 1)
            self.modes[path] = meta.split()[0]
        self.names: dict[str, list[str]] = {}
        for path in sorted(self.modes):
            self.names.setdefault(path.rsplit("/", 1)[-1], []).append(path)
        self.found: dict[tuple[str, tuple[str, ...]], bool] = {}

    def has(self, path: str) -> bool:
        """A path span: a file, or a folder when it ends in /, from the top or from any folder
        (a skill's `references/x.md`); a bare file name anywhere"""
        if "/" not in path:
            return path in self.names
        if path in self.modes:
            return True
        within = "/" + path
        if path.endswith("/"):
            return any(("/" + p).find(within) >= 0 for p in self.modes)
        return any(p.endswith(within) for p in self.modes)

    def quoted(self, word: str, sources: tuple[str, ...]) -> bool:
        """Whether word appears as a quoted string literal in any of the sources at the commit"""
        key = (word, sources)
        if key not in self.found:
            done = subprocess.run(
                ["git", "grep", "-q", "-F", "-e", f'"{word}"', "-e", f"'{word}'", self.commit, "--", *sources],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            if done.returncode not in (0, 1):
                raise SpecError(f"git grep at {self.base}: {done.stderr.strip() or f'exit {done.returncode}'}")
            self.found[key] = done.returncode == 0
        return self.found[key]


def project_scripts(text: str) -> dict[str, str]:
    """The [project.scripts] table of a pyproject.toml: each command to its entry point"""
    if tomllib is not None:
        try:
            table = tomllib.loads(text).get("project", {}).get("scripts", {})
        except tomllib.TOMLDecodeError as exc:
            raise SpecError(f"pyproject.toml is not valid TOML: {exc}") from exc
        return {str(k): str(v) for k, v in table.items()}
    return project_scripts_310(text)


def project_scripts_310(text: str) -> dict[str, str]:
    """[project.scripts] read line by line on Python 3.10, which has no tomllib: plain
    `name = "module:function"` lines, as decisions.py reads its table"""
    scripts: dict[str, str] = {}
    inside = False
    for line in text.splitlines():
        if TABLE_HEADER.match(line):
            inside = SCRIPTS_TABLE.match(line) is not None
            continue
        entry = SCRIPT_ENTRY.match(line) if inside else None
        if entry:
            scripts[entry.group(1)] = entry.group(2) if entry.group(2) is not None else entry.group(3)
    return scripts


def entry_sources(tree: Tree, entry: str) -> tuple[str, ...]:
    """The files of an entry point's top-level package at the commit: its folder, or its module"""
    package = entry.split(":", 1)[0].split(".", 1)[0].strip()
    for root in ("", "src/"):
        if f"{root}{package}/__init__.py" in tree.modes:
            return (f"{root}{package}/",)
    return tuple(f"{root}{package}.py" for root in ("", "src/") if f"{root}{package}.py" in tree.modes)


def is_path(text: str) -> bool:
    """A span that names a path of the repo: a / and a file extension or a trailing /, or a
    bare file name with a file extension; never a placeholder or a pattern, nor a path outside
    the repo (`~/...`, `/...`)"""
    if not text.strip("./") or any(c.isspace() for c in text) or any(mark in text for mark in NOT_A_PATH):
        return False
    if text.startswith(OUTSIDE):
        return False
    return text.endswith("/") or EXTENSION.match(text.rsplit("/", 1)[-1]) is not None


def command_of(words: list[str]) -> Command | None:
    """The command a span's words run, past a `uvx NAME==VERSION` or `uv run [options]
    python` prefix: its first word, the first word after it that reads as a subcommand, and
    its --flags"""
    if len(words) >= 2 and words[0] == "uvx" and UVX_PIN.match(words[1]):
        words = [words[1].split("==", 1)[0].split("[", 1)[0], *words[2:]]  # uvx NAME==VERSION runs NAME
    elif words[:2] == ["uv", "run"]:
        words = words[2:]
        python = next((i for i, w in enumerate(words) if w in PYTHONS), None)
        if python is not None and (python == 0 or words[0].startswith("-")):
            words = words[python + 1 :]  # uv run [options] python
        else:
            while words and words[0].startswith("-"):
                words = words[1:]
    if not words or words[0].startswith("-"):
        return None
    rest = words[1:]
    subcommand = next((w for w in rest if SUBCOMMAND.match(w)), None)
    return Command(words[0], subcommand, FLAG.findall(" ".join(rest)))


def command_sources(tree: Tree, word: str, scripts: dict[str, str]) -> tuple[str, ...]:
    """The source files of the repo's own command a word names at the commit, none when it
    is another tool's: a [project.scripts] entry's package, or a script file by path or name"""
    if word in scripts:
        return entry_sources(tree, scripts[word])
    path = word.removeprefix("./")
    if "/" not in path:  # a bare name is a script's file name, never a tool's: an executable `gh` stub is not gh
        return tuple(tree.names.get(path, [])) if path.endswith(SCRIPT_SUFFIXES) else ()
    script = path in tree.modes and (path.endswith(SCRIPT_SUFFIXES) or tree.modes[path] == EXECUTABLE)
    return (path,) if script else ()


def spans(spec: Spec) -> list[Span]:
    """The inline code spans of the Behaviour and the Acceptance criteria, at the line each starts"""
    found: list[Span] = []
    for section in CHECKED_SECTIONS:
        lines = spec.sections.get(section, [])
        starts: list[int] = []
        offset = 0
        for _, line in lines:
            starts.append(offset)
            offset += len(line) + 1
        text = "\n".join(line for _, line in lines)
        adds = {n for n, line in lines if section == "Behaviour" and line.startswith(ADDS)}
        for match in SPAN.finditer(text):
            index = bisect.bisect_right(starts, match.start(2)) - 1
            content = match.group(2)
            if "\n\n" in content:
                continue  # a stray backtick, not a span across a paragraph
            stripped = content[1:-1] if len(content) > 2 and content[0] == content[-1] == " " else content
            found.append(Span(lines[index][0], stripped.strip(), lines[index][0] in adds))
    return found


def decision_log(given: str | None) -> tuple[str, dict[int, tuple[str, int] | None]] | None:
    """The decisions log, read from the working tree so a D-n the spec pull request adds
    counts: its path, and each D-n to its Superseded by value and that line (None when
    active); None without a log"""
    path = Path(given) if given else next((p for p in DECISION_LOGS if p.is_file()), None)
    if path is None:
        return None
    if not path.is_file():
        raise SpecError(f"no decisions log at {path}")
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    entries, _ = parse_log(text)
    states: dict[int, tuple[str, int] | None] = {}
    for k, entry in enumerate(entries):
        end = entries[k + 1].line - 1 if k + 1 < len(entries) else len(lines)
        superseded = entry.fields.get("Superseded by")
        at = next((n for n in range(entry.line, end + 1) if lines[n - 1].startswith("- Superseded by:")), entry.line)
        states[entry.number] = (superseded, at) if superseded is not None else None
    return path.as_posix(), states


def decision_findings(spec: Spec, log: tuple[str, dict[int, tuple[str, int] | None]] | None) -> list[Finding]:
    """Each D-n the Behaviour or a criterion cites that the log lacks or marks superseded; a
    line that says it supersedes may name the rule it replaces"""
    findings = []
    for section in CHECKED_SECTIONS:
        for n, line in spec.sections.get(section, []):
            if SUPERSEDE.search(line):
                continue
            for number in dict.fromkeys(int(m.group(1)) for m in DECISION_ID.finditer(line)):
                name = f"D-{number}"
                if log is None:
                    findings.append(Finding(n, "missing decision", name, "there is no decisions log"))
                elif number not in log[1]:
                    findings.append(Finding(n, "missing decision", name, f"not in {log[0]}"))
                elif (state := log[1][number]) is not None:
                    findings.append(
                        Finding(n, "superseded decision", name, f"{log[0]}:{state[1]}: Superseded by: {state[0]}")
                    )
    return findings


def name_findings(spec: Spec, rel: str | None, tree: Tree) -> list[Finding]:
    """The paths, commands, and flags the spec's spans name that the tree lacks, and while
    the spec is not on the tree, the ones its `Adds:` lines name that the tree already has"""
    base = tree.base
    pyproject = file_at(tree.commit, "pyproject.toml") if "pyproject.toml" in tree.modes else None
    scripts = project_scripts(pyproject) if pyproject is not None else {}
    found = spans(spec)
    added_paths: set[str] = set()
    added_words: set[str] = set()
    for span in found:
        if not span.adds:
            continue
        if is_path(span.text):
            added_paths.add(span.text.removeprefix("./"))
        command = command_of(span.text.split())
        if command is not None:
            added_paths.add(command.word.removeprefix("./"))
            added_words.update(w for w in (command.subcommand, *command.flags) if w)
    on_tree = rel is not None and rel in tree.modes
    findings = []
    for span in found:
        if is_path(span.text):
            path = span.text.removeprefix("./")
            if span.adds and not on_tree and tree.has(path):
                findings.append(Finding(span.line, "already exists", span.text, f"{path} at {base}"))
            elif not span.adds and path not in added_paths and not tree.has(path):
                findings.append(Finding(span.line, "missing path", span.text, f"not in {base}"))
        command = command_of(span.text.split())
        sources = command_sources(tree, command.word, scripts) if command is not None else ()
        if command is None or not sources:
            continue
        label = ", ".join(sources)
        sub = command.subcommand
        if span.adds:
            if not on_tree and sub and not command.flags and tree.quoted(sub, sources):
                name = f"{command.word} {sub}"
                findings.append(Finding(span.line, "already exists", name, f'"{sub}" in {label} at {base}'))
            continue
        if sub and sub not in added_words and not tree.quoted(sub, sources):
            name = f"{command.word} {sub}"
            findings.append(Finding(span.line, "missing command", name, f'no "{sub}" in {label} at {base}'))
        for flag in dict.fromkeys(command.flags):
            if flag not in added_words and not tree.quoted(flag, sources):
                findings.append(Finding(span.line, "missing flag", flag, f'no "{flag}" in {label} at {base}'))
    return findings


def repo_path(path: Path) -> str | None:
    """The spec's path relative to the repo's top level, None outside it"""
    top = Path(git("rev-parse", "--show-toplevel").strip())
    try:
        return path.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        return None


def contradictions(given: str, base: str, decisions: str | None, as_json: bool) -> int:
    path = Path(given)
    if not path.is_file():
        raise SpecError(f"no spec file {given}")
    spec, problems = parse(path)
    if spec is None:
        raise SpecError(problems[0])
    tree = Tree(commit_of(base), base)
    findings = decision_findings(spec, decision_log(decisions)) + name_findings(spec, repo_path(path), tree)
    findings.sort(key=lambda f: f.line)
    shown = path.as_posix()
    if as_json:
        print(json.dumps({"spec": shown, "base": base, "findings": [vars(f) for f in findings]}, indent=2))
    elif findings:
        for f in findings:
            print(f"{shown}:{f.line}: {f.kind}: {f.name}: {f.other}")
    else:
        print("no contradictions found")
    return 1 if findings else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("new", "check", "find", "criteria", "coverage", "split"):
        p = sub.add_parser(name)
        p.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="the specs folder (default: docs/specs)")
        if name == "new":
            p.add_argument("--title", help="the spec's title (default: from the slug)")
            p.add_argument("slug", metavar="SLUG")
        if name == "check":
            p.add_argument("--decisions", help="the decisions log (default: DECISIONS.md or docs/decisions.md)")
        if name == "find":
            p.add_argument("terms", nargs="+", metavar="TERM")
        if name == "criteria":
            p.add_argument("spec", metavar="NNN")
        if name == "coverage":
            p.add_argument("--root", type=Path, default=Path("."), help="where the tests are (default: .)")
            p.add_argument("--spec", action="append", default=[], metavar="NNN", help="check this spec, built or not")
        if name == "split":
            p.add_argument("--repo", metavar="OWNER/REPO", help="name the issues OWNER/REPO#N (default: #N)")
            p.add_argument("--group", action="append", default=[], metavar="K,K", help="one build issue's criteria")
            p.add_argument("--after", action="append", default=[], metavar="B:A", help="build issue B depends on A")
            p.add_argument("--json", action="store_true", help="print the task graph as one JSON object")
            p.add_argument("--milestone", metavar="TITLE", help="put every build issue in this milestone")
            p.add_argument("spec", metavar="NNN")
    p = sub.add_parser("same-approval")
    p.add_argument("--base", default="origin/main", help="the default branch (default: origin/main)")
    p.add_argument("spec", metavar="SPEC", help="the spec file, docs/specs/NNN-<slug>.md")
    p.add_argument("answered", metavar="ANSWERED_HEAD", help="the pull request's head when the answer was given")
    p.add_argument("head", metavar="HEAD", help="its head now")
    p = sub.add_parser("contradictions")
    p.add_argument("--base", default="origin/main", help="the code to read, through git (default: origin/main)")
    p.add_argument("--decisions", help="the decisions log (default: DECISIONS.md or docs/decisions.md)")
    p.add_argument("--json", action="store_true", help="print the findings as one JSON object")
    p.add_argument("spec", metavar="SPEC", help="the spec file, docs/specs/NNN-<slug>.md")
    args = parser.parse_args()
    try:
        if args.command == "same-approval":
            return same_approval(args.spec, args.answered, args.head, args.base)
        if args.command == "contradictions":
            return contradictions(args.spec, args.base, args.decisions, args.json)
        if args.command == "new":
            return new(args.dir, args.slug, args.title)
        if args.command == "criteria":
            return criteria(args.dir, args.spec)
        if args.command == "coverage":
            return coverage(args.dir, args.root, args.spec)
        if args.command == "split":
            return split(args.dir, args.spec, args.group, args.after, args.repo, args.json, args.milestone)
        if args.command == "check" and not args.dir.is_dir():
            print("no specs")
            return 0
        specs, problems = load(args.dir)
        if args.command == "check":
            problems += check_decisions(specs, decision_states(args.decisions))
            problems += check_serves(specs, direction_ids(Path(".")), frozenset(ended_goals(Path("."))))
            for problem in problems:
                print(problem)
            return 1 if problems else 0
        found = [s for s in specs if any(touches(s, t) for t in args.terms)]
        for spec in found:
            print(f"{spec.id}: {spec.title}  ({spec.path})")
        return 0 if found else 1
    except (SpecError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
