"""The earned landing level (spec 083, D-101): a pull request in protected or security may land
at the lower level [decisions.earned] bounds, when its four pieces of evidence hold.

| Evidence | Holds when |
|---|---|
| checks | the default branch requires at least one status check that proves (spec 080) |
| size | the change's added plus deleted lines are at most max_lines |
| record | no area the change touches is raised |
| kind | no path the change touches is of a ceiling kind |

A path whose level is never (the zone's or a part's) never earns, no path earns below its
zone's floor, and without [decisions.earned] nothing earns (D-63). The rule is a pure function
of classify's zones, the change's line counts, the base's [decisions], the raised areas, and
the merge-checks reading, so tests/landing/seeded.toml scores it without GitHub."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import PurePosixPath

from shipmill.classify import Classification, Detected, PathLevel, PathSource, matches
from shipmill.decide import EARNED_ZONES, DecisionPolicy, Earned, Level, Zone, zones
from shipmill.errors import ReleaseError

NOT_READ = "not read: [decisions.earned] is not set"


class Kind(StrEnum):
    """A kind of change that never earns, whatever its evidence"""

    CONTROLS = "controls"  # shipmill's own, and every workflow and action
    INFRASTRUCTURE = "infrastructure"
    DEPENDENCIES = "dependencies"  # where a new advisory comes in


_DEPENDENCY_FILES = (
    "pyproject.toml", "uv.lock", "requirements*.txt", "poetry.lock", "package.json", "package-lock.json",
    "pnpm-lock.yaml", "yarn.lock", "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "Gemfile", "Gemfile.lock",
)  # fmt: skip

# The ceiling kinds' paths, matched as spec 057 matches parts; a glob starting `**/` matches at
# the root too. Extending the table is a contract tweak, not a change to spec 083
CEILING: tuple[tuple[Kind, tuple[str, ...]], ...] = (
    (
        Kind.CONTROLS,
        (
            ".github/shipmill.toml",
            ".github/CODEOWNERS",
            "CODEOWNERS",
            "REVIEW.md",
            "CLAUDE.md",
            "AGENTS.md",
            "docs/decisions.md",
            "DECISIONS.md",
            ".claude/**",
            ".claude-plugin/**",
            ".github/workflows/**",
            ".github/actions/**",
        ),  # fmt: skip
    ),
    (
        Kind.INFRASTRUCTURE,
        (
            "**/*.tf",
            "**/*.tfvars",
            "**/Dockerfile",
            "**/docker-compose*.yml",
            "**/migrations/**",
            "infra/**",
            "deploy/**",
            "k8s/**",
            "helm/**",
        ),  # fmt: skip
    ),
    (Kind.DEPENDENCIES, (".github/dependabot.yml", *(f"**/{name}" for name in _DEPENDENCY_FILES))),
)

_ANYWHERE = "**/"


def _matches(glob: str, path: str) -> bool:
    return matches(glob, path) or (glob.startswith(_ANYWHERE) and matches(glob[len(_ANYWHERE) :], path))


def ceiling_kind(path: str) -> Kind | None:
    """The ceiling kind of a path, the table's first that matches, or None"""
    return next((kind for kind, globs in CEILING if any(_matches(g, path) for g in globs)), None)


def areas_of(paths: Iterable[str]) -> frozenset[str]:
    """The parent directory of each path, `.` for a file at the root (spec 083's area)"""
    return frozenset(str(PurePosixPath(p).parent) for p in paths)


@dataclass(frozen=True, slots=True)
class Changed:
    """A changed path and its added plus deleted lines"""

    path: str
    lines: int

    def __post_init__(self) -> None:
        if not isinstance(self.lines, int) or isinstance(self.lines, bool) or self.lines < 0:
            raise ReleaseError(f"{self.path}'s changed lines are a count from 0, got {self.lines!r}")


@dataclass(frozen=True, slots=True)
class Proof:
    """The merge-checks reading (spec 080): the name of a required check on the default branch
    that proves, or None with why none does (a rules read that fails is one)"""

    check: str | None
    why: str = ""

    def __post_init__(self) -> None:
        if (self.check is None) == (not self.why):
            raise ReleaseError("a merge-checks reading names a proving check, or else why none proves")


@dataclass(frozen=True, slots=True)
class Evidence:
    name: str
    holds: bool
    detail: str

    def record(self) -> dict[str, object]:
        return {"name": self.name, "holds": self.holds, "detail": self.detail}

    def text(self) -> str:
        return f"{self.name}: {'holds' if self.holds else 'fails'}: {self.detail}"


@dataclass(frozen=True, slots=True)
class Lowered:
    """A zone whose level an earned bound set"""

    zone: Zone
    before: Level
    after: Level

    def note(self) -> str:
        """What the zone's reason ends with"""
        return f" (earned {self.after} from {self.before} by [decisions.earned])"


@dataclass(frozen=True, slots=True)
class Landing:
    """The level a change lands at (None: no zone detected), whether a bound lowered it, the
    four pieces of evidence in the table's order, and the zones, each lowered one's paths and
    reason as the bound left them"""

    level: Level | None
    evidence: tuple[Evidence, ...]
    zones: tuple[Detected, ...]
    lowered: tuple[Lowered, ...]

    @property
    def earned(self) -> bool:
        return bool(self.lowered)

    def record(self) -> dict[str, object]:
        return {
            "level": None if self.level is None else self.level.value,
            "earned": self.earned,
            "evidence": [e.record() for e in self.evidence],
        }


def evidence(
    changed: Sequence[Changed], decisions: DecisionPolicy, raised: frozenset[str] | None, proof: Proof | None
) -> tuple[Evidence, ...]:
    """The four pieces of evidence, in the table's order; a raised or proof of None was not read"""
    if proof is None:
        checks = Evidence("checks", False, NOT_READ)
    else:
        checks = Evidence("checks", proof.check is not None, proof.check or proof.why)
    limit = (decisions.earned or Earned()).max_lines
    lines = sum(c.lines for c in changed)
    size = Evidence("size", lines <= limit, f"{lines} of at most {limit} lines")
    if raised is None:
        record = Evidence("record", False, NOT_READ)
    else:
        touched = sorted(areas_of(c.path for c in changed) & raised)
        record = Evidence("record", not touched, f"{', '.join(touched)} raised" if touched else "no raised area")
    ceiling = next(((c.path, k) for c in changed if (k := ceiling_kind(c.path)) is not None), None)
    if ceiling is None:
        kind = Evidence("kind", True, "no ceiling path")
    else:
        kind = Evidence("kind", False, f"{ceiling[0]} is of the {ceiling[1]} kind")
    return (checks, size, record, kind)


def landing(
    found: Classification,
    changed: Sequence[Changed],
    decisions: DecisionPolicy,
    raised: frozenset[str] | None,
    proof: Proof | None,
) -> Landing:
    """The change's landing level. Only with [decisions.earned] and every piece of evidence
    holding does a path that puts protected or security in, above its zone's bound, take the
    bound instead; never a path at never, and never below the zone's floor. raised and proof
    are None when they weren't read, which holds nothing"""
    shown = evidence(changed, decisions, raised, proof)
    earns = decisions.earned is not None and all(e.holds for e in shown)
    detected = tuple(_earn(z, decisions) if earns else z for z in found.zones)
    lowered = tuple(
        Lowered(before.zone, before.level, after.level)
        for before, after in zip(found.zones, detected, strict=True)
        if after.level is not before.level
    )
    level = Level.strictest(z.level for z in detected) if detected else None
    return Landing(level, shown, detected, lowered)


def _earn(detected: Detected, decisions: DecisionPolicy) -> Detected:
    """The zone with each path above its bound at the bound, at most the zone's floor lower"""
    bound = decisions.bound(detected.zone)
    if detected.zone not in EARNED_ZONES or bound is None or not detected.paths:
        return detected
    floor = zones()[detected.zone].floor
    to = bound if floor is None or not bound.below(floor) else floor
    paths = tuple(_lowered(p, to) for p in detected.paths)
    before = Level.strictest(p.level for p in detected.paths)
    # a rule that put the zone in without a path holds the zone's own level: it doesn't earn
    held = [detected.level] if before.below(detected.level) else []
    level = Level.strictest([*(p.level for p in paths), *held])
    if level is detected.level:
        return detected
    note = Lowered(detected.zone, detected.level, level).note()
    return replace(detected, level=level, reason=detected.reason + note, paths=paths)


def _lowered(path: PathLevel, to: Level) -> PathLevel:
    if path.level is Level.NEVER or not to.below(path.level):
        return path
    return PathLevel(path.path, to, PathSource.CONFIG)
