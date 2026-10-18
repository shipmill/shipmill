"""Line edits of the structured Markdown files agents change through commands (spec 024):
docs/product.md and REVIEW.md. An edit inserts, rewrites, or removes whole lines and leaves
every other line byte for byte as it was, line endings included. The ids an edit hands out
come from the file's git history, so a retired id is never handed out again"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from shipmill.errors import ReleaseError
from shipmill.gitrepo import Git


@dataclass(frozen=True, slots=True)
class LineText:
    """The text an edit writes into one line: not empty, one line, no surrounding whitespace"""

    value: str

    def __post_init__(self) -> None:
        if not self.value or self.value != self.value.strip() or len(self.value.splitlines()) != 1:
            raise ReleaseError(f"the text is one line, not empty, without surrounding whitespace; got {self.value!r}")

    def __str__(self) -> str:
        return self.value


class Document:
    """A file's lines, each with its own line ending; only the lines an edit touches change"""

    def __init__(self, path: Path, lines: list[str]) -> None:
        self.path = path
        self.lines = lines
        self.eol = next((_ending(line) for line in lines if _ending(line)), "\n")  # the file's own

    @classmethod
    def read(cls, path: Path) -> Document:
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReleaseError(f"{path} is not UTF-8 text: {exc}") from None
        return cls(path, text.splitlines(keepends=True))

    @classmethod
    def new(cls, path: Path) -> Document:
        return cls(path, [])

    def text(self) -> str:
        return "".join(self.lines)

    def content(self, index: int) -> str:
        """Line `index` (from 0) without its line ending"""
        line = self.lines[index]
        return line[: len(line) - len(_ending(line))]

    def blank(self, index: int) -> bool:
        return not self.content(index).strip()

    def insert(self, index: int, lines: Sequence[str], pad: bool = False) -> int:
        """Insert lines before line `index` (from 0; len(lines) appends); pad puts a blank line
        between them and a non-blank neighbour. Returns the index of the first given line. At
        the end of a file without a final line ending, the old last line gains one and the new
        last line goes without, so the file still ends as it did"""
        block = list(lines)
        prepended = pad and index > 0 and not self.blank(index - 1)
        if prepended:
            block.insert(0, "")
        if pad and index < len(self.lines) and not self.blank(index):
            block.append("")
        unterminated = index == len(self.lines) and self.lines and not _ending(self.lines[-1])
        if unterminated:
            self.lines[-1] += self.eol
        written = [line + self.eol for line in block]
        if unterminated:
            written[-1] = block[-1]
        self.lines[index:index] = written
        return index + 1 if prepended else index

    def replace(self, index: int, line: str) -> None:
        self.lines[index] = line + _ending(self.lines[index])

    def delete(self, index: int) -> None:
        del self.lines[index]

    def section_start(self, heading: int) -> int:
        """Where a line goes at the top of the section whose heading is line `heading` (from 0):
        after the blank line under the heading when there is one, else right under it"""
        under = heading + 1
        return under + 1 if under < len(self.lines) and self.blank(under) else under

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self.text().encode("utf-8"))


def _ending(line: str) -> str:
    for eol in ("\r\n", "\n", "\r"):
        if line.endswith(eol):
            return eol
    return ""


def history_numbers(root: Path, paths: Sequence[PurePosixPath], prefix: str) -> set[int]:
    """Every n of a `- <prefix>-n: ` line the paths ever held on the current branch: the lines
    each commit added, removed, or kept (`git log -p`); none before the first commit"""
    git = Git(root)
    git.run("rev-parse", "--git-dir")  # refuses a folder that isn't a git checkout
    if not git.ok("rev-parse", "--verify", "-q", "HEAD"):
        return set()
    patch = git.run_bytes(
        "log",
        "-p",
        "--format=",
        "--no-color",
        "--no-ext-diff",
        "--no-renames",
        "--",
        *(f":(literal){p}" for p in paths),
    ).decode("utf-8", errors="replace")
    line = re.compile(rf"^[-+ ]- {re.escape(prefix)}-([1-9][0-9]*): ", re.MULTILINE)
    return {int(m.group(1)) for m in line.finditer(patch)}
