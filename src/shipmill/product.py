"""The product's direction, docs/product.md (spec 024): the mission, users, goals, non-goals,
and quality bar the agents work toward. Its grammar is fixed so code reads it without a model:
a level-one heading naming the product, then the five sections in order, the four list
sections holding only `- <prefix>-<n>: <text>` items. A section may move to its own file
under docs/product/ through a single `See [<section>](product/<file>.md).` line. A goal may
carry one measure on the line right after it, `  measure: <metric> <comparison> <target>`
(spec 027). Only the maintainer merges a change to it (D-34); the edit commands at the end
write one item line, or a goal's measure line, in the working tree, never a commit. `check`
and `read` also read it as committed at a git ref (spec 034), so the watch checks the default
branch's direction rather than whatever the checkout holds"""

import posixpath
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from shipmill import cli_command
from shipmill.errors import ReleaseError
from shipmill.gitrepo import Git
from shipmill.lineedit import Document, LineText, history_numbers

DIRECTION = Path("docs/product.md")
_MOVED_DIR = "product"  # moved sections live in docs/product/, linked relative to docs/

_HEADING = re.compile(r"^(?P<hashes>#{1,6})(?:[ \t]+(?P<title>.*))?$")
_ITEM = re.compile(r"^- (?P<prefix>[A-Za-z]+)-(?P<number>[1-9][0-9]*): (?P<text>\S.*)$")
_ID = re.compile(r"^(?P<prefix>[A-Z])-(?P<number>[1-9][0-9]*)$")
_SEE = re.compile(r"^See \[")
_MOVED = re.compile(r"^See \[(?P<label>[^\]]+)\]\(product/(?P<file>[A-Za-z0-9][A-Za-z0-9_-]*\.md)\)\.$")
_MEASURE_LIKE = re.compile(r"^\s*measure:")  # any line that tries to be a measure line
_MEASURE_LINE = re.compile(r"^  measure: (?P<text>\S.*)$")
_MEASURE_PARTS = re.compile(r"^(?P<metric>\S+) (?P<comparison>\S+) (?P<target>\S+)$")
_TARGET = re.compile(r"^(?P<number>[0-9]+(?:\.[0-9]+)?)(?P<unit>/week|h|d|%)$")
_MEASURE_FORM = "`  measure: <metric> <comparison> <target>`"


class Unit(StrEnum):
    """The unit a measure's target is held in, the one metrics.py reports its value in"""

    HOURS = "hours"
    RATIO = "ratio"
    PER_WEEK = "per week"

    @property
    def forms(self) -> str:
        """How a target in this unit is written"""
        return _UNIT_FORMS[self]


_UNIT_FORMS = {Unit.HOURS: "`<n>h` or `<n>d`", Unit.RATIO: "`<n>%`", Unit.PER_WEEK: "`<n>/week`"}
_SUFFIX_UNITS = {"h": Unit.HOURS, "d": Unit.HOURS, "%": Unit.RATIO, "/week": Unit.PER_WEEK}


class Metric(StrEnum):
    """The fixed registry of spec 027: each a value skills/github-ship-watch/scripts/metrics.py
    computes. A metric joins only together with the metrics.py code that computes it"""

    DEPLOY_FREQUENCY = "deploy_frequency"  # Deploy frequency
    LEAD_TIME_MEDIAN = "lead_time_median"  # Lead time for changes, median
    LEAD_TIME_P90 = "lead_time_p90"  # Lead time for changes, p90
    CHANGE_FAILURE_RATE = "change_failure_rate"  # Change failure rate
    TIME_TO_RESTORE_MEDIAN = "time_to_restore_median"  # Time to restore, median
    ISSUE_TO_RELEASE_MEDIAN = "issue_to_release_median"  # Issue to release, median
    ISSUE_TO_RELEASE_P90 = "issue_to_release_p90"  # Issue to release, p90
    HUMAN_TOUCH = "human_touch"  # Human touch
    AGENT_SHARE = "agent_share"  # Agent share

    @property
    def unit(self) -> Unit:
        return _METRIC_UNITS[self]


_METRIC_UNITS = {
    Metric.DEPLOY_FREQUENCY: Unit.PER_WEEK,
    Metric.LEAD_TIME_MEDIAN: Unit.HOURS,
    Metric.LEAD_TIME_P90: Unit.HOURS,
    Metric.CHANGE_FAILURE_RATE: Unit.RATIO,
    Metric.TIME_TO_RESTORE_MEDIAN: Unit.HOURS,
    Metric.ISSUE_TO_RELEASE_MEDIAN: Unit.HOURS,
    Metric.ISSUE_TO_RELEASE_P90: Unit.HOURS,
    Metric.HUMAN_TOUCH: Unit.RATIO,
    Metric.AGENT_SHARE: Unit.RATIO,
}


class Comparison(StrEnum):
    LESS = "<"
    AT_MOST = "<="
    MORE = ">"
    AT_LEAST = ">="


@dataclass(frozen=True, slots=True)
class Measure:
    """A goal's measure: its metric, the comparison, and the target in the metric's unit
    (`1d` is 24 hours, `20%` a ratio of 0.2); `text` is the line as written after `measure: `"""

    metric: Metric
    comparison: Comparison
    target: float
    text: str

    @property
    def unit(self) -> Unit:
        return self.metric.unit

    @classmethod
    def parse(cls, text: str) -> Measure:
        """`<metric> <comparison> <target>`, single spaces between; refused naming the rule"""
        parts = _MEASURE_PARTS.fullmatch(text)  # `$` alone would let a trailing newline through
        if parts is None:
            raise ReleaseError(f"a measure is `<metric> <comparison> <target>`, single spaces between; got {text!r}")
        known = {m.value for m in Metric}
        if parts["metric"] not in known:
            names = ", ".join(m.value for m in Metric)
            raise ReleaseError(f"`{parts['metric']}` is not a known metric; they are {names}")
        metric = Metric(parts["metric"])
        if parts["comparison"] not in {c.value for c in Comparison}:
            listed = ", ".join(f"`{c.value}`" for c in Comparison)
            raise ReleaseError(f"`{parts['comparison']}` is not a comparison; it is one of {listed}")
        target = _TARGET.match(parts["target"])
        if target is None or _SUFFIX_UNITS[target["unit"]] is not metric.unit:
            raise ReleaseError(
                f"`{metric}` takes a target in {metric.unit.forms}, a non-negative number; got `{parts['target']}`"
            )
        number = float(target["number"])
        if metric.unit is Unit.RATIO and number > 100:
            raise ReleaseError(f"a percentage lies between 0 and 100; got `{parts['target']}`")
        return cls(metric, Comparison(parts["comparison"]), _in_unit(number, target["unit"]), text)

    def record(self) -> dict[str, str | float]:
        return {
            "metric": self.metric.value,
            "comparison": self.comparison.value,
            "target": self.target,
            "unit": self.unit.value,
            "text": self.text,
        }

    def __str__(self) -> str:
        return f"  measure: {self.text}"


def _in_unit(number: float, suffix: str) -> float:
    """A target as written, in its metric's unit: days in hours, a percentage as a ratio"""
    match suffix:
        case "d":
            return number * 24
        case "%":
            return number / 100
        case _:
            return number


class Prefix(StrEnum):
    """The prefix of an item's id, one per list section"""

    USER = "U"
    GOAL = "G"
    NON_GOAL = "N"
    QUALITY = "Q"


class Section(StrEnum):
    """A level-two heading of the direction, in the file's order; the value is the heading"""

    MISSION = "Mission"
    USERS = "Users"
    GOALS = "Goals"
    NON_GOALS = "Non-goals"
    QUALITY = "Quality bar"

    @property
    def prefix(self) -> Prefix | None:
        """The prefix its items carry; None for Mission, which is prose"""
        return _PREFIXES.get(self)

    @property
    def key(self) -> str:
        """Its key in the JSON record"""
        return _KEYS[self]

    @property
    def option(self) -> str:
        """How `--section` names it"""
        return _KEYS[self].replace("_", "-")

    @property
    def required(self) -> bool:
        """Users, Goals, and Quality bar hold at least one item; Non-goals may be empty"""
        return self in (Section.USERS, Section.GOALS, Section.QUALITY)

    @classmethod
    def named(cls, option: str) -> Section:
        for section in cls:
            if section.option == option:
                return section
        names = ", ".join(s.option for s in cls)
        raise ReleaseError(f"a direction section is one of {names}; got {option!r}")


_PREFIXES = {
    Section.USERS: Prefix.USER,
    Section.GOALS: Prefix.GOAL,
    Section.NON_GOALS: Prefix.NON_GOAL,
    Section.QUALITY: Prefix.QUALITY,
}
_KEYS = {
    Section.MISSION: "mission",
    Section.USERS: "users",
    Section.GOALS: "goals",
    Section.NON_GOALS: "non_goals",
    Section.QUALITY: "quality",
}
_ORDER = ", ".join(s.value for s in Section)


@dataclass(frozen=True, slots=True, order=True)
class ItemId:
    """An item's id, such as G-3: numbered from 1 within its prefix, never reused"""

    prefix: Prefix
    number: int

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ReleaseError(f"an item id's number starts at 1; got {self.prefix}-{self.number}")

    @classmethod
    def parse(cls, text: str) -> ItemId:
        m = _ID.match(text)
        known = {p.value for p in Prefix}
        if m is None or m["prefix"] not in known:
            raise ReleaseError(f"an item id is U-n, G-n, N-n, or Q-n with n from 1, such as G-3; got {text!r}")
        return cls(Prefix(m["prefix"]), int(m["number"]))

    def __str__(self) -> str:
        return f"{self.prefix}-{self.number}"


@dataclass(frozen=True, slots=True)
class Item:
    id: ItemId
    text: str
    measure: Measure | None = None  # only a goal carries one (spec 027)

    def record(self) -> dict[str, Any]:
        """A goal's record has a `measure` key, null without one; other items have none"""
        record: dict[str, Any] = {"id": str(self.id), "text": self.text}
        if self.id.prefix is Prefix.GOAL:
            record["measure"] = None if self.measure is None else self.measure.record()
        return record

    def lines(self) -> str:
        """The item as the file writes it: its line, and its measure line under it"""
        line = f"- {self}"
        return line if self.measure is None else f"{line}\n{self.measure}"

    def __str__(self) -> str:
        return f"{self.id}: {self.text}"


@dataclass(frozen=True, slots=True)
class Problem:
    """A rule the direction breaks: the file (relative to the repo), its line, and the rule"""

    path: Path
    line: int
    rule: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}"


@dataclass(frozen=True, slots=True)
class Direction:
    name: str
    mission: str  # the prose as written, its line breaks kept
    users: tuple[Item, ...]
    goals: tuple[Item, ...]
    non_goals: tuple[Item, ...]
    quality: tuple[Item, ...]

    def items(self, section: Section) -> tuple[Item, ...]:
        match section:
            case Section.MISSION:
                raise ReleaseError("Mission is prose; it holds no items")
            case Section.USERS:
                return self.users
            case Section.GOALS:
                return self.goals
            case Section.NON_GOALS:
                return self.non_goals
            case Section.QUALITY:
                return self.quality

    def all_items(self) -> tuple[Item, ...]:
        return self.users + self.goals + self.non_goals + self.quality

    def record(self, sections: Sequence[Section] = ()) -> dict[str, Any]:
        """The JSON shape of spec 024: the whole direction, or only the sections given"""
        if not sections:
            return {"name": self.name} | self._record(Section)
        return self._record(sections)

    def _record(self, sections: Iterable[Section]) -> dict[str, Any]:
        record: dict[str, Any] = {}
        for section in _ordered(sections):
            if section is Section.MISSION:
                record[section.key] = self.mission
            else:
                record[section.key] = [item.record() for item in self.items(section)]
        return record

    def render(self, sections: Sequence[Section] = ()) -> str:
        """The direction as Markdown, moved sections inline; only the sections given, if any"""
        blocks = [] if sections else [f"# {self.name}"]
        for section in _ordered(sections or tuple(Section)):
            if section is Section.MISSION:
                body = self.mission
            else:
                body = "\n".join(item.lines() for item in self.items(section))
            blocks.append(f"## {section.value}\n\n{body}" if body else f"## {section.value}")
        return "\n\n".join(blocks) + "\n"


def _ordered(sections: Iterable[Section]) -> list[Section]:
    wanted = set(sections)
    return [s for s in Section if s in wanted]


@dataclass(frozen=True, slots=True)
class GitRef:
    """A git ref of the checkout, as given, and the commit it resolved to (spec 034)"""

    name: str
    commit: str

    @classmethod
    def resolve(cls, root: Path, name: str) -> GitRef:
        """The ref's commit; refused (exit 2) when git can't resolve it to one, which is never
        read as a direction absent at it"""
        if not name or name.startswith("-") or name != name.strip():
            raise ReleaseError(f"a git ref names a commit, such as origin/main; got {name!r}")
        git = Git(root)
        git.run("rev-parse", "--git-dir")  # refuses a folder that isn't a git checkout
        if not git.ok("rev-parse", "--verify", "-q", f"{name}^{{commit}}"):
            raise ReleaseError(
                f"git can't resolve {name} to a commit in {root}; fetch it, or name a branch, tag, or commit it holds"
            )
        return cls(name, git.sha(name))

    def __str__(self) -> str:
        return self.name


def check(root: Path, at: GitRef | None = None) -> tuple[Problem, ...]:
    """Every rule docs/product.md and the files its sections moved to break; none when well
    formed. A missing docs/product.md is a problem too. Read from the working tree, or from
    the commit `at` names"""
    return _parse(_tree(root, at))[1]


def read(root: Path, at: GitRef | None = None) -> Direction:
    """The direction, moved sections resolved; refused (exit 2) when it isn't well formed"""
    direction, problems = _parse(_tree(root, at))
    if problems:
        listed = "\n".join(f"  {p}" for p in problems)
        raise ReleaseError(
            f"{DIRECTION} is not well formed; fix it, then run `{cli_command()} product check`:\n{listed}"
        )
    assert direction is not None  # no problems means every part parsed
    return direction


Line = tuple[int, str]  # a line number from 1 and the line, trailing whitespace stripped


@dataclass(slots=True)
class _Body:
    path: Path
    heading: int  # the line of its level-two heading
    lines: list[Line]  # blank ones included

    def filled(self) -> list[Line]:
        return [(n, line) for n, line in self.lines if line]


class _Tree(Protocol):
    """Where the direction's files are read: the working tree, or the tree of a commit"""

    @property
    def ref(self) -> GitRef | None: ...

    def is_file(self, relative: Path) -> bool: ...

    def contained(self, relative: Path, under: Path) -> bool:
        """Whether the file, symlinks resolved, stays under the repo's `under` directory, so a
        link never reads, and a problem never quotes, a file outside it"""
        ...

    def lines(self, relative: Path) -> list[Line]: ...


@dataclass(frozen=True, slots=True)
class _WorkTree:
    root: Path
    ref: None = None

    def is_file(self, relative: Path) -> bool:
        return (self.root / relative).is_file()

    def contained(self, relative: Path, under: Path) -> bool:
        return (self.root / relative).resolve().is_relative_to((self.root / under).resolve()) and (
            self.root / under
        ).resolve().is_relative_to(self.root.resolve())

    def lines(self, relative: Path) -> list[Line]:
        path = self.root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ReleaseError(f"{path} is not UTF-8 text: {exc}") from None
        return _split(text)


_SYMLINK = "120000"  # the git mode of a symbolic link, whose blob is the link's target
_MAX_LINKS = 40  # symlinks followed for one path before it reads as missing, as the kernel's ELOOP


@dataclass(frozen=True, slots=True)
class _Entry:
    mode: str
    kind: str  # blob, tree, or commit (a submodule)
    object: str


@dataclass(slots=True)
class _RefTree:
    """The tree of the commit a ref names (spec 034): the files as committed there, symlinks
    followed inside that tree by the same containment rules as the working tree's"""

    git: Git
    ref: GitRef
    _entries: dict[PurePosixPath, _Entry | None] = field(default_factory=dict)

    def is_file(self, relative: Path) -> bool:
        path = self._resolve(relative)
        if path is None:
            return False
        if _outside(path):
            return True  # a link out of the repo; contained() refuses it, its target never read
        entry = self._entry(path)
        return entry is not None and entry.kind == "blob"

    def contained(self, relative: Path, under: Path) -> bool:
        path, directory = self._resolve(relative), self._resolve(under)
        if path is None or directory is None or _outside(path) or _outside(directory):
            return False
        return path.is_relative_to(directory)

    def lines(self, relative: Path) -> list[Line]:
        path = self._resolve(relative)
        entry = None if path is None or _outside(path) else self._entry(path)
        if entry is None or entry.kind != "blob":
            raise ReleaseError(f"{self.ref}:{relative} is not a file")
        try:
            text = self.git.run_bytes("cat-file", "blob", entry.object).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReleaseError(f"{self.ref}:{relative} is not UTF-8 text: {exc}") from None
        return _split(text)

    def _entry(self, path: PurePosixPath) -> _Entry | None:
        """The commit tree's entry at path, None when there is none; path holds no symlink"""
        if path not in self._entries:
            out = self.git.run_bytes("ls-tree", "-z", "--full-tree", self.ref.commit, "--", path.as_posix())
            found = None
            for record in out.decode("utf-8", errors="replace").split("\0"):
                meta, _, name = record.partition("\t")
                if name == path.as_posix():
                    mode, kind, obj = meta.split(" ")
                    found = _Entry(mode, kind, obj)
            self._entries[path] = found
        return self._entries[path]

    def _resolve(self, relative: Path) -> PurePosixPath | None:
        """The path with each symlink in it followed within the commit's tree; None when a part
        is missing or the links loop. A link out of the repo gives a path outside it"""
        done = PurePosixPath()
        parts = list(PurePosixPath(relative.as_posix()).parts)
        links = 0
        while parts:
            current = done / parts.pop(0)
            entry = self._entry(current)
            if entry is None:
                return None
            if entry.mode != _SYMLINK:
                done = current
                continue
            links += 1
            if links > _MAX_LINKS:
                return None
            target = self.git.run_bytes("cat-file", "blob", entry.object).decode("utf-8", errors="replace")
            if target.startswith("/"):
                return PurePosixPath(target)
            joined = PurePosixPath(posixpath.normpath(posixpath.join(done.as_posix(), target)))
            if _outside(joined):
                return joined
            parts = [p for p in joined.parts if p != "."] + parts
            done = PurePosixPath()
        return done


def _outside(path: PurePosixPath) -> bool:
    """Whether a path resolved at a ref leaves the repo"""
    return path.is_absolute() or path.parts[:1] == ("..",)


def _tree(root: Path, at: GitRef | None) -> _Tree:
    return _WorkTree(root) if at is None else _RefTree(Git(root), at)


class _Parser:
    def __init__(self, tree: _Tree) -> None:
        self.tree = tree
        self.problems: list[Problem] = []
        self.seen: dict[ItemId, str] = {}  # the file:line each id first appears on, for a duplicate's message
        self.bodies: dict[Section, _Body] = {}  # each section's lines, in the file a moved one moved to

    def fail(self, path: Path, line: int, rule: str) -> None:
        self.problems.append(Problem(path, line, rule))

    def direction(self) -> Direction | None:
        if not self.tree.is_file(DIRECTION):
            ref = self.tree.ref
            if ref is None:
                self.fail(DIRECTION, 1, f"no such file; the direction is {DIRECTION}, in the grammar of spec 024")
            else:
                self.fail(DIRECTION, 1, f"no {DIRECTION} at {ref}")
            return None
        if not self.tree.contained(DIRECTION, DIRECTION.parent):
            self.fail(DIRECTION, 1, f"a symlink out of {DIRECTION.parent}/; the direction is a file in the repo")
            return None
        name, bodies = self._sections(self.tree.lines(DIRECTION))
        parts: dict[Section, str | tuple[Item, ...]] = {}
        for section in Section:
            body = self._resolve(section, bodies[section]) if section in bodies else None
            if body is not None:
                self.bodies[section] = body
                parts[section] = self._section(section, body)
        if self.problems or name is None:
            return None
        mission = parts[Section.MISSION]
        assert isinstance(mission, str)
        items = {s: p for s, p in parts.items() if isinstance(p, tuple)}
        return Direction(
            name=name,
            mission=mission,
            users=items[Section.USERS],
            goals=items[Section.GOALS],
            non_goals=items[Section.NON_GOALS],
            quality=items[Section.QUALITY],
        )

    def _sections(self, lines: list[Line]) -> tuple[str | None, dict[Section, _Body]]:
        """The product's name and each section's lines; headings out of the grammar are problems"""
        name: str | None = None
        bodies: dict[Section, _Body] = {}
        order: list[tuple[int, Section]] = []
        current: _Body | None = None
        skipping = False  # under a heading already reported, whose lines say nothing more
        unnamed = False  # the missing `# <product name>` is reported
        for number, line in lines:
            heading = _HEADING.match(line)
            if heading is not None:
                level, title = len(heading["hashes"]), (heading["title"] or "").strip()
                if level == 1:
                    if name is not None or bodies:
                        self.fail(DIRECTION, number, "a second level-one heading; the file has one, the product's name")
                    elif not title:
                        self.fail(DIRECTION, number, "the level-one heading names the product; it is empty")
                    else:
                        name = title
                    continue
                if name is None and not unnamed:
                    self.fail(DIRECTION, number, "the file starts with a level-one heading, `# <product name>`")
                    unnamed = True
                if level != 2:
                    self.fail(DIRECTION, number, f"{_quote(line)}: the direction has only its five level-two headings")
                    continue
                section = _section_named(title)
                if section is None:
                    self.fail(DIRECTION, number, f"{_quote(line)} is not a direction heading; they are {_ORDER}")
                    current, skipping = None, True
                    continue
                if section in bodies:
                    first = bodies[section].heading
                    self.fail(DIRECTION, number, f"`## {section.value}` again; it is already on line {first}")
                    current, skipping = None, True
                    continue
                current, skipping = _Body(DIRECTION, number, []), False
                bodies[section] = current
                order.append((number, section))
                continue
            if current is not None:
                current.lines.append((number, line))  # blank lines too: they part Mission's paragraphs
                continue
            if not line or skipping:
                continue
            if name is None:
                if not unnamed:
                    self.fail(DIRECTION, number, "the file starts with a level-one heading, `# <product name>`")
                    unnamed = True
            else:
                self.fail(DIRECTION, number, "text before `## Mission`; the sections come right after the name")
                skipping = True
        if name is None and not unnamed:
            self.fail(DIRECTION, 1, "the file starts with a level-one heading, `# <product name>`")
        self._order(order, bodies, lines)
        return name, bodies

    def _order(self, order: list[tuple[int, Section]], bodies: dict[Section, _Body], lines: list[Line]) -> None:
        sections = list(Section)
        latest: Section | None = None
        for number, section in order:
            if latest is not None and sections.index(section) < sections.index(latest):
                self.fail(
                    DIRECTION,
                    number,
                    f"`## {section.value}` comes after `## {latest.value}`; the sections go {_ORDER}",
                )
            elif latest is None or sections.index(section) > sections.index(latest):
                latest = section
        end = lines[-1][0] if lines else 1
        for index, section in enumerate(sections):
            if section in bodies:
                continue
            later = [bodies[s].heading for s in sections[index + 1 :] if s in bodies]
            self.fail(DIRECTION, later[0] if later else end, f"missing `## {section.value}`; the sections go {_ORDER}")

    def _resolve(self, section: Section, body: _Body) -> _Body | None:
        """The section's own lines, or those of the file it moved to; None when the link is broken"""
        filled = body.filled()
        if not any(_SEE.match(line) for _, line in filled):
            return body
        number, line = next((n, x) for n, x in filled if _SEE.match(x))
        if len(filled) > 1:
            self.fail(
                body.path, number, f"a moved section holds only its `See [...]` line; `## {section.value}` holds more"
            )
            return None
        moved = _MOVED.match(line)
        if moved is None:
            self.fail(
                body.path,
                number,
                f"a moved section's line is `See [{section.value}](product/<file>.md).`; got {_quote(line)}",
            )
            return None
        if moved["label"] != section.value:
            self.fail(body.path, number, f"the link names `{moved['label']}`; under `## {section.value}` it names it")
            return None
        relative = DIRECTION.parent / _MOVED_DIR / moved["file"]
        if not self.tree.is_file(relative):
            at = "" if self.tree.ref is None else f" at {self.tree.ref}"
            self.fail(body.path, number, f"`## {section.value}` moved to {relative}, which doesn't exist{at}")
            return None
        if not self.tree.contained(relative, relative.parent):
            self.fail(
                body.path, number, f"{relative} is a symlink out of {relative.parent}/; a moved section is a file there"
            )
            return None
        return self._moved(section, relative, self.tree.lines(relative))

    def _moved(self, section: Section, path: Path, lines: list[Line]) -> _Body | None:
        body: _Body | None = None
        for number, line in lines:
            if not line:
                if body is not None:
                    body.lines.append((number, line))
                continue
            heading = _HEADING.match(line)
            if body is None:
                if heading is None or len(heading["hashes"]) != 2 or _section_named(heading["title"]) is not section:
                    self.fail(path, number, f"a file `## {section.value}` moved to starts with it; got {_quote(line)}")
                    return None
                body = _Body(path, number, [])
            elif heading is not None:
                self.fail(path, number, f"{_quote(line)}: a moved section's file holds only its own heading")
            elif _SEE.match(line):
                self.fail(path, number, "a moved section moves no further; its items sit in this file")
            else:
                body.lines.append((number, line))
        if body is None:
            self.fail(path, 1, f"the file is empty; a file `## {section.value}` moved to starts with it")
            return None
        return body

    def _section(self, section: Section, body: _Body) -> str | tuple[Item, ...]:
        prefix = section.prefix
        if prefix is None:
            if not body.filled():
                self.fail(
                    body.path, body.heading, f"`## {section.value}` holds no text; it says what the product is for"
                )
            return "\n".join(line for _, line in body.lines).strip("\n")
        items: list[Item] = []
        broken = False  # a line failed, so an empty section says nothing more
        previous = _Previous.START
        for number, line in body.lines:
            if not line:
                previous = _Previous.BLANK
                continue
            if _MEASURE_LIKE.match(line):
                previous = self._measure(section, body, number, line, previous, items)
                continue
            previous = _Previous.BROKEN
            m = _ITEM.match(line)
            broken = broken or m is None or m["prefix"] != prefix.value
            if m is None:
                self.fail(body.path, number, f"not an item of the form `- {prefix}-<n>: <text>`: {_quote(line)}")
                continue
            if m["prefix"] != prefix.value:
                self.fail(
                    body.path,
                    number,
                    f"`## {section.value}` holds {prefix}-n items; got {m['prefix']}-{m['number']}",
                )
                continue
            item = Item(ItemId(prefix, int(m["number"])), m["text"])
            first = self.seen.get(item.id)
            if first is not None:
                self.fail(body.path, number, f"{item.id} again; it is already on {first}")
                continue
            self.seen[item.id] = f"{body.path}:{number}"
            items.append(item)
            previous = _Previous.ITEM
        if section.required and not items and not broken:
            self.fail(body.path, body.heading, f"`## {section.value}` holds no item; it needs at least one")
        return tuple(items)

    def _measure(
        self, section: Section, body: _Body, number: int, line: str, previous: _Previous, items: list[Item]
    ) -> _Previous:
        """A measure line (spec 027): only right under a goal's item line, one per goal; the
        goal it measures gets it. Returns what the next line follows"""
        if section is not Section.GOALS:
            self.fail(body.path, number, f"a measure line sits only under a goal; `## {section.value}` holds none")
            return _Previous.BROKEN
        if previous is _Previous.BROKEN:  # under a line already reported
            return _Previous.BROKEN
        if previous is _Previous.MEASURED:
            self.fail(body.path, number, f"a second measure line under {items[-1].id}; a goal carries at most one")
            return _Previous.BROKEN
        if previous is not _Previous.ITEM:
            where = "after a blank line" if previous is _Previous.BLANK else "before any goal"
            self.fail(body.path, number, f"a measure line sits right under its goal's item line; this one is {where}")
            return _Previous.BROKEN
        written = _MEASURE_LINE.match(line)
        if written is None:
            self.fail(
                body.path, number, f"a measure line is {_MEASURE_FORM}, indented by two spaces; got {_quote(line)}"
            )
            return _Previous.MEASURED
        try:
            measure = Measure.parse(written["text"])
        except ReleaseError as exc:
            self.fail(body.path, number, str(exc))
            return _Previous.MEASURED
        items[-1] = replace(items[-1], measure=measure)
        return _Previous.MEASURED


class _Previous(StrEnum):
    """What the line before a list section's line was, for where a measure line may sit"""

    START = "start"
    BLANK = "blank"
    ITEM = "item"
    MEASURED = "measured"  # a measure line, well formed or not
    BROKEN = "broken"  # a line already reported, or one no measure may follow


def _parse(tree: _Tree) -> tuple[Direction | None, tuple[Problem, ...]]:
    parser = _Parser(tree)
    direction = parser.direction()
    return direction, tuple(parser.problems)


def _split(text: str) -> list[Line]:
    return [(n, line.rstrip()) for n, line in enumerate(text.splitlines(), start=1)]


def _section_named(title: str | None) -> Section | None:
    for section in Section:
        if section.value == title:
            return section
    return None


def _quote(line: str) -> str:
    return f"`{line}`" if "`" not in line else repr(line)


# The edit commands (spec 024): an agent changes an item only through them, so an id is never
# reused and a line never breaks the grammar. Each refuses a direction `check` refuses, writes
# only the item's line, in the file a moved section moved to, and leaves every other line as it was


@dataclass(frozen=True, slots=True)
class Edited:
    """The line an edit wrote, or removed, and where: the file relative to the repo, and its line"""

    path: Path
    line: int
    text: str


_SECTION_OF = {prefix: section for section, prefix in _PREFIXES.items()}


def add(root: Path, section: Section, text: LineText) -> Edited:
    """Append `- <id>: <text>` to the section with the next id"""
    prefix = section.prefix
    if prefix is None:
        raise ReleaseError(f"`## {section.value}` is prose, not items; edit it in {DIRECTION} by hand")
    direction, bodies = _editable(root)
    body = bodies[section]
    line = f"- {Item(_next(root, prefix, direction), str(text))}"
    document = Document.read(root / body.path)
    filled = body.filled()
    if filled:
        index = document.insert(filled[-1][0], [line])  # right after the last item
    else:
        index = document.insert(document.section_start(body.heading - 1), [line], pad=True)
    document.write()
    return Edited(body.path, index + 1, line)


def edit(root: Path, id: ItemId, text: LineText) -> Edited:
    """Rewrite one item's text; its id stays"""
    _, bodies = _editable(root)
    body, number = _located(bodies, id)
    line = f"- {Item(id, str(text))}"
    document = Document.read(root / body.path)
    document.replace(number - 1, line)
    document.write()
    return Edited(body.path, number, line)


def retire(root: Path, id: ItemId) -> Edited:
    """Remove one item; its id is never handed out again. The last item of a section that needs
    one is refused"""
    direction, bodies = _editable(root)
    section = _SECTION_OF[id.prefix]
    body, number = _located(bodies, id)
    if section.required and len(direction.items(section)) == 1:
        raise ReleaseError(
            f"{id} is the only item of `## {section.value}`, which needs at least one; add the item that"
            f" replaces it with `{cli_command()} product add {section.option}`, then retire {id}"
        )
    document = Document.read(root / body.path)
    removed = document.content(number - 1)
    if any(item.id == id and item.measure is not None for item in direction.items(section)):
        document.delete(number)  # its measure line, right under its item line (spec 027)
    document.delete(number - 1)
    document.write()
    return Edited(body.path, number, removed)


def measure(root: Path, id: ItemId, written: Measure | None) -> Edited | None:
    """Write a goal's measure line right under its item line, replacing the one it has, or
    remove it when `written` is None (spec 027). None when there was nothing to remove"""
    if id.prefix is not Prefix.GOAL:
        raise ReleaseError(f"only a goal carries a measure; {id} is not a G-n id")
    direction, bodies = _editable(root)
    body, number = _located(bodies, id)
    had = next(item.measure for item in direction.goals if item.id == id) is not None
    document = Document.read(root / body.path)
    if written is None:
        if not had:
            return None
        removed = document.content(number)
        document.delete(number)
        document.write()
        return Edited(body.path, number + 1, removed)
    line = str(written)
    if had:
        document.replace(number, line)  # the measure line, right under the item line
    else:
        document.insert(number, [line])
    document.write()
    return Edited(body.path, number + 1, line)


def _editable(root: Path) -> tuple[Direction, dict[Section, _Body]]:
    """The direction and each section's lines; refused (exit 2) when `check` refuses it, so
    nothing is written over a broken file"""
    parser = _Parser(_WorkTree(root))
    direction = parser.direction()
    if parser.problems:
        listed = "\n".join(f"  {p}" for p in parser.problems)
        raise ReleaseError(
            f"{DIRECTION} doesn't pass `{cli_command()} product check`, so nothing was written; fix it first:\n{listed}"
        )
    assert direction is not None  # no problems means every part parsed
    return direction, parser.bodies


def _next(root: Path, prefix: Prefix, direction: Direction) -> ItemId:
    """One above the highest id of the prefix that docs/product.md, or a file under
    docs/product/, ever held on the current branch or holds now"""
    paths = (PurePosixPath(DIRECTION.as_posix()), PurePosixPath((DIRECTION.parent / _MOVED_DIR).as_posix()))
    held = history_numbers(root, paths, prefix.value)
    held |= {item.id.number for item in direction.all_items() if item.id.prefix is prefix}
    return ItemId(prefix, max(held, default=0) + 1)


def _located(bodies: dict[Section, _Body], id: ItemId) -> tuple[_Body, int]:
    """The body holding the item and the item's line number in its file"""
    body = bodies[_SECTION_OF[id.prefix]]
    for number, line in body.filled():
        m = _ITEM.match(line)
        if m is not None and int(m["number"]) == id.number:
            return body, number
    raise ReleaseError(f"no {id} in {DIRECTION}; `{cli_command()} product ids` lists its ids")
