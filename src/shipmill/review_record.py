"""`review record` (spec 055): the App's record of a review of a pull request's head.

github-pr-triage's landing session records its reviewer's verdict on the head it reviewed, and
`pr_gate.py` reads an agent's code pull request UNREVIEWED until such a record covers the head it
judges. The record is a pull request review posted as the App: event COMMENT, `commit_id` the
head, and a body whose first line is the verdict's marker, followed by the reviewer's report.
Every check runs before the write: the head's form, the report's file, the App, and that the head
is still the pull request's current one; a failure writes nothing.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from shipmill.errors import ReleaseError

_SHA = re.compile(r"[0-9a-f]{40}")


class Verdict(StrEnum):
    """The reviewer's verdict on the head"""

    MERGE = "merge"
    REFUSE = "refuse"

    @property
    def marker(self) -> str:
        """The body's first line, which pr_gate.py reads"""
        return f"<!-- shipmill:review {self.value} -->"


@dataclass(frozen=True, slots=True)
class Head:
    """A pull request's head commit, its full 40-character SHA, lowercase"""

    sha: str

    def __post_init__(self) -> None:
        if _SHA.fullmatch(self.sha) is None:
            raise ReleaseError(f"--head is the reviewed head's full SHA, 40 hex characters; got {self.sha!r}")

    @classmethod
    def parse(cls, text: str) -> Head:
        return cls(text.lower() if re.fullmatch(r"[0-9a-fA-F]{40}", text) else text)

    def __str__(self) -> str:
        return self.sha


class Hub(Protocol):
    """The GitHub side of review record; every call goes as `shipmill gh` makes it"""

    def head(self, number: int) -> str:
        """Pull request number's current head SHA"""
        ...

    def post(self, number: int, head: Head, body: str) -> None:
        """Post the review: event COMMENT, commit_id head, and body"""
        ...


@dataclass(frozen=True, slots=True)
class Request:
    """`review record`'s arguments: the pull request, --head, --verdict, and --body-file"""

    number: int
    head: str
    verdict: Verdict
    body_file: Path


def record(request: Request, hub: Hub, app: Callable[[], None]) -> str:
    """S-055-16: the checks, then the review; the line saying what was recorded. app raises, as
    `shipmill gh` would before a write, when the App isn't available. Any failure raises with
    nothing written"""
    if request.number < 1:
        raise ReleaseError(f"the pull request's number is 1 or more; got {request.number}")
    head = Head.parse(request.head)
    report = _report(request.body_file)
    app()
    current = hub.head(request.number)
    if current != head.sha:
        raise ReleaseError(
            f"--head {head} is not #{request.number}'s current head, {current}: the pull request moved since the "
            "review, so review its current head and record that; nothing was written"
        )
    marker = request.verdict.marker
    hub.post(request.number, head, f"{marker}\n\n{report}" if report else marker)
    return f"recorded {request.verdict} for #{request.number} at {head}"


def _report(path: Path) -> str:
    """--body-file's text, the reviewer's report, without leading or trailing blank lines"""
    try:
        return path.read_text(encoding="utf-8").strip("\n")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReleaseError(f"--body-file {path} can't be read: {exc}") from None
