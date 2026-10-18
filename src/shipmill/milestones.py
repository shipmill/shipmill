"""Whether a milestone's goal is done (spec 022): the specs behind its issues are built, and
every build issue of theirs is in the candidate's base.

A spec belongs to a milestone when its Issues section names an issue of this repository in
the milestone, or when an issue in the milestone links the spec's file in its body. Specs
are read at main's head. A milestone that holds no spec is done as it was before: no open
issues and at least one closed, which the caller checks first.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from shipmill.errors import ReleaseError
from shipmill.fragments import AtRevision
from shipmill.github import CloseReason, GitHub, IssueClose, IssueComment, MilestoneIssues
from shipmill.gitrepo import Git

SPECS = "docs/specs"
NOT_SPECS = ("TEMPLATE.md", "README.md")
_SPEC_NAME = r"(\d{3,})-[a-z0-9]+(?:-[a-z0-9]+)*\.md"
SPEC_FILE = re.compile(rf"^{_SPEC_NAME}$")
SPEC_LINK = re.compile(rf"{SPECS}/({_SPEC_NAME})")
STATUS = re.compile(r"^status: (\S+)$")
ISSUE_ITEM = re.compile(r"^- (?:([\w.-]+/[\w.-]+))?#(\d+)(?![\w])")
CLOSE_CONFIRMED = "<!-- shipmill:close-confirmed -->"
TRUSTED = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


class SpecStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    BUILT = "built"


@dataclass(frozen=True, slots=True, order=True)
class SpecId:
    number: int

    def __str__(self) -> str:
        return f"S-{self.number:03d}"


@dataclass(frozen=True, slots=True)
class IssueRef:
    """A line of a spec's Issues section: owner/repo#N, or #N for this repository"""

    repo: str | None
    number: int

    def here(self, repo: str) -> bool:
        return self.repo is None or self.repo.lower() == repo.lower()


@dataclass(frozen=True, slots=True)
class Spec:
    id: SpecId
    file: str  # its name in docs/specs
    status: str  # as written; checked once the spec belongs to a milestone
    issues: tuple[IssueRef, ...]

    def built(self) -> SpecStatus:
        """Its status; ReleaseError for one the spec gate doesn't know"""
        if self.status not in set(SpecStatus):
            known = ", ".join(SpecStatus)
            raise ReleaseError(f"{SPECS}/{self.file} says status {self.status!r}; a spec's status is one of {known}")
        return SpecStatus(self.status)

    def numbers(self, repo: str) -> list[int]:
        """Its build issues in this repository, in the order it lists them"""
        return [ref.number for ref in self.issues if ref.here(repo)]


def parse_spec(name: str, text: str) -> Spec:
    """The status line under the title and the Issues section's items; a line of another
    shape is the spec checker's to report, and is skipped here"""
    match = SPEC_FILE.match(name)
    if match is None:
        raise ReleaseError(f"{SPECS}/{name} is not named NNN-<slug>.md")
    status = ""
    section: str | None = None
    issues = []
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        elif section is None and not status and (found := STATUS.match(line)):
            status = found.group(1)
        elif section == "Issues" and (item := ISSUE_ITEM.match(line.strip())):
            issues.append(IssueRef(item.group(1), int(item.group(2))))
    return Spec(SpecId(int(match.group(1))), name, status, tuple(issues))


def specs_at(git: Git, rev: str) -> list[Spec]:
    """The specs in docs/specs at rev, by number; none when rev has no such folder"""
    source = AtRevision(git, rev)
    if not source.has(SPECS):
        return []
    names = sorted(n for n in source.files(SPECS) if "/" not in n and n not in NOT_SPECS and n.endswith(".md"))
    specs = [parse_spec(n, source.text(f"{SPECS}/{n}")) for n in names]
    return sorted(specs, key=lambda s: s.id)


def belonging(specs: Sequence[Spec], listed: MilestoneIssues) -> list[Spec]:
    """The specs of the milestone: each whose Issues section names one of its issues, or
    whose file one of its issues links"""
    numbers = {n for n, _ in listed.issues}
    linked = {m.group(1) for _, body in listed.issues for m in SPEC_LINK.finditer(body)}
    return [s for s in specs if s.file in linked or any(n in numbers for n in s.numbers(listed.repo))]


class Holdup(StrEnum):
    NOT_BUILT = "not built"
    OPEN = "open"
    NOT_IN_BASE = "not in base"
    NO_MERGED_PULL = "no merged pull request"


@dataclass(frozen=True, slots=True)
class Wait:
    """What holds one spec of a milestone: the first reason found"""

    spec: SpecId
    holdup: Holdup
    status: SpecStatus | None = None  # with NOT_BUILT
    issue: int | None = None  # with the others
    where: str = ""  # with NOT_IN_BASE: what the candidate's base is, such as the rc's tag

    def __str__(self) -> str:
        match self.holdup:
            case Holdup.NOT_BUILT:
                return f"{self.spec} is {self.status}, not built"
            case Holdup.OPEN:
                return f"{self.spec}'s #{self.issue} is open"
            case Holdup.NOT_IN_BASE:
                return f"{self.spec}'s #{self.issue} is not in {self.where}"
            case Holdup.NO_MERGED_PULL:
                return f"{self.spec}'s #{self.issue} closed with no merged pull request"


@dataclass(frozen=True, slots=True)
class Verdict:
    """A milestone with no open issues: the specs it holds, and what holds any of them"""

    milestone: str
    specs: tuple[SpecId, ...]
    waits: tuple[Wait, ...]

    @property
    def done(self) -> bool:
        return not self.waits

    @property
    def reasons(self) -> list[str]:
        """One line per spec that waits, `milestone <title>: <what holds it>`"""
        return [f"milestone {self.milestone}: {w}" for w in self.waits]

    @property
    def reason(self) -> str:
        if self.waits:
            return "; ".join(self.reasons)
        if self.specs:
            return f"milestone {self.milestone} built: {', '.join(str(s) for s in self.specs)}"
        return f"milestone {self.milestone} has no open issues"


def confirmed(close: IssueClose, github: GitHub, app_id: int | None) -> bool:
    """A comment after the issue's last close whose first line is the close-confirmed marker,
    by an OWNER, MEMBER, or COLLABORATOR or by the App of [agents] app_id (D-29)"""
    if close.closed_at is None:
        return False
    for c in close.comments:
        if c.created_at > close.closed_at and _first_line(c.body) == CLOSE_CONFIRMED and _trusted(c, github, app_id):
            return True
    return False


def _first_line(body: str) -> str:
    return body.lstrip().split("\n", 1)[0].strip()


def _trusted(comment: IssueComment, github: GitHub, app_id: int | None) -> bool:
    if comment.association in TRUSTED:
        return True
    return comment.bot and app_id is not None and github.app_id(comment.author) == app_id


def _holdup(close: IssueClose, git: Git, github: GitHub, base: str, app_id: int | None) -> Holdup | None:
    if close.open:
        return Holdup.OPEN
    if close.reason is CloseReason.NOT_PLANNED:
        return None
    if any(git.is_ancestor(fix, base) for fix in close.fixes) or confirmed(close, github, app_id):
        return None
    return Holdup.NOT_IN_BASE if close.fixes else Holdup.NO_MERGED_PULL


def verdict(
    git: Git, github: GitHub, title: str, head: str, base: str, where: str, app_id: int | None = None
) -> Verdict:
    """Whether the milestone, which has no open issues, holds a finished goal: its specs read
    at head (main's), their build issues' fixes looked for in base (the candidate's, which
    `where` names). With no spec in the repository, GitHub isn't asked anything more"""
    specs = specs_at(git, head)
    if not specs:
        return Verdict(title, (), ())
    listed = github.milestone_issues(title)
    members = belonging(specs, listed)
    waits: list[Wait] = []
    built = []
    for spec in members:
        status = spec.built()
        if status is SpecStatus.BUILT:
            built.append(spec)
        else:
            waits.append(Wait(spec.id, Holdup.NOT_BUILT, status=status))
    numbers = sorted({n for s in built for n in s.numbers(listed.repo)})
    closes = {c.number: c for c in github.issue_closes(numbers)} if numbers else {}
    for spec in built:
        for n in spec.numbers(listed.repo):
            holdup = _holdup(closes[n], git, github, base, app_id)
            if holdup is not None:
                waits.append(Wait(spec.id, holdup, issue=n, where=where))
                break
    waits.sort(key=lambda w: w.spec)
    return Verdict(title, tuple(s.id for s in members), tuple(waits))
