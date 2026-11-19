"""`review record` (spec 055): the App's record of a review of a pull request's head.

github-pr-triage's landing session records its reviewer's verdict on the head it reviewed, and
`pr_gate.py` reads an agent's code pull request UNREVIEWED until such a record covers the head it
judges. The record is a pull request review posted as the App: event COMMENT, `commit_id` the
head, and a body whose first line is the verdict's marker, then, after a second look at a refusal
(spec 075), the findings line with its counts, followed by the reviewer's report.
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
class Findings:
    """S-075-4: the second look's marks over a refusal's findings: confirmed, rejected, and minor"""

    KEYS = ("confirmed", "rejected", "minor")
    _FORM = "--findings is confirmed=N,rejected=N,minor=N, each key once with a whole number of 0 or more"

    confirmed: int
    rejected: int
    minor: int

    def __post_init__(self) -> None:
        for key in self.KEYS:
            count = getattr(self, key)
            if count < 0:
                raise ReleaseError(f"{self._FORM}; {key} is {count}")

    @classmethod
    def parse(cls, text: str) -> Findings:
        """`confirmed=N,rejected=N,minor=N`, the keys in any order; anything else raises"""
        counts: dict[str, int] = {}
        for part in text.split(","):
            key, sep, value = part.partition("=")
            if not sep:
                raise ReleaseError(f"{cls._FORM}; {part!r} in {text!r} is not key=N")
            if key not in cls.KEYS:
                raise ReleaseError(f"{cls._FORM}; {key!r} in {text!r} is not one of {', '.join(cls.KEYS)}")
            if key in counts:
                raise ReleaseError(f"{cls._FORM}; {key} is given twice in {text!r}")
            if re.fullmatch(r"[0-9]+", value) is None:
                raise ReleaseError(f"{cls._FORM}; {key}={value!r} in {text!r} is not a whole number of 0 or more")
            counts[key] = int(value)
        missing = [key for key in cls.KEYS if key not in counts]
        if missing:
            raise ReleaseError(f"{cls._FORM}; {text!r} lacks {', '.join(missing)}")
        return cls(counts["confirmed"], counts["rejected"], counts["minor"])

    def check(self, verdict: Verdict) -> None:
        """S-075-5: a refusal stands on a confirmed finding, and a confirmed finding refuses"""
        if verdict is Verdict.REFUSE and self.confirmed == 0:
            raise ReleaseError(
                "--verdict refuse with --findings confirmed=0: the second look confirmed no finding, so record "
                "--verdict merge with these counts; nothing was written"
            )
        if verdict is Verdict.MERGE and self.confirmed > 0:
            raise ReleaseError(
                f"--verdict merge with --findings confirmed={self.confirmed}: a confirmed finding refuses, so record "
                "--verdict refuse; nothing was written"
            )

    @property
    def line(self) -> str:
        """The body's line right after the verdict's marker, its keys in one order"""
        return f"<!-- shipmill:findings confirmed={self.confirmed} rejected={self.rejected} minor={self.minor} -->"


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
    """`review record`'s arguments: the pull request, --head, --verdict, --body-file, and the
    optional --findings, as its text or parsed"""

    number: int
    head: str
    verdict: Verdict
    body_file: Path
    findings: Findings | str | None = None


def record(request: Request, hub: Hub, app: Callable[[], None]) -> str:
    """S-055-16: the checks, then the review; the line saying what was recorded. app raises, as
    `shipmill gh` would before a write, when the App isn't available. Any failure raises with
    nothing written. S-075-4: given findings, their line follows the verdict's marker"""
    if request.number < 1:
        raise ReleaseError(f"the pull request's number is 1 or more; got {request.number}")
    head = Head.parse(request.head)
    findings = Findings.parse(request.findings) if isinstance(request.findings, str) else request.findings
    if findings is not None:
        findings.check(request.verdict)
    report = _report(request.body_file)
    app()
    current = hub.head(request.number)
    if current != head.sha:
        raise ReleaseError(
            f"--head {head} is not #{request.number}'s current head, {current}: the pull request moved since the "
            "review, so review its current head and record that; nothing was written"
        )
    marker = request.verdict.marker if findings is None else f"{request.verdict.marker}\n{findings.line}"
    hub.post(request.number, head, f"{marker}\n\n{report}" if report else marker)
    return f"recorded {request.verdict} for #{request.number} at {head}"


def _report(path: Path) -> str:
    """--body-file's text, the reviewer's report, without leading or trailing blank lines"""
    try:
        return path.read_text(encoding="utf-8").strip("\n")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReleaseError(f"--body-file {path} can't be read: {exc}") from None
