"""How far shipmill goes by itself at each stage, from the config's [autonomy] section, and
the stop switch: an open issue labelled shipmill-hold.

- observe: plan and report only
- propose: open or update an issue saying what it would do; a person does it
- act: do it

The hold turns every act into propose for the whole repository. Release autonomy is read by
the planner; deploy and rollback autonomy by shipmill operate. Triage, fix, and land are the
stages agent sessions run (spec 040): triage and fix act by default and land proposes, so a
pull request waits for a person to merge it unless the config says otherwise. Intake
autonomy is read by the product-intake skill, and is observe or propose only: the
maintainer's accept is its valve.
Upgrade autonomy is read by `shipmill upgrade` (spec 014): how far shipmill goes in proposing
the config upgrades a release adds."""

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol

from shipmill.config import Table
from shipmill.errors import ReleaseError

HOLD_LABEL = "shipmill-hold"
INTAKE = "intake"  # the [autonomy] key of the product-intake skill: not a StageKind, it never acts
UPGRADE = "upgrade"  # the [autonomy] key of config upgrades (spec 014): not a StageKind, it releases nothing
_ENVIRONMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_LANDS = re.compile(r"\b(?:merge\s+when\s+green|land)\b", re.IGNORECASE)


class Autonomy(StrEnum):
    OBSERVE = "observe"
    PROPOSE = "propose"
    ACT = "act"


class StageKind(StrEnum):
    RELEASE = "release"
    DEPLOY = "deploy"
    ROLLBACK = "rollback"
    TRIAGE = "triage"
    FIX = "fix"
    LAND = "land"


AGENT_STAGES = (StageKind.TRIAGE, StageKind.FIX, StageKind.LAND)  # the stages agent sessions run (spec 040)


@dataclass(frozen=True, slots=True)
class EnvironmentName:
    """A deploy environment's name, as a key under [autonomy.deploy]"""

    name: str

    def __post_init__(self) -> None:
        if not _ENVIRONMENT.match(self.name):
            raise ReleaseError(f"an environment name is letters, digits, '.', '_', or '-'; got {self.name!r}")

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class Stage:
    kind: StageKind
    environment: EnvironmentName | None = None

    def __post_init__(self) -> None:
        if (self.kind is StageKind.DEPLOY) != (self.environment is not None):
            raise ReleaseError("a deploy stage names its environment, and only a deploy stage does")

    @classmethod
    def release(cls) -> Stage:
        return cls(StageKind.RELEASE)

    @classmethod
    def rollback(cls) -> Stage:
        return cls(StageKind.ROLLBACK)

    @classmethod
    def deploy(cls, environment: EnvironmentName) -> Stage:
        return cls(StageKind.DEPLOY, environment)

    def __str__(self) -> str:
        return f"deploy.{self.environment}" if self.environment else self.kind.value


class _Issues(Protocol):
    def open_issues(self, label: str) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class Hold:
    """The open shipmill-hold issues, as '#N title'; none means no hold"""

    issues: tuple[str, ...] = ()

    @classmethod
    def read(cls, github: _Issues) -> Hold:
        return cls(tuple(github.open_issues(HOLD_LABEL)))

    @property
    def on(self) -> bool:
        return bool(self.issues)

    @property
    def reason(self) -> str:
        numbers = ", ".join(issue.split(maxsplit=1)[0] for issue in self.issues)
        return f"held by {HOLD_LABEL} {numbers}"


class Source(StrEnum):
    """Where a stage's level comes from, as `shipmill autonomy` shows it (spec 040)"""

    DEFAULT = "default"
    CONFIG = "config"
    PROMPT = "prompt"  # the legacy reading of [agents] prompt, for one minor release
    HOLD = "hold"  # the hold lowers the configured level, wherever it came from


@dataclass(frozen=True, slots=True)
class StageLevel:
    """One row of `shipmill autonomy`: a stage as [autonomy] names its key (triage,
    deploy.production, intake), its configured level, its level under the hold, and the source"""

    stage: str
    configured: Autonomy
    effective: Autonomy
    source: Source

    def record(self) -> dict[str, str]:
        return {
            "stage": self.stage,
            "configured": self.configured.value,
            "effective": self.effective.value,
            "source": self.source.value,
        }

    def text(self, width: int = 18) -> str:
        """The row as a line, the stage padded to width, so a long deploy environment's name aligns"""
        return f"{self.stage:<{width}} {self.configured.value:<7} {self.effective.value:<7} {self.source.value}"


@dataclass(frozen=True, slots=True)
class AutonomyPolicy:
    """The configured autonomy per stage; an environment not listed deploys at act (D-7).
    Intake and upgrade default to propose: an opportunity, like a config upgrade, is the
    maintainer's to accept. Of the agent stages (spec 040) triage and fix default to act and
    land to propose: a pull request is itself a proposal, and merging it stays a person's
    until the config raises land"""

    release: Autonomy = Autonomy.ACT
    rollback: Autonomy = Autonomy.ACT
    deploy: Mapping[EnvironmentName, Autonomy] = field(default_factory=dict)
    intake: Autonomy = Autonomy.PROPOSE
    upgrade: Autonomy = Autonomy.PROPOSE
    triage: Autonomy = Autonomy.ACT
    fix: Autonomy = Autonomy.ACT
    land: Autonomy = Autonomy.PROPOSE
    # the keys the config sets, as `shipmill autonomy` names them (deploy.<env> for a deploy level)
    explicit: frozenset[str] = field(default=frozenset(), compare=False)
    # the agent stages read from [agents] prompt by the legacy reading (spec 040), by name
    from_prompt: frozenset[str] = field(default=frozenset(), compare=False)

    @classmethod
    def parse(cls, t: Table) -> AutonomyPolicy:
        t.allow(*StageKind, INTAKE, UPGRADE)
        # its own words, not Table.table's: the message shows the shape a deploy level takes
        if not isinstance(t.raw.get("deploy", {}), dict):
            raise ReleaseError(f"{t.where}: deploy is a table of environments, such as deploy.production = 'propose'")
        deploy = t.table("deploy", optional=True)
        keys = {key for key in t.raw if key != StageKind.DEPLOY} | {f"{StageKind.DEPLOY}.{name}" for name in deploy.raw}
        return cls(
            release=_level(t, "release"),
            rollback=_level(t, "rollback"),
            deploy={EnvironmentName(name): _level(deploy, name) for name in deploy.raw},
            intake=_intake(t),
            upgrade=_level(t, UPGRADE, default=Autonomy.PROPOSE),
            triage=_level(t, StageKind.TRIAGE),
            fix=_level(t, StageKind.FIX),
            land=_level(t, StageKind.LAND, default=Autonomy.PROPOSE),
            explicit=frozenset(keys),
        )

    def require_environments(self, known: Collection[str], where: str) -> None:
        """Each deploy.<name> names an environment the config declares in [environments]"""
        for name in self.deploy:
            if name.name not in known:
                declared = ", ".join(known) or "none"
                raise ReleaseError(f"{where}: deploy.{name} names no environment in [environments]; known: {declared}")

    def configured(self, stage: Stage) -> Autonomy:
        if stage.kind is StageKind.RELEASE:
            return self.release
        if stage.kind is StageKind.ROLLBACK:
            return self.rollback
        if stage.kind is StageKind.TRIAGE:
            return self.triage
        if stage.kind is StageKind.FIX:
            return self.fix
        if stage.kind is StageKind.LAND:
            return self.land
        assert stage.environment is not None  # Stage guarantees it
        return self.deploy.get(stage.environment, Autonomy.ACT)

    def effective(self, stage: Stage, hold: Hold) -> Autonomy:
        """The stage's autonomy under the hold: an open hold turns act into propose"""
        level = self.configured(stage)
        return Autonomy.PROPOSE if level is Autonomy.ACT and hold.on else level

    def upgrades(self, hold: Hold) -> Autonomy:
        """The upgrade autonomy under the hold: an open hold turns act into propose (D-8)"""
        return Autonomy.PROPOSE if self.upgrade is Autonomy.ACT and hold.on else self.upgrade

    def cause(self, stage: Stage, hold: Hold) -> str:
        """Why the stage doesn't act: the hold, or the configured level. Under propose the
        hold still names itself, as it also refuses a person starting the stage by hand"""
        if self.configured(stage) is not Autonomy.OBSERVE and hold.on:
            return hold.reason
        return f"{stage} autonomy is {self.configured(stage)}"

    def stages(self) -> tuple[Stage, ...]:
        """The stages doctor reports: release, rollback, and each configured environment"""
        envs = sorted(self.deploy, key=str)
        return (Stage.release(), *(Stage.deploy(e) for e in envs), Stage.rollback())

    def sets_agent_stage(self) -> bool:
        """Whether the config sets any of triage, fix, and land, which ends the legacy reading"""
        return any(kind.value in self.explicit for kind in AGENT_STAGES)

    def read_prompt(self, prompt: str) -> AutonomyPolicy:
        """S-040-6, for one minor release: a config that sets none of triage, fix, and land
        reads land as act from a prompt that says "merge when green" or "land"; one that sets
        any of them reads nothing from the prompt"""
        if self.sets_agent_stage() or not lands(prompt):
            return self
        return replace(self, land=Autonomy.ACT, from_prompt=frozenset({StageKind.LAND.value}))

    def is_read_from_prompt(self, stage: Stage) -> bool:
        return str(stage) in self.from_prompt

    def is_set(self, stage: Stage) -> bool:
        """Whether the config sets the stage's key, rather than leaving it to its default"""
        return str(stage) in self.explicit

    def levels(self, hold: Hold, environments: Collection[EnvironmentName] = ()) -> tuple[StageLevel, ...]:
        """Every stage, as `shipmill autonomy` lists it: the agent stages, release, a deploy per
        environment [autonomy] lists or environments names (an unlisted one acts, D-7),
        rollback, intake, and upgrade; each configured, under the hold, and its source"""
        envs = sorted({*self.deploy, *environments}, key=str)
        stages = (*(Stage(kind) for kind in AGENT_STAGES), Stage.release())
        stages += (*(Stage.deploy(e) for e in envs), Stage.rollback())
        rows = [self._row(str(s), self.configured(s), self.effective(s, hold)) for s in stages]
        rows.append(self._row(INTAKE, self.intake, self.intake))  # never act, so the hold has nothing to lower
        rows.append(self._row(UPGRADE, self.upgrade, self.upgrades(hold)))
        return tuple(rows)

    def _row(self, stage: str, configured: Autonomy, effective: Autonomy) -> StageLevel:
        if effective is not configured:
            source = Source.HOLD
        elif stage in self.from_prompt:
            source = Source.PROMPT
        else:
            source = Source.CONFIG if stage in self.explicit else Source.DEFAULT
        return StageLevel(stage, configured, effective, source)


def lands(prompt: str) -> bool:
    """The legacy reading's words (spec 040): "merge when green", or "land" as a word, in any
    case. A word match, so "landing", "landed", "lands", and "island" are not "land"; and a
    literal one, so "do not land" holds "land" too"""
    return _LANDS.search(prompt) is not None


def _level(t: Table, key: str, default: Autonomy = Autonomy.ACT) -> Autonomy:
    """A level, absent meaning the default. Not Table.enum: that one refuses a non-string as
    "must be a string", where a level names its choices either way"""
    value = t.raw.get(key, default.value)
    if not isinstance(value, str) or value not in set(Autonomy):
        raise ReleaseError(f"{t.where}: {key} must be one of {[a.value for a in Autonomy]}, got {value!r}")
    return Autonomy(value)


def _intake(t: Table) -> Autonomy:
    """The intake level, absent meaning propose; act is refused, as only the maintainer accepts
    or declines an opportunity"""
    value = t.raw.get(INTAKE, Autonomy.PROPOSE.value)
    allowed = [Autonomy.OBSERVE.value, Autonomy.PROPOSE.value]
    if value == Autonomy.ACT.value:
        raise ReleaseError(f"{t.where}: {INTAKE} is observe or propose: only the maintainer accepts an opportunity")
    if not isinstance(value, str) or value not in allowed:
        raise ReleaseError(f"{t.where}: {INTAKE} must be one of {allowed}, got {value!r}")
    return Autonomy(value)
