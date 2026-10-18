"""REVIEW.md, the repo's review rubric, read without a model (spec 024).

The file stays Markdown that Claude's Code Review reads too. Three level-two sections have a
fixed line format that code extracts, and a line that breaks it is an error, never skipped:

- `## Important`: `- I-n: <rule>`, ids from 1 and unique in the file
- `## Nits`: `- <nit>` items and at most one `cap: N` line; without the line the cap is 5
- `## Protected areas`: `` - `<glob>`: <why> ``

Every other section, and any text before the first heading, is free: passed to the reviewer
as it is and never an error. A REVIEW.md in a subdirectory adds its rules for changes under
it; its ids are its own, cited with its directory (`skills/I-2`), and the smallest cap wins.
The edit commands at the end write one structured line in the working tree, never a commit.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from shipmill import cli_command
from shipmill.errors import ReleaseError
from shipmill.gitrepo import Git
from shipmill.lineedit import Document, LineText, history_numbers

REVIEW = "REVIEW.md"
DEFAULT_CAP = 5
IMPORTANT = "Important"
NITS = "Nits"
PROTECTED = "Protected areas"
STRUCTURED = (IMPORTANT, NITS, PROTECTED)

_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_RULE_ID = re.compile(r"I-([1-9][0-9]*)")
_IMPORTANT_ITEM = re.compile(r"- (I-\S*): (\S.*)")
_CAP = re.compile(r"cap:(.*)")
_NIT = re.compile(r"- \S.*")
_PROTECTED_ITEM = re.compile(r"- `([^`]*)`: (\S.*)")


@dataclass(frozen=True, slots=True, order=True)
class RuleId:
    """An Important rule's id within its REVIEW.md, such as I-3"""

    number: int

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ReleaseError(f"an Important id is I-n with n from 1, such as I-1; got I-{self.number}")

    @classmethod
    def parse(cls, text: str) -> RuleId:
        m = _RULE_ID.fullmatch(text)
        if m is None:
            raise ReleaseError(f"an Important id is I-n with n from 1, such as I-1; got {text!r}")
        return cls(int(m.group(1)))

    def __str__(self) -> str:
        return f"I-{self.number}"


@dataclass(frozen=True, slots=True)
class Glob:
    """A Protected areas path pattern, such as src/shipmill/land.py or skills/**"""

    value: str

    def __post_init__(self) -> None:
        if not self.value or self.value != self.value.strip() or "`" in self.value:
            raise ReleaseError(f"a protected glob is a non-empty path pattern without backticks; got {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Problem:
    """A line of a REVIEW.md that breaks a structured section's format"""

    file: PurePosixPath  # relative to the repo root
    line: int
    rule: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.rule}"


@dataclass(frozen=True, slots=True)
class Rule:
    id: RuleId
    text: str
    file: PurePosixPath

    @property
    def cited(self) -> str:
        """The id a finding cites: I-2 for the root's, skills/I-2 for skills/REVIEW.md's"""
        folder = self.file.parent
        return str(self.id) if folder == PurePosixPath(".") else f"{folder}/{self.id}"


@dataclass(frozen=True, slots=True)
class Protected:
    glob: Glob
    why: str
    file: PurePosixPath


@dataclass(frozen=True, slots=True)
class Free:
    heading: str | None  # None for the text before the first heading
    text: str
    file: PurePosixPath


@dataclass(frozen=True, slots=True)
class Rubric:
    """One REVIEW.md, or several merged; cap is None when none of them sets one"""

    important: tuple[Rule, ...]
    cap: int | None
    protected: tuple[Protected, ...]
    free: tuple[Free, ...]

    @property
    def effective_cap(self) -> int:
        return DEFAULT_CAP if self.cap is None else self.cap

    def to_json(self) -> dict[str, Any]:
        return {
            "important": [{"id": r.cited, "text": r.text, "file": str(r.file)} for r in self.important],
            "cap": self.effective_cap,
            "protected": [{"glob": str(p.glob), "why": p.why, "file": str(p.file)} for p in self.protected],
            "free": [{"heading": f.heading, "text": f.text, "file": str(f.file)} for f in self.free],
        }

    def render(self) -> str:
        """The rubric as Markdown, for a reviewer's brief"""
        out: list[str] = []
        if self.important:
            out += ["## Important", "", *(f"- {r.cited}: {r.text}" for r in self.important), ""]
        out += ["## Nits", "", f"cap: {self.effective_cap}", ""]
        if self.protected:
            out += [
                "## Protected areas",
                "",
                *(f"- `{p.glob}`: {p.why} ({p.file})" for p in self.protected),
                "",
            ]
        for f in self.free:
            title = "Before the first heading" if f.heading is None else f.heading
            out += [f"## {title} ({f.file})", ""]
            if f.text:
                out += [f.text, ""]
        return "\n".join(out)


class Malformed(ReleaseError):
    """A REVIEW.md whose structured sections break their format"""

    def __init__(self, problems: Sequence[Problem]) -> None:
        self.problems = tuple(problems)
        super().__init__("REVIEW.md is malformed:\n" + "\n".join(str(p) for p in self.problems))


@dataclass(slots=True)
class _Section:
    heading: str | None
    line: int  # the heading's line, or 1 for the text before the first heading
    body: list[tuple[int, str]]


def _sections(text: str) -> list[_Section]:
    """Split at level-one and level-two headings outside fenced code; a deeper heading stays
    in its section's body"""
    sections = [_Section(None, 1, [])]
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        opened = _FENCE.match(line)
        if fence is not None:
            if opened is not None and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence):
                fence = None
        elif opened is not None:
            fence = opened.group(1)
        else:
            heading = _HEADING.match(line)
            if heading is not None and len(heading.group(1)) <= 2:
                sections.append(_Section((heading.group(2) or "").strip(), number, []))
                continue
        sections[-1].body.append((number, line))
    return sections


def _free_text(body: Sequence[tuple[int, str]]) -> str:
    return "\n".join(line for _, line in body).strip("\n")


def parse(text: str, file: PurePosixPath) -> tuple[Rubric, tuple[Problem, ...]]:
    """The rubric one REVIEW.md holds, and every line that breaks a structured section"""
    important: list[Rule] = []
    protected: list[Protected] = []
    free: list[Free] = []
    problems: list[Problem] = []
    cap: int | None = None
    seen_sections: dict[str, int] = {}
    seen_ids: dict[RuleId, int] = {}
    seen_globs: dict[Glob, int] = {}

    def problem(line: int, rule: str) -> None:
        problems.append(Problem(file, line, rule))

    for section in _sections(text):
        if section.heading not in STRUCTURED:
            body = _free_text(section.body)
            if section.heading is not None or body:
                free.append(Free(section.heading, body, file))
            continue
        name = section.heading
        if name in seen_sections:
            problem(section.line, f"a second ## {name} section; the first is on line {seen_sections[name]}")
            continue
        seen_sections[name] = section.line
        cap_line: int | None = None
        for number, line in section.body:
            if not line.strip():
                continue
            if name == IMPORTANT:
                item = _IMPORTANT_ITEM.fullmatch(line)
                if item is None:
                    problem(number, "an Important item is one line `- I-n: <rule>`")
                    continue
                try:
                    rule_id = RuleId.parse(item.group(1))
                except ReleaseError as exc:
                    problem(number, str(exc))
                    continue
                if rule_id in seen_ids:
                    problem(number, f"{rule_id} is already used on line {seen_ids[rule_id]}; ids are unique")
                    continue
                seen_ids[rule_id] = number
                important.append(Rule(rule_id, item.group(2).strip(), file))
            elif name == NITS:
                capped = _CAP.fullmatch(line)
                if capped is not None:
                    if cap_line is not None:
                        problem(number, f"a second `cap:` line; Nits holds at most one, on line {cap_line}")
                        continue
                    cap_line = number
                    value = capped.group(1).strip()
                    if not value.isascii() or not value.isdigit():
                        problem(number, f"the Nits cap is a whole number, as `cap: 5`; got {value!r}")
                        continue
                    cap = int(value)
                elif _NIT.fullmatch(line) is None:
                    problem(number, "Nits holds `- <nit>` items and at most one `cap: N` line")
            else:
                item = _PROTECTED_ITEM.fullmatch(line)
                if item is None:
                    problem(number, "a Protected areas item is one line ``- `<glob>`: <why>``, the glob in backticks")
                    continue
                try:
                    glob = Glob(item.group(1))
                except ReleaseError as exc:
                    problem(number, str(exc))
                    continue
                if glob in seen_globs:
                    problem(number, f"`{glob}` is already listed on line {seen_globs[glob]}")
                    continue
                seen_globs[glob] = number
                protected.append(Protected(glob, item.group(2).strip(), file))
    rubric = Rubric(tuple(important), cap, tuple(protected), tuple(free))
    return rubric, tuple(problems)


def merge(rubrics: Iterable[Rubric]) -> Rubric:
    """Rubrics in order, root first; the smallest cap any of them sets"""
    listed = list(rubrics)
    caps = [r.cap for r in listed if r.cap is not None]
    return Rubric(
        tuple(rule for r in listed for rule in r.important),
        min(caps) if caps else None,
        tuple(p for r in listed for p in r.protected),
        tuple(f for r in listed for f in r.free),
    )


def files(root: Path) -> list[PurePosixPath]:
    """Every REVIEW.md in the checkout, tracked or new and not ignored, root first"""
    listed = Git(root).run("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    found = {
        PurePosixPath(name)
        for name in listed.split("\0")
        if name and PurePosixPath(name).name == REVIEW and (root / name).is_file()
    }
    return sorted(found, key=lambda p: (len(p.parts), p.parts))


def _read(root: Path, file: PurePosixPath) -> tuple[Rubric, tuple[Problem, ...]]:
    """Refuses a REVIEW.md that a symlink, its own or a folder's, leads outside the checkout,
    so a change can't feed a file from elsewhere on the machine to the reviewer"""
    target = (root / file).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ReleaseError(f"{file} resolves to {target}, outside the repository {root}; refusing to read it")
    return parse(target.read_text(encoding="utf-8"), file)


def check(root: Path) -> list[Problem]:
    """What breaks the structured sections of every REVIEW.md; none without a REVIEW.md"""
    return [p for file in files(root) for p in _read(root, file)[1]]


def _changed(root: Path, path: str) -> PurePosixPath:
    """A changed file as a path relative to the repo root; it need not exist (a deletion)"""
    given = Path(path)
    if given.is_absolute():
        try:
            given = given.relative_to(root)
        except ValueError:
            raise ReleaseError(f"--path {path} is outside the repository {root}") from None
    relative = PurePosixPath(given.as_posix())
    if ".." in relative.parts or not relative.parts or relative == PurePosixPath("."):
        raise ReleaseError(f"--path is a file in the repository, relative to its root; got {path!r}")
    return relative


def applying(root: Path, paths: Sequence[str]) -> list[PurePosixPath]:
    """The REVIEW.md files for changes to paths: the root's, then those of every directory
    from each file up to the root, shallowest first; tracked or new and not ignored, as check"""
    wanted = {PurePosixPath(REVIEW)}
    for path in paths:
        for folder in _changed(root, path).parents:
            wanted.add(folder / REVIEW)
    return [p for p in files(root) if p in wanted]  # the ones check reads, so show never refuses what check passed


def show(root: Path, paths: Sequence[str]) -> Rubric:
    """The merged rubric for changes to paths (the root's alone without any); Malformed when
    a REVIEW.md it reads breaks its format"""
    rubrics: list[Rubric] = []
    problems: list[Problem] = []
    for file in applying(root, paths):
        rubric, found = _read(root, file)
        rubrics.append(rubric)
        problems.extend(found)
    if problems:
        raise Malformed(problems)
    return merge(rubrics)


# The edit commands (spec 024): an agent changes a structured line only through them, so an id
# is never reused, a glob keeps its backticks, and Nits keeps one `cap:` line. Each refuses a
# REVIEW.md `check` refuses, writes a section the file lacks in its fixed place (Important, then
# Nits, then Protected areas), and leaves every other line as it was


@dataclass(frozen=True, slots=True)
class Edited:
    """The line an edit wrote, or removed, and where: the REVIEW.md relative to the repo, and its line"""

    file: PurePosixPath
    line: int
    text: str


def review_file(root: Path, folder: str | None) -> PurePosixPath:
    """The REVIEW.md an edit changes: the root's, or that of --dir, an existing directory in
    the repository given relative to its root"""
    if folder is None:
        return PurePosixPath(REVIEW)
    relative = PurePosixPath(Path(folder).as_posix())
    if relative.is_absolute() or ".." in relative.parts:
        raise ReleaseError(f"--dir is a directory in the repository, relative to its root; got {folder!r}")
    target = root / relative
    if not target.is_dir():
        raise ReleaseError(f"--dir {folder}: no such directory in {root}")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ReleaseError(f"--dir {folder} resolves to {target.resolve()}, outside the repository {root}")
    return relative / REVIEW


def add_rule(root: Path, file: PurePosixPath, text: LineText) -> Edited:
    """Append `- I-n: <text>` to Important, n one above any id the file ever held"""
    document, rubric = _editable(root, file, create=True)
    held = history_numbers(root, (file,), "I") | {rule.id.number for rule in rubric.important}
    line = f"- {RuleId(max(held, default=0) + 1)}: {text}"
    return _append(document, file, IMPORTANT, line)


def protect(root: Path, file: PurePosixPath, glob: Glob, why: LineText) -> Edited:
    """Append ``- `<glob>`: <why>`` to Protected areas; a glob already listed is refused"""
    document, rubric = _editable(root, file, create=True)
    if any(p.glob == glob for p in rubric.protected):
        raise ReleaseError(f"`{glob}` is already in {file}'s Protected areas; nothing was written")
    return _append(document, file, PROTECTED, f"- `{glob}`: {why}")


def set_cap(root: Path, file: PurePosixPath, cap: int) -> Edited:
    """Rewrite Nits' `cap:` line, or write one at the top of Nits"""
    if cap < 0:
        raise ReleaseError(f"the Nits cap is a whole number from 0; got {cap}")
    document, _ = _editable(root, file, create=True)
    line = f"cap: {cap}"
    section = _section(document, NITS)
    if section is None:
        return _create(document, file, NITS, line)
    for number, text in section.body:
        if _CAP.fullmatch(text) is not None:
            document.replace(number - 1, line)
            document.write()
            return Edited(file, number, line)
    index = document.insert(document.section_start(section.line - 1), [line], pad=True)
    document.write()
    return Edited(file, index + 1, line)


def retire(root: Path, file: PurePosixPath, target: str) -> Edited:
    """Remove an Important rule by its id (I-n) or a Protected areas item by its glob; a rule's
    id is never handed out again"""
    document, _ = _editable(root, file, create=False)
    if _RULE_ID.fullmatch(target) is not None:
        name, pattern, key = IMPORTANT, _IMPORTANT_ITEM, str(RuleId.parse(target))
    else:
        name, pattern, key = PROTECTED, _PROTECTED_ITEM, str(Glob(target))
    section = _section(document, name)
    for number, line in section.body if section is not None else ():
        item = pattern.fullmatch(line)
        if item is not None and item.group(1) == key:
            document.delete(number - 1)
            document.write()
            return Edited(file, number, line)
    raise ReleaseError(f"no {target} in {file}'s {name}; nothing was written")


def _editable(root: Path, file: PurePosixPath, create: bool) -> tuple[Document, Rubric]:
    """The file's lines and rubric; refused (exit 2) when `check` refuses it, so nothing is
    written over a broken file. A missing file is a new, empty one when create is set"""
    path = root / file
    if not path.exists():
        if not create:
            raise ReleaseError(f"no {file} in {root}; nothing to retire")
        return Document.new(path), Rubric((), None, (), ())
    if not path.resolve().is_relative_to(root.resolve()):
        raise ReleaseError(f"{file} resolves to {path.resolve()}, outside the repository {root}; refusing to edit it")
    document = Document.read(path)
    rubric, problems = parse(document.text(), file)
    if problems:
        listed = "\n".join(f"  {p}" for p in problems)
        raise ReleaseError(
            f"{file} doesn't pass `{cli_command()} review check`, so nothing was written; fix it first:\n{listed}"
        )
    return document, rubric


def _section(document: Document, name: str) -> _Section | None:
    return next((s for s in _sections(document.text()) if s.heading == name), None)


def _append(document: Document, file: PurePosixPath, name: str, line: str) -> Edited:
    """The line after the section's last one, or the section, written in its place"""
    section = _section(document, name)
    if section is None:
        return _create(document, file, name, line)
    filled = [number for number, text in section.body if text.strip()]
    if filled:
        index = document.insert(filled[-1], [line])
    else:
        index = document.insert(document.section_start(section.line - 1), [line], pad=True)
    document.write()
    return Edited(file, index + 1, line)


def _create(document: Document, file: PurePosixPath, name: str, line: str) -> Edited:
    """Write `## <name>` holding the line in its fixed place: before the first structured section
    that comes after it, else after the last that comes before it, else at the end"""
    sections = _sections(document.text())
    rank = STRUCTURED.index(name)
    later = [s for s in sections if s.heading in STRUCTURED and STRUCTURED.index(s.heading) > rank]
    earlier = [i for i, s in enumerate(sections) if s.heading in STRUCTURED and STRUCTURED.index(s.heading) < rank]
    if later:
        index = later[0].line - 1
    elif earlier and earlier[-1] + 1 < len(sections):
        index = sections[earlier[-1] + 1].line - 1  # the heading of the section after it
    else:
        index = len(document.lines)
    first = document.insert(index, [f"## {name}", "", line], pad=True)
    document.write()
    return Edited(file, first + 3, line)
