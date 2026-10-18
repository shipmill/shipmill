"""The product's direction, docs/product.md (spec 024): the mission, users, goals, non-goals,
and quality bar the agents work toward. Its grammar is fixed so code reads it without a model:
a level-one heading naming the product, then the five sections in order, the four list
sections holding only `- <prefix>-<n>: <text>` items. A section may move to its own file
under docs/product/ through a single `See [<section>](product/<file>.md).` line. Only the
maintainer changes it (D-34); this module only reads it"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from shipmill import cli_command
from shipmill.errors import ReleaseError

DIRECTION = Path("docs/product.md")
_MOVED_DIR = "product"  # moved sections live in docs/product/, linked relative to docs/

_HEADING = re.compile(r"^(?P<hashes>#{1,6})(?:[ \t]+(?P<title>.*))?$")
_ITEM = re.compile(r"^- (?P<prefix>[A-Za-z]+)-(?P<number>[1-9][0-9]*): (?P<text>\S.*)$")
_ID = re.compile(r"^(?P<prefix>[A-Z])-(?P<number>[1-9][0-9]*)$")
_SEE = re.compile(r"^See \[")
_MOVED = re.compile(r"^See \[(?P<label>[^\]]+)\]\(product/(?P<file>[A-Za-z0-9][A-Za-z0-9_-]*\.md)\)\.$")


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

    def record(self) -> dict[str, str]:
        return {"id": str(self.id), "text": self.text}

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
                body = "\n".join(f"- {item}" for item in self.items(section))
            blocks.append(f"## {section.value}\n\n{body}" if body else f"## {section.value}")
        return "\n\n".join(blocks) + "\n"


def _ordered(sections: Iterable[Section]) -> list[Section]:
    wanted = set(sections)
    return [s for s in Section if s in wanted]


def check(root: Path) -> tuple[Problem, ...]:
    """Every rule docs/product.md and the files its sections moved to break; none when well
    formed. A missing docs/product.md is a problem too"""
    return _parse(root)[1]


def read(root: Path) -> Direction:
    """The direction, moved sections resolved; refused (exit 2) when it isn't well formed"""
    direction, problems = _parse(root)
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


class _Parser:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.problems: list[Problem] = []
        self.seen: dict[ItemId, str] = {}  # the file:line each id first appears on, for a duplicate's message

    def fail(self, path: Path, line: int, rule: str) -> None:
        self.problems.append(Problem(path, line, rule))

    def direction(self) -> Direction | None:
        path = self.root / DIRECTION
        if not path.is_file():
            self.fail(DIRECTION, 1, f"no such file; the direction is {DIRECTION}, in the grammar of spec 024")
            return None
        name, bodies = self._sections(_lines(path))
        parts: dict[Section, str | tuple[Item, ...]] = {}
        for section in Section:
            body = self._resolve(section, bodies[section]) if section in bodies else None
            if body is not None:
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
        path = self.root / relative
        if not path.is_file():
            self.fail(body.path, number, f"`## {section.value}` moved to {relative}, which doesn't exist")
            return None
        return self._moved(section, relative, _lines(path))

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
        for number, line in body.filled():
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
        if section.required and not items and not broken:
            self.fail(body.path, body.heading, f"`## {section.value}` holds no item; it needs at least one")
        return tuple(items)


def _parse(root: Path) -> tuple[Direction | None, tuple[Problem, ...]]:
    parser = _Parser(root)
    direction = parser.direction()
    return direction, tuple(parser.problems)


def _lines(path: Path) -> list[Line]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseError(f"{path} is not UTF-8 text: {exc}") from None
    return [(n, line.rstrip()) for n, line in enumerate(text.splitlines(), start=1)]


def _section_named(title: str | None) -> Section | None:
    for section in Section:
        if section.value == title:
            return section
    return None


def _quote(line: str) -> str:
    return f"`{line}`" if "`" not in line else repr(line)
