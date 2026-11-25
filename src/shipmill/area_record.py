"""The production record of an area (spec 083): which areas a failed release raised, and how
many clean releases have touched each since.

An area is the parent directory of a path (`.` for a file at the root). A failed release is an
issue labelled `[operate] incident_label` whose body holds the hidden line `shipmill operate`
writes (`operate.Incident.read`), opened by a bot or an OWNER, MEMBER, or COLLABORATOR (D-16);
anyone else's issue counts for nothing and its body is never parsed. It raises the parent
directories of `git diff --name-only <from> <tag>`, `<from>` being the line's `to`, or, for
`-`, the newest earlier tag in version order. A clean release is a later tag in version order
whose deployment to the same environment reached `success`, that no counted incident names,
and whose own diff from the tag before it touches the area; `clean_releases` of them clear it.

The record reads GitHub's issues and deployments and the checkout only (D-6), and every read
finishes before anything is returned, so a read that fails is an error, never a partial record."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Protocol

from shipmill.decide import CleanReleases
from shipmill.errors import ReleaseError
from shipmill.github import AuthoredIssue, Deployment, DeploymentState, DeploymentStatus
from shipmill.gitrepo import Git
from shipmill.operate import Incident, tag_of
from shipmill.version import Version

TRUSTED = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})  # D-16, with a bot
_MARK = "<!-- shipmill:incident "  # the start of the hidden line Incident.read reads
NO_RECORD = "no failed release on record"


class Reads(Protocol):
    """What the record reads of GitHub"""

    def authored_issues(self, label: str) -> list[AuthoredIssue]:
        """Every issue with the label, open and closed, with who opened it"""
        ...

    def deployments(self, environment: str) -> list[Deployment]:
        """The environment's deployments, newest first"""
        ...

    def deployment_statuses(self, deployment: int) -> list[DeploymentStatus]: ...


class State(StrEnum):
    RAISED = "raised"  # fewer than clean_releases clean releases have touched it since
    CLEARED = "cleared"  # it reads like an area with no record


@dataclass(frozen=True, slots=True)
class Area:
    """An area's newest failed release and the clean releases that touched it since, the
    first clean_releases of them"""

    area: str
    incident: int
    env: str
    tag: Version
    clean: tuple[Version, ...]
    needed: int  # clean_releases

    @property
    def state(self) -> State:
        return State.RAISED if len(self.clean) < self.needed else State.CLEARED

    @property
    def counted(self) -> str:
        """`1 of 3 clean releases since (v1.4.1)`"""
        named = f" ({', '.join(v.tag for v in self.clean)})" if self.clean else ""
        return f"{len(self.clean)} of {self.needed} clean releases since{named}"

    def record(self) -> dict[str, object]:
        return {
            "area": self.area,
            "state": self.state.value,
            "incident": self.incident,
            "env": self.env,
            "tag": self.tag.tag,
            "clean": [v.tag for v in self.clean],
        }

    def text(self) -> str:
        """`RAISED  src/app  v1.4.0 failed in production (#212), 1 of 3 clean releases since (v1.4.1)`"""
        state = self.state.value.upper()
        return f"{state:<7} {self.area}  {self.tag.tag} failed in {self.env} (#{self.incident}), {self.counted}"


@dataclass(frozen=True, slots=True)
class Record:
    clean_releases: int
    areas: tuple[Area, ...]  # raised first, then by area

    def raised(self) -> tuple[Area, ...]:
        return tuple(a for a in self.areas if a.state is State.RAISED)

    def record(self) -> dict[str, object]:
        return {"clean_releases": self.clean_releases, "areas": [a.record() for a in self.areas]}

    def text(self) -> str:
        if not self.areas:
            return NO_RECORD + "\n"
        return "".join(a.text() + "\n" for a in self.areas)


def trusted(authored: AuthoredIssue) -> bool:
    """Whether an issue's author is one whose incident counts: a bot or a trusted association"""
    return authored.bot or authored.association in TRUSTED


def counted(authored: Sequence[AuthoredIssue]) -> list[Incident]:
    """The incidents that count: a trusted author's issues holding the hidden line. A trusted
    issue whose line doesn't read stops the read, rather than drop a failed release unseen"""
    found = []
    for item in authored:
        if not trusted(item):
            continue  # never parsed: an untrusted body can't raise an area or fail the read
        incident = Incident.read(item.issue)
        if incident is None:
            if _MARK in item.issue.body:
                raise ReleaseError(
                    f"incident #{item.issue.number} holds a shipmill:incident line that doesn't read: it takes"
                    " `<!-- shipmill:incident env=<env> tag=<tag> to=<tag or -> state=<state> -->`"
                )
            continue
        found.append(incident)
    return found


def area_of(path: str) -> str:
    """The path's parent directory, `.` for a file at the root"""
    return str(PurePosixPath(path).parent)


def areas_of(paths: Iterable[str]) -> frozenset[str]:
    """The parent directory of each path, `.` for a file at the root"""
    return frozenset(area_of(p) for p in paths)


class _Tree:
    """The checkout's release tags in version order, and the areas each one's diff touches"""

    def __init__(self, git: Git) -> None:
        self._git = git
        self._tags = git.tags()
        self.versions: list[Version] = sorted(t.version for t in self._tags)
        self._known = frozenset(self.versions)

    def has(self, version: Version, incident: int) -> None:
        if version not in self._known:
            raise ReleaseError(
                f"incident #{incident} names {version.tag}, which the checkout lacks: `git fetch --tags` it"
            )

    def before(self, version: Version) -> Version | None:
        """The newest tag before version in version order, never by creation date"""
        earlier = [v for v in self.versions if v < version]
        return earlier[-1] if earlier else None

    def touched(self, since: Version | None, version: Version) -> frozenset[str]:
        """The areas of `git diff --name-only since version`; with no since, of every file the
        tag holds (the first release)"""
        if since is None:
            listed = self._git.run("ls-tree", "-r", "--name-only", version.tag).splitlines()
            return areas_of(p for p in listed if p)
        return areas_of(self._git.changed_paths(since.tag, version.tag))

    def released(self, deployment: Deployment) -> Version | None:
        return tag_of(deployment, self._tags)


def read(git: Git, reads: Reads, label: str, clean_releases: CleanReleases) -> Record:
    """The record of every area a counted incident raised: each area by its newest failed
    release (version order), with the clean releases that touched it since"""
    needed = int(clean_releases)
    try:
        listed = reads.authored_issues(label)
    except ReleaseError as exc:  # S-083-6: named, never a partial record
        raise ReleaseError(f"the issues labelled {label!r} can't be read: {exc}") from None
    incidents = counted(listed)
    if not incidents:
        return Record(needed, ())
    tree = _Tree(git)
    newest: dict[str, Incident] = {}
    for incident in incidents:
        tree.has(incident.tag, incident.number)
        if incident.to is not None:
            tree.has(incident.to, incident.number)
        since = incident.to if incident.to is not None else tree.before(incident.tag)
        for area in tree.touched(since, incident.tag):
            held = newest.get(area)
            if held is None or (incident.tag, incident.number) > (held.tag, held.number):
                newest[area] = incident
    failed = frozenset(i.tag for i in incidents)
    succeeded = _succeeded(reads, tree, {i.env: i.tag for i in _oldest_per_env(newest.values())}, failed)
    diffs: dict[Version, frozenset[str]] = {}

    def touched(version: Version) -> frozenset[str]:
        if version not in diffs:
            diffs[version] = tree.touched(tree.before(version), version)
        return diffs[version]

    found = []
    for area, incident in newest.items():
        later = sorted(v for v in succeeded.get(incident.env, ()) if v > incident.tag)
        clean = tuple(v for v in later if area in touched(v))[:needed]
        found.append(Area(area, incident.number, incident.env, incident.tag, clean, needed))
    return Record(needed, tuple(sorted(found, key=lambda a: (a.state is not State.RAISED, a.area))))


def _oldest_per_env(incidents: Iterable[Incident]) -> list[Incident]:
    """Per environment, the incident with the oldest tag: the tags after it are the candidates"""
    oldest: dict[str, Incident] = {}
    for incident in incidents:
        if incident.env not in oldest or incident.tag < oldest[incident.env].tag:
            oldest[incident.env] = incident
    return list(oldest.values())


def _succeeded(
    reads: Reads, tree: _Tree, after: Mapping[str, Version], failed: frozenset[Version]
) -> dict[str, frozenset[Version]]:
    """Per environment, the tags after its oldest failed one whose deployment there reached
    success, leaving out every tag a counted incident names"""
    found: dict[str, frozenset[Version]] = {}
    for env, since in after.items():
        hits: set[Version] = set()
        try:
            for deployment in reads.deployments(env):
                version = tree.released(deployment)
                if version is None or version <= since or version in failed or version in hits:
                    continue
                if any(s.state is DeploymentState.SUCCESS for s in reads.deployment_statuses(deployment.id)):
                    hits.add(version)
        except ReleaseError as exc:  # S-083-6: named, never a partial record
            raise ReleaseError(f"the deployments to {env} can't be read: {exc}") from None
        found[env] = frozenset(hits)
    return found
