"""`shipmill decide classify` (spec 030): the zones code detects for a change, each with its
level and the reason, the strictest level among them, and the D-n candidates.

The levels, REVIEW.md's Protected areas, and the decisions log are read at the base ref,
never from the change, so a pull request that edits [decisions] is judged by the levels it
would replace. A change given as paths (--files) is judged by its paths alone; a pull
request's (--pr) by its files and their patches too, read through gh:

- direction: docs/product.md, or a path under docs/product/
- decision-policy: .github/shipmill.toml whose [decisions] table differs between the merge
  base and the head, compared parsed, so a comment or a reorder doesn't count
- security: any other path under .github/, or the config's other tables, compared parsed
- protected: a path a REVIEW.md Protected areas glob on the base covers, as pr_gate.py matches
- scope: a docs/specs/*.md whose header's status line reads approved at the head and not at
  the merge base, both read whole
- contract-change: an added line under a heading [bump] major lists, in the changelog or a
  changelog fragment
"""

import fnmatch
import re
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Protocol

from shipmill import cli_command
from shipmill.config import CONFIG_PATH, loads
from shipmill.decide import Candidate, Level, Zone, candidates
from shipmill.errors import ReleaseError
from shipmill.github import FileChange, PullChange
from shipmill.gitrepo import Git
from shipmill.policy import Policy
from shipmill.review import REVIEW, Protected
from shipmill.review import parse as parse_review

DIRECTION = "docs/product.md"
DIRECTION_DIR = "docs/product/"
GITHUB_DIR = ".github/"
CONFIG = CONFIG_PATH.as_posix()
DECISIONS_TABLE = "decisions"
SPECS = "docs/specs/*.md"
LOGS = ("DECISIONS.md", "docs/decisions.md")  # decisions.py's order
DEFAULT_REF = "origin/HEAD"
FRAGMENTS_README = "README.md"

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_TITLE = re.compile(r"^# S-\d{3,}: \S")  # specs.py's TITLE and STATUS
_STATUS = re.compile(r"^status: (\S+)$")
APPROVED = "approved"


class Pulls(Protocol):
    """What classify reads of a pull request; GhCli is one, tests pass a fake"""

    def pull_change(self, number: int) -> PullChange: ...

    def text_at(self, sha: str, path: str) -> str: ...


@dataclass(frozen=True, slots=True)
class RepoPath:
    """A changed path relative to the repo's root, as git and GitHub spell it"""

    value: str

    def __post_init__(self) -> None:
        pure = PurePosixPath(self.value)
        if not self.value or self.value != self.value.strip() or pure.is_absolute() or ".." in pure.parts:
            raise ReleaseError(f"a changed path is relative to the repo's root, without '..'; got {self.value!r}")
        if str(pure) != self.value or self.value == ".":
            raise ReleaseError(f"a changed path is written as git writes it, such as src/x.py; got {self.value!r}")

    @classmethod
    def given(cls, text: str) -> RepoPath:
        """A path as a person types it: a leading ./ is dropped"""
        return cls(text.removeprefix("./"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Detected:
    """A zone code detects in a change, at the base's level, with why"""

    zone: Zone
    level: Level
    reason: str

    def record(self) -> dict[str, str]:
        return {"zone": self.zone.value, "level": self.level.value, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class Classification:
    zones: tuple[Detected, ...]
    candidates: tuple[Candidate, ...]

    @property
    def level(self) -> Level | None:
        """The strictest level among the zones; None when code detects none"""
        return Level.strictest(z.level for z in self.zones) if self.zones else None

    def record(self) -> dict[str, Any]:
        return {
            "level": None if self.level is None else self.level.value,
            "zones": [z.record() for z in self.zones],
            "candidates": [c.record() for c in self.candidates],
        }

    def text(self) -> str:
        lines = [f"level: {'none, no zone detected' if self.level is None else self.level.value}"]
        lines += [f"zone: {z.zone.value} at {z.level.value}: {z.reason}" for z in self.zones]
        lines += [f"candidate: {c.decision}: {c.title}" for c in self.candidates]
        return "\n".join(lines) + "\n"


def policy_at(git: Git, ref: str) -> Policy:
    """The config at ref; a ref the checkout lacks, no config there, or one that doesn't parse stops it"""
    if not git.ok("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"):
        raise ReleaseError(f"{ref} is not in {git.root}: run `git -C {git.root} fetch origin`, or pass --ref")
    where = f"{CONFIG} at {ref}"
    text = git.show(ref, CONFIG)
    if text is None:
        raise ReleaseError(f"no {CONFIG} at {ref}, so no levels to read")
    return Policy.parse(loads(text, where), where)


@dataclass(frozen=True, slots=True)
class Base:
    """What the base ref holds: the policy, every REVIEW.md's Protected areas, and the
    decisions log (None without one)"""

    policy: Policy
    protected: Mapping[str, tuple[Protected, ...]]  # by the REVIEW.md listing them
    log: str | None

    @classmethod
    def read(cls, git: Git, ref: str) -> Base:
        """The base at ref; a ref the checkout lacks, or a config or REVIEW.md that doesn't
        parse there, stops it"""
        policy = policy_at(git, ref)
        names = [n for n in git.run("ls-tree", "-r", "-z", "--name-only", ref).split("\0") if n]
        protected: dict[str, tuple[Protected, ...]] = {}
        for name in names:
            if PurePosixPath(name).name != REVIEW:
                continue
            review = git.show(ref, name)
            if review is None:
                raise ReleaseError(f"can't read {name} at {ref}")
            rubric, problems = parse_review(review, PurePosixPath(name))
            if problems:
                fix = f"fix it on the default branch (`{cli_command()} review check`)"
                raise ReleaseError(f"{problems[0]} (at {ref}); {fix}")
            protected[name] = rubric.protected
        tree = set(names)
        log = next((git.show(ref, n) for n in LOGS if n in tree), None)
        return cls(policy, protected, log)

    def level(self, zone: Zone) -> Level:
        return self.policy.decisions.level(zone)

    def covering(self, path: str) -> list[Protected]:
        """The Protected areas of the root's REVIEW.md and its folders' on the way to path that
        cover it, as pr_gate.py reads them"""
        folders = PurePosixPath(path).parents
        wanted = {(folder / REVIEW).as_posix() for folder in folders}
        return [
            area
            for name in sorted((n for n in self.protected if n in wanted), key=lambda n: (n.count("/"), n))
            for area in self.protected[name]
            if covers(area, path)
        ]


def matches(glob: str, path: str) -> bool:
    """pr_gate.py's rule: fnmatch, where `*` also matches `/`, or the path sits under the glob's directory"""
    stem = glob.rstrip("*").rstrip("/")
    return path == glob or fnmatch.fnmatchcase(path, glob) or (bool(stem) and path.startswith(stem + "/"))


def covers(area: Protected, path: str) -> bool:
    """The glob from the repo's root, or, in a subdirectory's REVIEW.md, from its folder too"""
    folder = area.file.parent.as_posix()
    inner = path[len(folder) + 1 :] if folder != "." and path.startswith(folder + "/") else None
    return matches(str(area.glob), path) or (inner is not None and matches(str(area.glob), inner))


class _Found:
    """The reasons found per zone, kept in the zone table's order"""

    def __init__(self, base: Base) -> None:
        self.base = base
        self.reasons: dict[Zone, list[str]] = {}

    def add(self, zone: Zone, reason: str) -> None:
        listed = self.reasons.setdefault(zone, [])
        if reason not in listed:
            listed.append(reason)

    def result(self, paths: Sequence[str]) -> Classification:
        detected = tuple(
            Detected(zone, self.base.level(zone), "; ".join(self.reasons[zone]))
            for zone in Zone
            if zone in self.reasons
        )
        found = () if self.base.log is None else candidates(self.base.log, paths)
        return Classification(detected, found)


def _by_path(found: _Found, path: str) -> None:
    """The rules a path alone decides; the config's own path is its caller's to judge"""
    if path == DIRECTION or path.startswith(DIRECTION_DIR):
        found.add(Zone.DIRECTION, f"{path} edits the product's direction, which only the maintainer changes (D-34)")
    if path.startswith(GITHUB_DIR) and path != CONFIG:
        found.add(Zone.SECURITY, f"{path} is under {GITHUB_DIR}")
    for area in found.base.covering(path):
        found.add(Zone.PROTECTED, f"{path} matches `{area.glob}` ({area.file}): {area.why}")


def classify_paths(base: Base, paths: Iterable[RepoPath]) -> Classification:
    """The zones the paths alone show: no changelog or status-line rule. The config's path
    can't tell which table changed, so it counts as both decision-policy and security"""
    found = _Found(base)
    listed = list(dict.fromkeys(str(p) for p in paths))
    for path in listed:
        _by_path(found, path)
        if path == CONFIG:
            found.add(Zone.DECISION_POLICY, f"{CONFIG} changes, and paths alone can't tell whether [decisions] did")
            found.add(Zone.SECURITY, f"{CONFIG} changes, and paths alone can't tell which of its tables did")
    return found.result(listed)


def classify_pull(base: Base, pulls: Pulls, number: int) -> Classification:
    """The zones a pull request's files and patches show"""
    change = pulls.pull_change(number)
    found = _Found(base)
    listed = list(dict.fromkeys(p for f in change.files for p in f.paths))
    for file in change.files:
        for path in file.paths:
            _by_path(found, path)
        if CONFIG in file.paths:
            _config(found, pulls, change, file)
        if file.status == "removed":
            continue
        if _is_spec(file.path) and _becomes_approved(pulls, change, file):
            found.add(Zone.SCOPE, f"{file.path}'s status line becomes approved")
        if _changelog(base.policy, file.path):
            head = pulls.text_at(change.head, file.path)
            for line, heading in _major_entries(base.policy, file, head, number):
                reason = f"{file.path}:{line} adds an entry under ### {heading}, a [bump] major heading"
                found.add(Zone.CONTRACT_CHANGE, reason)
    return found.result(listed)


def _config(found: _Found, pulls: Pulls, change: PullChange, file: FileChange) -> None:
    """decision-policy when [decisions] differs parsed between the merge base and the head,
    security when another table does; a side that doesn't parse counts as both"""
    sides: list[Mapping[str, Any]] = []
    at_base = file.status != "added" and (file.previous or file.path) == CONFIG
    at_head = file.status != "removed" and file.path == CONFIG
    for side, present in ((change.base, at_base), (change.head, at_head)):
        if not present:  # an added config, a removed one, or one renamed to or from another path
            sides.append({})
            continue
        try:
            sides.append(tomllib.loads(pulls.text_at(side, CONFIG)))
        except tomllib.TOMLDecodeError as exc:
            reason = f"{CONFIG} at {side[:7]} doesn't parse ({exc}), so its tables can't be compared"
            found.add(Zone.DECISION_POLICY, reason)
            found.add(Zone.SECURITY, reason)
            return
    before, after = sides
    if before.get(DECISIONS_TABLE, {}) != after.get(DECISIONS_TABLE, {}):  # an empty table sets nothing
        found.add(Zone.DECISION_POLICY, f"{CONFIG} changes its [{DECISIONS_TABLE}] table")
    if _rest(before) != _rest(after):
        found.add(Zone.SECURITY, f"{CONFIG} changes outside [{DECISIONS_TABLE}]")


def _is_spec(path: str) -> bool:
    return fnmatch.fnmatchcase(path, SPECS) and "/" not in path[len("docs/specs/") :]


def _becomes_approved(pulls: Pulls, change: PullChange, file: FileChange) -> bool:
    """The spec's header status line reads approved at the head and not at the merge base;
    both sides are read whole, since a diff's hunks needn't show the header"""
    if _spec_status(pulls.text_at(change.head, file.path)) != APPROVED:
        return False
    if file.status in ("added", "copied"):  # no such file at the base
        return True
    before = file.previous if file.status == "renamed" and file.previous is not None else file.path
    return _spec_status(pulls.text_at(change.base, before)) != APPROVED


def _spec_status(text: str) -> str | None:
    """The status line as specs.py reads it: the first `status:` line after the title and
    before the first section; a line in the body is not it"""
    titled = False
    for line in text.splitlines():
        if line.startswith("## "):
            return None
        if not titled:
            titled = _TITLE.match(line) is not None
            continue
        status = _STATUS.match(line)
        if status is not None:
            return status.group(1)
    return None


def _rest(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in raw.items() if k != DECISIONS_TABLE}


def _changelog(policy: Policy, path: str) -> bool:
    """The changelog, or a changelog fragment (spec 013); none without [changelog] (#856)"""
    if policy.changelog_config is None:
        return False
    if path == policy.changelog:
        return True
    if policy.fragments is None:
        return False
    folder = policy.fragments.strip("/") + "/"
    name = path[len(folder) :]
    return path.startswith(folder) and name.endswith(".md") and "/" not in name and name != FRAGMENTS_README


def _patch(file: FileChange, number: int) -> tuple[list[tuple[int, str]], list[str]]:
    """The added lines with their line numbers at the head, and the removed lines"""
    if file.patch is None:
        raise ReleaseError(f"GitHub gives no diff for {file.path} in #{number}, so it can't be classified")
    added: list[tuple[int, str]] = []
    removed: list[str] = []
    line = 0
    for text in file.patch.splitlines():
        hunk = _HUNK.match(text)
        if hunk is not None:
            line = int(hunk.group(1))
        elif text.startswith("+"):
            added.append((line, text[1:]))
            line += 1
        elif text.startswith("-"):
            removed.append(text[1:])
        elif not text.startswith("\\"):  # "\ No newline at end of file"
            line += 1
    return added, removed


def _major_entries(policy: Policy, file: FileChange, head: str, number: int) -> list[tuple[int, str]]:
    """Each added line, with its heading, that sits under a ### heading [bump] major lists"""
    majors = policy.major_headings
    if not majors:
        return []
    lines = head.splitlines()
    found = []
    for at, text in _patch(file, number)[0]:
        if not text.strip() or text.startswith("#"):
            continue
        heading = _heading(lines, at)
        if heading in majors:
            found.append((at, heading))
    return found


def _heading(lines: Sequence[str], at: int) -> str | None:
    """The ### heading above line at (1-based), within its ## section; None outside one"""
    for line in reversed(lines[: at - 1]):
        if line.startswith("### "):
            return line[4:].strip()
        if line.startswith("#"):
            return None
    return None
