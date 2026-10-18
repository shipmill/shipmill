"""The [roadmap] section of the config, deprecated by D-32: shipmill no longer plans
milestones, so nothing reads it. For one minor release the policy still accepts and validates
it, and doctor warns that the work-in-progress limit is now [agents] wip; the next minor
refuses it and this module goes"""

from dataclasses import dataclass

from shipmill.config import Table

WIP = 5  # the default: issues open at once across the open milestones
CADENCE = 2  # the default: weeks between milestone due dates
_MAX_WIP = 100
_MAX_CADENCE = 26  # half a year


@dataclass(frozen=True, slots=True)
class RoadmapConfig:
    wip: int = WIP  # issues open at once across the open milestones
    cadence: int = CADENCE  # weeks from one milestone's due date to the next

    @classmethod
    def parse(cls, t: Table) -> RoadmapConfig:
        t.allow("wip", "cadence")
        wip = t.integer("wip", default=WIP, low=1, high=_MAX_WIP)
        cadence = t.integer("cadence", default=CADENCE, low=1, high=_MAX_CADENCE)
        assert wip is not None and cadence is not None  # defaults were given
        return cls(wip=wip, cadence=cadence)

    def __str__(self) -> str:
        weeks = "week" if self.cadence == 1 else f"{self.cadence} weeks"
        return f"wip {self.wip} open issues, a milestone every {weeks}"
