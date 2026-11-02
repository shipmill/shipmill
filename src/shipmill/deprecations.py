"""The config keys and readings shipmill deprecated and keeps alive (D-63, spec 047): each keeps
loading and warns naming its replacement. `shipmill doctor`'s deprecation warnings come from
this catalogue, so a repo's warning and a report over many repos never disagree. A key shipmill
refuses is another catalogue, `shipmill.refused` (D-64): nothing relies on it, as its config
fails to load"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from shipmill import cli_command
from shipmill.agents import Credit
from shipmill.autonomy import Stage, StageKind
from shipmill.errors import ReleaseError
from shipmill.policy import Policy
from shipmill.upgrades import UpgradeId
from shipmill.version import Version

_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DECIDER = "decider, a merge names who decided it in Co-authored-by"  # [agents] credit's and author's reading
_LAND = Stage(StageKind.LAND)


@dataclass(frozen=True, slots=True)
class DeprecationId:
    """A deprecation's id, lowercase words joined by '-', such as agents-prs"""

    value: str

    def __post_init__(self) -> None:
        if not _ID.match(self.value):
            raise ReleaseError(
                f"a deprecation id is lowercase words joined by '-', such as agents-prs; got {self.value!r}"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Deprecation:
    """A deprecated key or reading: what it is, the shipmill release that deprecated it, its
    replacement, the upgrade that migrates a config off it (None: none does), and doctor's row
    for its warning. warn reads a parsed config: the warning when the config relies on it,
    None when it doesn't"""

    id: DeprecationId
    subject: str  # the key or reading, as the config writes it: [agents] prs
    since: Version
    replacement: str
    upgrade: UpgradeId | None
    row: str  # the doctor row that carries its warning
    warn: Callable[[Policy], str | None]

    def relies(self, policy: Policy) -> bool:
        """Whether the config relies on it: sets the key, or is read the deprecated way"""
        return self.warn(policy) is not None


def _prs(policy: Policy) -> str | None:
    if policy.agents is None or policy.agents.prs is None:
        return None
    land = policy.autonomy.configured(_LAND)
    return (
        f"[agents] prs is deprecated and ignored: [autonomy] land ({land}) decides whether the gate works on"
        " open pull requests, under propose or act, not under observe; delete prs"
    )


def _prompt_land(policy: Policy) -> str | None:
    if not policy.autonomy.is_read_from_prompt(_LAND):
        return None
    level = policy.autonomy.configured(_LAND)
    return (
        f'{_LAND} reads {level} from [agents] prompt ("merge when green" or "land"), which nothing'
        f' checks: add {_LAND} = "{level}" to [autonomy], or run'
        f" `{cli_command()} upgrade --apply agent-autonomy`"
    )


def _roadmap(policy: Policy) -> str | None:
    if policy.roadmap is None:
        return None
    return (
        "[roadmap] is deprecated (D-32) and read by nothing: the work-in-progress limit is [agents] wip;"
        " move wip there and delete [roadmap]"
    )


def _credit(policy: Policy) -> str | None:
    agents = policy.agents
    if agents is None or agents.credit is None:
        return None
    if agents.author is not None:
        return (
            f'{DECIDER} ([agents] author = "{agents.author}", spec 051); [agents] author replaces [agents] credit, '
            "which is ignored: delete credit"
        )
    reading = f"{DECIDER} (spec 049)" if agents.credit is Credit.DECIDER else "off"
    return (
        f'{reading}; [agents] credit is deprecated (spec 051): set [agents] author = "app" instead, the same as '
        'credit = "decider", or, for a repo that wants no trailer, leave both unset'
    )


AGENT_AUTONOMY = UpgradeId("agent-autonomy")
CATALOGUE: tuple[Deprecation, ...] = (
    Deprecation(
        id=DeprecationId("agents-prs"),
        subject="[agents] prs",
        since=Version.parse("0.79.0"),  # #662
        replacement="[autonomy] land",
        upgrade=AGENT_AUTONOMY,
        row="autonomy",
        warn=_prs,
    ),
    Deprecation(
        id=DeprecationId("agents-prompt-land"),
        subject='[agents] prompt read as land = "act" ("merge when green" or "land")',
        since=Version.parse("0.78.0"),  # #661
        replacement="[autonomy] land",
        upgrade=AGENT_AUTONOMY,
        row="autonomy",
        warn=_prompt_land,
    ),
    Deprecation(
        id=DeprecationId("roadmap"),
        subject="[roadmap]",
        since=Version.parse("0.50.0"),  # #377, D-32
        replacement="[agents] wip",
        upgrade=None,
        row="roadmap",
        warn=_roadmap,
    ),
    Deprecation(
        id=DeprecationId("agents-credit"),
        subject="[agents] credit",
        since=Version.parse("0.102.0"),  # #863, spec 051
        replacement="[agents] author",
        upgrade=None,
        row="credit",
        warn=_credit,
    ),
)


def find(deprecation_id: DeprecationId) -> Deprecation:
    for deprecation in CATALOGUE:
        if deprecation.id == deprecation_id:
            return deprecation
    known = ", ".join(str(d.id) for d in CATALOGUE)
    raise ReleaseError(f"unknown deprecation {deprecation_id}; known: {known}")


def relied_on(policy: Policy) -> tuple[Deprecation, ...]:
    """The catalogue's entries the parsed config relies on, in the catalogue's order"""
    return tuple(d for d in CATALOGUE if d.relies(policy))


def warnings(policy: Policy, row: str) -> tuple[str, ...]:
    """The warnings of the entries the config relies on whose doctor row is row"""
    found = (d.warn(policy) for d in CATALOGUE if d.row == row)
    return tuple(w for w in found if w is not None)
