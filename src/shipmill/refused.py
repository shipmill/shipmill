"""The config keys shipmill refuses (spec 052, D-64): a refused key stops only the feature it
configured. The config still loads, the key is dropped, and every command that loads the
config says so once on stderr. A key no release of shipmill knew stays an error (D-63)"""

import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shipmill.config import CONFIG_PATH, Table, config_path, read
from shipmill.lanes import Lane

NOTHING = "nothing"  # what an entry whose feature is gone turns off, before its reason


@dataclass(frozen=True, slots=True)
class Refusal:
    """A refused key: its table and key, the spec that removed it, what it turns off (NOTHING,
    then why, when its feature is gone), and the fix the refusal's message ends with"""

    table: str  # as the config writes its header, such as [lanes.stable]
    key: str
    spec: str  # the spec's number, such as 029
    off: str
    fix: str
    lane: Lane | None = None  # the lane it turns off, which the planner leaves unplanned

    @property
    def turns_off(self) -> bool:
        return not (self.off == NOTHING or self.off.startswith(f"{NOTHING}:"))

    @property
    def removed(self) -> str:
        """The line a load raised before spec 052 (S-029-9, S-031-22)"""
        return f"{self.table} {self.key} was removed (spec {self.spec}); {self.fix}"

    @property
    def message(self) -> str:
        """The refusal's message: the removed line, then what it turns off when it turns something off"""
        return f"{self.removed}; {self.off} is off" if self.turns_off else self.removed

    @property
    def named(self) -> str:
        """The key and its spec, as a gate tick names it: [agents] plugin_update (spec 031)"""
        return f"{self.table} {self.key} (spec {self.spec})"

    @property
    def path(self) -> tuple[str, ...]:
        """The table's names from the config's top: [lanes.stable] is ("lanes", "stable")"""
        return tuple(self.table.removeprefix("[").removesuffix("]").split("."))

    @property
    def what(self) -> str:
        """The refusal without its fix, for a row that prints the fix on its own line (S-052-9)"""
        removed = f"{self.table} {self.key} was removed (spec {self.spec})"
        return f"{removed}; {self.off} is off" if self.turns_off else f"{removed}; it turns off {self.off}"

    def record(self) -> dict[str, str]:
        """The refusal in a command's --json object (S-052-11)"""
        return {"key": f"{self.table} {self.key}", "spec": self.spec, "off": self.off, "fix": self.fix}


MIN_SOAK_DAYS = Refusal(
    table="[lanes.stable]",
    key="min_soak_days",
    spec="029",
    off="the stable lane",
    fix="delete it, or run shipmill upgrade --apply stable-every-batch",
    lane=Lane.STABLE,
)
PLUGIN_UPDATE = Refusal(
    table="[agents]",
    key="plugin_update",
    spec="031",
    off=f"{NOTHING}: gate sessions load the installed plugin",
    fix="delete it",
)
CATALOGUE = (MIN_SOAK_DAYS, PLUGIN_UPDATE)


def drop(table: Table, header: str) -> tuple[Table, tuple[Refusal, ...]]:
    """The table without the catalogued keys it sets, whatever their values, and the refusals
    of those keys; header names the table as the config writes it, such as [agents]"""
    found = tuple(r for r in CATALOGUE if r.table == header and r.key in table.raw)
    if not found:
        return table, ()
    keys = {r.key for r in found}
    return Table({k: v for k, v in table.raw.items() if k not in keys}, table.where), found


def found(raw: Mapping[str, Any]) -> tuple[Refusal, ...]:
    """The catalogue's keys a config's raw tables set, in the catalogue's order, read without
    parsing the config: a table that isn't one sets none of them"""
    sets = []
    for refusal in CATALOGUE:
        table: object = raw
        for name in refusal.path:
            table = table.get(name) if isinstance(table, Mapping) else None
        if isinstance(table, Mapping) and refusal.key in table:
            sets.append(refusal)
    return tuple(sets)


def in_checkout(root: Path) -> tuple[Refusal, ...]:
    """The refused keys the checkout's config sets; none without a config file"""
    return found(read(config_path(root))) if (root / CONFIG_PATH).is_file() else ()


def records(refusals: Iterable[Refusal]) -> list[dict[str, str]]:
    """A --json object's "refused" list (S-052-11): empty on a config that sets no refused key"""
    return [r.record() for r in refusals]


_said: set[Refusal] = set()  # the refusals this command printed already


def begin() -> None:
    """A new command starts: the refusals it loads are printed again, once each"""
    _said.clear()


def report(refusals: Iterable[Refusal]) -> None:
    """Print each refusal once per command on stderr, however often the command loads the config"""
    for refusal in refusals:
        if refusal not in _said:
            _said.add(refusal)
            print(f"shipmill: refused: {refusal.message}", file=sys.stderr)
