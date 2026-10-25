"""The decision policy (spec 030, D-48): every decision an agent meets falls in a zone, and
each zone has one level, from the config's [decisions] section or the zone's default.

- act: the agent decides and goes on
- notify: decides, says so on the item, and goes on; the maintainer may veto within veto_hours
- ask: asks with the needs-decision protocol and leaves the item
- never: may prepare the change, but the maintainer takes the decision by hand

A zone's floor is the lowest level [decisions] may set it to. The release side's stages keep
their levels in [autonomy]: [decisions] can't set them, nor the fixed zones."""

import functools
import importlib.util
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import ModuleType
from typing import Any

from shipmill.autonomy import Autonomy, AutonomyPolicy
from shipmill.config import Table
from shipmill.errors import ReleaseError
from shipmill.gate import skills_dir

VETO_HOURS_KEY = "veto_hours"


class Level(StrEnum):
    """Ordered from the least to the most human involvement"""

    ACT = "act"
    NOTIFY = "notify"
    ASK = "ask"
    NEVER = "never"

    @property
    def rank(self) -> int:
        return _RANK[self]

    def below(self, other: Level) -> bool:
        """Whether this level involves the maintainer less than other does"""
        return self.rank < other.rank

    @classmethod
    def strictest(cls, levels: Iterable[Level]) -> Level:
        """The level with the most human involvement among them; a decision in several zones
        takes it"""
        found = tuple(levels)
        if not found:
            raise ReleaseError("the strictest level needs at least one level")
        return max(found, key=lambda level: level.rank)


_RANK = {level: rank for rank, level in enumerate(Level)}


class Zone(StrEnum):
    """The zones [decisions] names, in the zone table's order: by reversibility, then blast
    radius. An id is part of the contract: never renamed or reused"""

    DIRECTION = "direction"
    DECISION_POLICY = "decision-policy"
    SCOPE = "scope"
    RULE_DEPARTURE = "rule-departure"
    CONTRACT_CHANGE = "contract-change"
    CONTRACT_ADDITION = "contract-addition"
    SECURITY = "security"
    PROTECTED = "protected"
    INTERPRETATION = "interpretation"
    TRIAGE_VERDICT = "triage-verdict"
    IMPLEMENTATION = "implementation"
    UNKNOWN = "unknown"


class ReleaseZone(StrEnum):
    """The release side's zones: [autonomy] sets them, or a decision fixes them, never
    [decisions]"""

    RELEASE = "release"
    BREAKING_RELEASE = "breaking-release"
    DEPLOY = "deploy"
    ROLLBACK = "rollback"
    INTAKE = "intake"
    UPGRADE = "upgrade"


@dataclass(frozen=True, slots=True)
class ZoneRule:
    """A zone's default level, and its floor with the reason for it; no floor lets [decisions]
    set any level"""

    default: Level
    floor: Level | None = None
    why: str = ""

    def __post_init__(self) -> None:
        if (self.floor is None) != (not self.why):
            raise ReleaseError("a zone's floor comes with its reason, and only a floor does")
        if self.floor is not None and self.default.below(self.floor):
            raise ReleaseError(f"a zone's default {self.default} is below its floor {self.floor}")


# Why a zone has its floor, for the refusal's fix; the floors themselves are the table's
_WHY = {
    Zone.DIRECTION: "only the maintainer changes the direction (D-34)",
    Zone.DECISION_POLICY: "only the maintainer changes [decisions] (D-48)",
    Zone.SCOPE: "only the maintainer accepts an opportunity, approves a spec, or plans a goal (D-10)",
    Zone.RULE_DEPARTURE: "a departure from a D-n or a spec's criterion needs the maintainer's approval (Q-5)",
    Zone.SECURITY: "a change to workflows, secrets, or permissions is always told (D-48)",
    Zone.UNKNOWN: "a decision no zone covers waits for the maintainer (D-48)",
}
_TABLE = ("github-issue-triage", "scripts", "decisions.py")


@functools.cache
def _log() -> ModuleType:
    """decisions.py, the decisions log's script: the zone table and the log's parser live there"""
    script = skills_dir().joinpath(*_TABLE)
    spec = importlib.util.spec_from_file_location("shipmill_decisions_log", script)
    if spec is None or spec.loader is None:
        raise ReleaseError(f"can't load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@functools.cache
def zones() -> Mapping[Zone, ZoneRule]:
    """Each zone's rule, in the zone table's order. The table (ids, defaults, floors) has one
    copy, decisions.py's ZONES and LEVELS, which the skill scripts read too; a table that
    disagrees with Zone or Level stops here rather than being guessed at"""
    module = _log()
    script = skills_dir().joinpath(*_TABLE)
    levels, table = tuple(module.LEVELS), dict(module.ZONES)
    if levels != tuple(Level):
        raise ReleaseError(f"{script}: LEVELS {list(levels)} are not {[level.value for level in Level]}")
    if list(table) != list(Zone):
        raise ReleaseError(f"{script}: ZONES {list(table)} are not {[zone.value for zone in Zone]}")
    rules = {}
    for zone in Zone:
        default, floor = table[zone.value]
        rules[zone] = ZoneRule(Level(default), None if floor is None else Level(floor), _WHY.get(zone, ""))
    return rules


# Zones [decisions] can't set at all, whatever the value
_FIXED = {
    Zone.DECISION_POLICY.value: "is fixed at never: only the maintainer changes [decisions] (D-48); remove the key",
    ReleaseZone.BREAKING_RELEASE.value: (
        "is fixed: a breaking stable release waits for a person's hand start (D-39); remove the key"
    ),
}


_VETO_LOW = 1
_VETO_HIGH = 168  # a week
_VETO_DEFAULT = 24


@dataclass(frozen=True, slots=True)
class VetoHours:
    """The notify window: how long the maintainer has to veto a decided comment, 1 to 168"""

    hours: int = _VETO_DEFAULT

    def __post_init__(self) -> None:
        if not isinstance(self.hours, int) or isinstance(self.hours, bool) or not _VETO_LOW <= self.hours <= _VETO_HIGH:
            raise ReleaseError(f"{VETO_HOURS_KEY} must be in {_VETO_LOW}..{_VETO_HIGH}, got {self.hours!r}")

    def __int__(self) -> int:
        return self.hours


@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    """The [decisions] section: the levels the config sets, over each zone's default"""

    configured: Mapping[Zone, Level] = field(default_factory=dict)
    veto_hours: VetoHours = VetoHours()

    def __post_init__(self) -> None:
        if Zone.DECISION_POLICY in self.configured:
            raise ReleaseError(f"[decisions]: {Zone.DECISION_POLICY} {_FIXED[Zone.DECISION_POLICY.value]}")
        for zone, level in self.configured.items():
            _check_floor(zone, level, "[decisions]")

    @classmethod
    def parse(cls, t: Table) -> DecisionPolicy:
        configured: dict[Zone, Level] = {}
        for key in t.raw:
            if key == VETO_HOURS_KEY:
                continue
            zone, level = _zone(t, key), _level(t, key)
            _check_floor(zone, level, t.where)
            configured[zone] = level
        hours = t.integer(VETO_HOURS_KEY, default=_VETO_DEFAULT, low=_VETO_LOW, high=_VETO_HIGH)
        assert hours is not None  # a default is given
        return cls(configured, VetoHours(hours))

    def level(self, zone: Zone) -> Level:
        """The zone's level: the config's, or the zone's default"""
        return self.configured.get(zone, zones()[zone].default)

    def is_configured(self, zone: Zone) -> bool:
        """Whether [decisions] sets the zone's level, rather than its default"""
        return zone in self.configured

    @property
    def levels(self) -> Mapping[Zone, Level]:
        """Every zone's level, in the zone table's order"""
        return {zone: self.level(zone) for zone in Zone}


def _zone(t: Table, key: str) -> Zone:
    """The zone a key names; a fixed, a release-side, or an unknown key is refused with its fix"""
    if key in _FIXED:
        raise ReleaseError(f"{t.where}: {key} {_FIXED[key]}")
    if key in set(ReleaseZone):
        raise ReleaseError(f"{t.where}: {key} is set in [autonomy] {key}; move it there")
    if key not in set(Zone):
        zones = ", ".join(z.value for z in Zone)
        raise ReleaseError(f"{t.where}: unknown key {key!r}; a key is {VETO_HOURS_KEY} or a zone id: {zones}")
    return Zone(key)


def _level(t: Table, key: str) -> Level:
    """A zone's level; refused naming the four levels"""
    value = t.raw[key]
    if not isinstance(value, str) or value not in set(Level):
        raise ReleaseError(f"{t.where}: {key} must be one of {[level.value for level in Level]}, got {value!r}")
    return Level(value)


def _check_floor(zone: Zone, level: Level, where: str) -> None:
    rule = zones()[zone]
    if rule.floor is not None and level.below(rule.floor):
        raise ReleaseError(f'{where}: {zone} = "{level}" is below its floor {rule.floor}: {rule.why}')


# -- `shipmill decide levels` ------------------------------------------------------------------


class Source(StrEnum):
    """Where a zone's level comes from"""

    DEFAULT = "default"
    CONFIG = "config"
    AUTONOMY = "autonomy"
    FIXED = "fixed"


@dataclass(frozen=True, slots=True)
class ZoneLevel:
    """One row of `decide levels`: a zone, its level (None: agents take no part, as under
    [autonomy] observe), its floor, and where the level comes from"""

    zone: Zone | ReleaseZone
    level: Level | None
    floor: Level | None
    source: Source

    def record(self) -> dict[str, str | None]:
        return {
            "zone": self.zone.value,
            "level": None if self.level is None else self.level.value,
            "floor": None if self.floor is None else self.floor.value,
            "source": self.source.value,
        }

    def text(self) -> str:
        level = "none" if self.level is None else self.level.value
        floor = "none" if self.floor is None else self.floor.value
        return f"{self.zone.value:<18} {level:<7} floor {floor:<7} {self.source.value}"


# The level an agent has at a release-side stage: under propose the proposal issue is the question
_AUTONOMY: Mapping[Autonomy, Level | None] = {
    Autonomy.ACT: Level.ACT,
    Autonomy.PROPOSE: Level.ASK,
    Autonomy.OBSERVE: None,
}
# From the least to the most held back, to pick the stage the deploy row shows
_HELD = (Autonomy.ACT, Autonomy.PROPOSE, Autonomy.OBSERVE)


def agent_level(autonomy: Autonomy) -> Level | None:
    """A release-side stage's level for agents: act for act, ask for propose, none for observe"""
    return _AUTONOMY[autonomy]


def levels(decisions: DecisionPolicy, autonomy: AutonomyPolicy) -> tuple[ZoneLevel, ...]:
    """Every zone, the agent zones in the zone table's order, then the release side's. Deploy
    shows its most held-back environment, act when [autonomy] lists none (D-7)"""
    rows = []
    for zone, rule in zones().items():
        if zone is Zone.DECISION_POLICY:
            source = Source.FIXED
        else:
            source = Source.CONFIG if decisions.is_configured(zone) else Source.DEFAULT
        rows.append(ZoneLevel(zone, decisions.level(zone), rule.floor, source))
    deploy = max(autonomy.deploy.values(), key=_HELD.index, default=Autonomy.ACT)
    stages = {
        ReleaseZone.RELEASE: autonomy.release,
        ReleaseZone.DEPLOY: deploy,
        ReleaseZone.ROLLBACK: autonomy.rollback,
        ReleaseZone.INTAKE: autonomy.intake,
        ReleaseZone.UPGRADE: autonomy.upgrade,
    }
    for release_zone in ReleaseZone:
        if release_zone is ReleaseZone.BREAKING_RELEASE:  # D-39: a trigger only proposes
            rows.append(ZoneLevel(release_zone, Level.ASK, None, Source.FIXED))
        else:
            rows.append(ZoneLevel(release_zone, agent_level(stages[release_zone]), None, Source.AUTONOMY))
    return tuple(rows)


# -- the D-n candidates of a change ------------------------------------------------------------

_DECISION_ID = re.compile(r"D-[1-9][0-9]*")


@dataclass(frozen=True, slots=True)
class Candidate:
    """An active D-n whose "Applies to" covers a changed path: the session checks whether the
    change departs from it (rule-departure); code can't tell, so it is never a zone"""

    decision: str
    title: str

    def __post_init__(self) -> None:
        if not _DECISION_ID.fullmatch(self.decision):
            raise ReleaseError(f"a decision's id is D-n, got {self.decision!r}")

    def record(self) -> dict[str, str]:
        return {"decision": self.decision, "title": self.title}


def candidates(log: str, paths: Sequence[str]) -> tuple[Candidate, ...]:
    """The active entries of a decisions log that `decisions.py find` gives for paths, by id"""
    module = _log()
    entries: list[Any] = module.parse(log)[0]
    found = [e for e in entries if e.active and any(module.matches(e, path) for path in paths)]
    return tuple(Candidate(f"D-{e.number}", str(e.title)) for e in sorted(found, key=lambda e: e.number))
