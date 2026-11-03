"""The config upgrades shipmill can propose (spec 014): features that need an opt-in in a
repo's .github/shipmill.toml, which shipmill never turns on by itself (D-10, D-22).

An upgrade is decided once the config holds its key, whatever the value: `fragments = ""`
written by hand ends the proposal as surely as accepting it. Applying one edits the
config's text, adding its line at the end of its table and keeping every other byte (comments
included), and creates the files it owns; it commits nothing. A top-level `requires` lower than
the upgrade's version is raised to it, in place (spec 031); a higher one stays.

An upgrade may add several keys to one top-level table, with values it reads from the config
(agent-autonomy writes triage, fix, and land as spec 040's legacy reading gives them); setting
any of them decides it, and one that creates its table appends it at the end of a file without
its header line.

An upgrade that retires a deprecated key (spec 029) works the other way round: it applies
while its table sets that key, whatever the value, and is decided once the key is gone, so a
repo that edits it out by hand is done. Its edit takes the key's line out, a trailing comment
with it, and puts its own line in that place unless the table already sets one of the keys
that make it unneeded; one with no key of its own (drop-agents-prs) adds nothing.

An upgrade that retires a deprecated table (spec 047, drop-roadmap) applies while the config
has the table and is decided once it is gone. Its edit takes the table out, from its header to
the next table's header, and may move one of its keys into another top-level table, when that
table exists and doesn't set the key already.

Proposing one opens an issue labelled shipmill-upgrade whose first line is the upgrade's
marker, kept up to date on later runs. Closing that issue while the config lacks the key is a
decline: the upgrade is never proposed again, nor listed as pending. An issue the maintainer
answered "not now" carries shipmill-upgrade-later, which a run takes off only once the upgrade's
version is newer than the one the issue's marker records (S-014-14). An upgrade shipmill no
longer offers is WITHDRAWN: a run closes its open issue, saying why (S-031-21).

Two shipmill releases may propose on one repo (spec 047), so a run never moves an issue
backwards: it leaves as it is an issue whose marker records a version newer than its own, and one
whose marker names an id it doesn't know and hasn't withdrawn (a newer shipmill's upgrade)."""

import copy
import json
import re
import tomllib
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from shipmill import UVX, requires
from shipmill.agent_marker import unmarked
from shipmill.autonomy import Autonomy, AutonomyPolicy, StageKind
from shipmill.config import CONFIG_PATH
from shipmill.errors import ReleaseError
from shipmill.github import UPGRADE_LABEL, UPGRADE_LATER_LABEL, GitHub, Issue
from shipmill.policy import Style
from shipmill.requires import Requires
from shipmill.version import Version

_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_HEADER = re.compile(r"^\s*\[\s*([A-Za-z0-9_-]+(?:\s*\.\s*[A-Za-z0-9_-]+)*)\s*\]\s*(?:#.*)?$")
_ANY_HEADER = re.compile(r"^\s*\[")
_LINE = re.compile(r"[^\n]*\n|[^\n]+\Z")
_MARKER = re.compile(r"^<!-- shipmill-upgrade: (\S+) (\S+) -->\s*$")


@dataclass(frozen=True, slots=True)
class UpgradeId:
    """An upgrade's id, lowercase words joined by '-', such as changelog-fragments"""

    value: str

    def __post_init__(self) -> None:
        if not _ID.match(self.value):
            raise ReleaseError(
                f"an upgrade id is lowercase words joined by '-', such as changelog-fragments; got {self.value!r}"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OwnedFile:
    """A file an upgrade creates, relative to the repo root; render gives its text from the
    config being upgraded"""

    path: Path
    render: Callable[[Mapping[str, Any]], str]

    def __post_init__(self) -> None:
        if self.path.is_absolute() or ".." in self.path.parts:
            raise ReleaseError(f"an upgrade's file is relative to the repo root, got {self.path}")


@dataclass(frozen=True, slots=True, kw_only=True)
class Upgrade:
    id: UpgradeId
    version: Version  # the shipmill release that last changed it
    table: str  # the config table its key goes in, dotted for a nested one: lanes.stable
    # the key it adds; None for an upgrade whose edit only takes a key or a table out
    key: str | None = None
    value: str | bool | int | None = None  # key's value, unless reads or into gives it
    needs_table: bool  # applies only to a config that has the table, such as [agents]
    changes: str  # what it changes, for people
    why: str
    off: str  # how to turn it off
    files: tuple[OwnedFile, ...] = ()
    # a deprecated key of the table the edit takes out: the upgrade applies while the table
    # sets it and is decided once it is gone; None for an upgrade that only adds its key
    removes: str | None = None
    unless: tuple[str, ...] = ()  # with removes: keys of the table, any of which means no line is added
    declined: str = ""  # what closing its issue means besides "never proposed again", for the issue's body
    also: tuple[str, ...] = ()  # more keys it adds to the table after key; setting any of them decides it
    # the values of key and also, read from the config being upgraded; None: value alone
    reads: Callable[[Mapping[str, Any]], tuple[str | bool | int, ...]] | None = None
    when: str | None = None  # another top-level table the config must have for it to apply, such as agents
    creates: bool = False  # a config without the table gets it, at the end of the file
    # the edit takes the whole top-level table out: the upgrade applies while the config has it
    # and is decided once it is gone
    drops: bool = False
    # with drops: the top-level table key moves to, with the value the dropped table gives it,
    # when the config has that table and it doesn't set key
    into: str | None = None
    turns_on: str = ""  # with into: what the moved key turns on, for the issue's body; {value} is its value

    def __post_init__(self) -> None:
        names = (
            *self.table.split("."),
            *([self.key] if self.key is not None else []),
            *self.also,
            *([self.removes] if self.removes else []),
            *self.unless,
        )
        for name in (*names, *(t for t in (self.when, self.into) if t is not None)):
            if not _KEY.match(name):
                raise ReleaseError(f"upgrade {self.id}: {name!r} is not a bare TOML key")
        if (self.also or self.creates) and (self.removes is not None or self.drops or "." in self.table):
            raise ReleaseError(f"upgrade {self.id}: only an upgrade that adds to a top-level table adds more keys")
        retires = self.removes is not None or self.drops
        if self.key is None and (not retires or self.unless or self.reads is not None or self.files):
            raise ReleaseError(f"upgrade {self.id}: only an upgrade that takes a key or a table out adds no key")
        if self.key is not None and self.into is None and self.reads is None and self.value is None:
            raise ReleaseError(f"upgrade {self.id}: {self.key} needs a value")
        if self.drops and (self.removes is not None or "." in self.table or self.files):
            raise ReleaseError(f"upgrade {self.id}: an upgrade that drops a table drops a top-level one, and only that")
        if self.into is not None and (not self.drops or self.key is None or self.into == self.table):
            raise ReleaseError(f"upgrade {self.id}: only an upgrade that drops a table moves its key into another")

    @property
    def keys(self) -> tuple[str, ...]:
        return () if self.key is None else (self.key, *self.also)

    @property
    def target(self) -> str:
        """The table its lines go in: into, for one that moves a key out of the table it drops"""
        return self.into if self.into is not None else self.table

    def settings(self, raw: Mapping[str, Any]) -> dict[str, str | bool | int]:
        """Each key it adds with its value for this config; for one that moves a key, nothing
        unless it moves it"""
        if self.key is None:
            return {}
        if self.into is not None:
            return self._moved(self.key, self.into, raw)
        values = (self.value,) if self.reads is None else self.reads(raw)
        if len(values) != len(self.keys):
            raise ReleaseError(f"upgrade {self.id}: {len(values)} values for the keys {', '.join(self.keys)}")
        found: dict[str, str | bool | int] = {}
        for key, value in zip(self.keys, values, strict=True):
            if value is None:
                raise ReleaseError(f"upgrade {self.id}: {key} needs a value")
            found[key] = value
        return found

    def _moved(self, key: str, into: str, raw: Mapping[str, Any]) -> dict[str, str | bool | int]:
        """key with the value the table sets it to, when the table sets it and the config has an
        into table that doesn't; else nothing"""
        table = self.section(raw)
        target = raw.get(into)
        if table is None or key not in table or target is None:
            return {}
        if not isinstance(target, dict):
            raise ReleaseError(f"{CONFIG_PATH}: {into} must be a table, got {target!r}")
        if key in target:
            return {}
        value = table[key]
        if not isinstance(value, str | bool | int):
            raise ReleaseError(f"{CONFIG_PATH}: [{self.table}] {key} must be a string, a boolean, or an integer")
        return {key: value}

    def unmoved(self, raw: Mapping[str, Any]) -> str:
        """For one that moves a key and won't for this config, why, for the issue's body"""
        table, target = self.section(raw) or {}, raw.get(self.target)
        if self.key not in table:
            return f"`[{self.table}]` sets no `{self.key}`"
        if target is None:
            return f"the config has no `[{self.target}]` table to move `{self.key}` to"
        return f"`[{self.target}]` already sets `{self.key}`, which stays as it is"

    def removed(self, raw: Mapping[str, Any]) -> tuple[str, ...]:
        """The config lines its edit takes out, as this config's values give them; a value the
        config doesn't give reads `…`"""
        table = self.section(raw)
        if self.drops:
            found = table or {}
            return (f"[{self.table}]", *(f"{_bare(k)} = {_shown(self.table, k, v)}" for k, v in found.items()))
        if self.removes is None:
            return ()
        if table is None or self.removes not in table:
            return (f"{self.removes} = …",)
        return (f"{self.removes} = {_shown(self.table, self.removes, table[self.removes])}",)

    def lines(self, raw: Mapping[str, Any]) -> tuple[str, ...]:
        """The config lines it adds to this config, such as fragments = "changelog.d" """
        return tuple(f"{key} = {_toml(value)}" for key, value in self.settings(raw).items())

    @property
    def line(self) -> str:
        """The config lines it adds, one per key, with the values a config with nothing to read gets"""
        return "\n".join(self.lines({}))

    def section(self, raw: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """The config's table the upgrade edits, None when it has none; refuses a value that
        isn't a table on the way"""
        found: Mapping[str, Any] = raw
        parts = self.table.split(".")
        for depth, part in enumerate(parts):
            table = found.get(part)
            if table is None:
                return None
            if not isinstance(table, dict):
                raise ReleaseError(f"{CONFIG_PATH}: {'.'.join(parts[: depth + 1])} must be a table, got {table!r}")
            found = table
        return found

    def applies(self, raw: Mapping[str, Any]) -> bool:
        if self.drops:
            return self.section(raw) is not None
        if self.removes is not None:
            table = self.section(raw)
            return table is not None and self.removes in table
        if self.when is not None and self.when not in raw:
            return False
        return not self.needs_table or self.section(raw) is not None

    def decided(self, raw: Mapping[str, Any]) -> bool:
        """The config holds the key, or any of also, whatever its value: a maintainer's decision
        either way; for an upgrade that removes a key, the table no longer sets it, and for one
        that drops a table, the config no longer has it"""
        if self.removes is not None or self.drops:
            return not self.applies(raw)
        table = self.section(raw)
        return table is not None and any(key in table for key in self.keys)

    def adds(self, raw: Mapping[str, Any]) -> bool:
        """Whether applying it to the config adds its line: always, unless it removes a key from a
        table that already sets its key or one of unless; never for one with no key; for one that
        moves a key, when it moves it"""
        if self.key is None:
            return False
        if self.into is not None:
            return bool(self.settings(raw))
        table = self.section(raw)
        return self.removes is None or table is None or not any(k in table for k in (self.key, *self.unless))

    def record(self, raw: Mapping[str, Any] | None = None) -> dict[str, object]:
        """The upgrade as JSON, its lines with the values for raw, the config being upgraded"""
        lines = self.lines(raw or {})
        return {
            "id": str(self.id),
            "version": str(self.version),
            "table": self.table,
            "into": self.target,  # the table its lines go in
            "line": "\n".join(lines),
            "lines": list(lines),
            "removes": self.removes,
            "drops": self.table if self.drops else None,
            "removed_lines": list(self.removed(raw or {})),
            "files": [p.path.as_posix() for p in self.files],
            "changes": self.changes,
            "why": self.why,
            "off": self.off,
        }


def _toml(value: str | bool | int) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else json.dumps(value)


def _bare(key: str) -> str:
    """A key as TOML writes it: bare when it can be, quoted otherwise"""
    return key if _KEY.match(key) else json.dumps(key)


def _shown(table: str, key: str, value: object) -> str:
    """A config value an upgrade takes out, as TOML writes it; refuses one that isn't a string,
    a boolean, or an integer, which no key an upgrade takes out holds in a config that loads"""
    if not isinstance(value, str | bool | int):
        raise ReleaseError(f"{CONFIG_PATH}: [{table}] {key} must be a string, a boolean, or an integer, got {value!r}")
    return _toml(value)


def _legacy_levels(raw: Mapping[str, Any]) -> tuple[str | bool | int, ...]:
    """triage, fix, and land as spec 040's legacy reading gives them for the config: the
    defaults, and land act when [agents] prompt says "merge when green" or "land" """
    agents = raw.get(AGENTS_TABLE)
    prompt = agents.get("prompt", "") if isinstance(agents, dict) else ""
    if not isinstance(prompt, str):
        raise ReleaseError(f"{CONFIG_PATH}: [{AGENTS_TABLE}] prompt must be a string, got {prompt!r}")
    read = AutonomyPolicy().read_prompt(prompt)
    return (read.triage.value, read.fix.value, read.land.value)


AGENTS_TABLE = "agents"
FRAGMENTS = "changelog.d"
# A fragment's example, in each CHANGELOG style: keep-a-changelog's category heading and entry,
# or dash style's titled entry block
KEEP_A_CHANGELOG_EXAMPLE = "### Fixed\n\n- Worktrees: a branch whose tip was a merged PR's head landed (#244)\n"
DASH_EXAMPLE = "### Worktrees: a branch whose tip was a merged PR's head landed (#244)\n\nIt lands no more.\n"


def fragments_readme(example: str) -> str:
    """The fragments folder's README.md, which keeps the folder in git and is never a fragment"""
    return f"""\
# Changelog fragments

Each pull request adds its changelog entry here as its own file instead of editing
`CHANGELOG.md`, so two pull requests never conflict on it. A stable release writes the
fragments into its section of `CHANGELOG.md` and deletes them; this README stays.

Name a fragment `<issue>-<slug>.md`, such as `{FRAGMENTS}/244-merged-pr-head-landed.md`, and
write what the pull request would have added under Unreleased, in the CHANGELOG's style:

```markdown
{example}```
"""


FRAGMENTS_README = fragments_readme(KEEP_A_CHANGELOG_EXAMPLE)


def fragments_readme_text(style: Style) -> str:
    """The fragments folder's README.md, its example in the CHANGELOG's style (spec 013)"""
    return fragments_readme(KEEP_A_CHANGELOG_EXAMPLE if style is Style.KEEP_A_CHANGELOG else DASH_EXAMPLE)


def _config_readme(raw: Mapping[str, Any]) -> str:
    """The README in the config's [changelog] style, as shipmill init writes it; keep-a-changelog
    for a config that names no style"""
    changelog = raw.get("changelog", {})
    if not isinstance(changelog, dict):
        raise ReleaseError(f"{CONFIG_PATH}: changelog must be a table, got {changelog!r}")
    style = changelog.get("style", Style.KEEP_A_CHANGELOG.value)
    known = [s.value for s in Style]
    if style not in known:
        raise ReleaseError(f"{CONFIG_PATH}: [changelog] style must be one of {', '.join(known)}; got {style!r}")
    return fragments_readme_text(Style(style))


CATALOGUE: tuple[Upgrade, ...] = (
    Upgrade(
        id=UpgradeId("changelog-fragments"),
        version=Version.parse("0.37.0"),
        table="changelog",
        key="fragments",
        value=FRAGMENTS,
        needs_table=True,  # every config releasing has [changelog]; one with releases off may leave it out (#856)
        changes=f"each pull request adds its changelog entry as a file in {FRAGMENTS}/ instead of editing CHANGELOG.md",
        why="pull requests stop conflicting on CHANGELOG.md; a stable release writes the fragments into its section",
        off="delete fragments from [changelog] once no fragment is pending",
        files=(OwnedFile(Path(FRAGMENTS) / "README.md", _config_readme),),
    ),
    Upgrade(
        id=UpgradeId("stable-every-batch"),
        version=Version.parse("0.53.0"),
        table="lanes.stable",
        key="quiet_minutes",
        value=30,
        needs_table=True,
        changes=(
            "stable releases ship every batch of merges whose CI passed, instead of an rc three days old that"
            " nobody ran; a breaking change still waits for the maintainer's hand start; the rc lane stays for"
            " people who pin pre-releases and can be deleted along with promote_from when no milestone gates"
            " the stable lane"
        ),
        why="a time soak checks nothing: in those days nobody runs the rc and shipmill reads no telemetry (spec 029)",
        off="none: shipmill refuses min_soak_days (S-029-9)",
        removes="min_soak_days",
        # a trigger beside milestone would release before the milestone is done
        unless=("schedule", "milestone"),
        declined=("shipmill refuses `min_soak_days`, so a decline means deleting it from `[lanes.stable]` by hand."),
    ),
    Upgrade(
        id=UpgradeId("agent-autonomy"),
        version=Version.parse("0.78.0"),  # the release that adds it (spec 014); 0.77.0 shipped without it
        table="autonomy",
        key=StageKind.TRIAGE.value,
        also=(StageKind.FIX.value, StageKind.LAND.value),
        value=Autonomy.ACT.value,
        reads=_legacy_levels,
        needs_table=False,
        when=AGENTS_TABLE,
        creates=True,
        changes=(
            "[autonomy] sets triage, fix, and land, the stages agent sessions run, to the levels they have today:"
            ' land acts when [agents] prompt says "merge when green" or "land", and proposes otherwise'
        ),
        why=(
            "the levels move from the prompt's words, which nothing checks, to checked keys, and doctor"
            " stops warning (spec 040)"
        ),
        off='set each key to "observe", "propose", or "act" in [autonomy]',
        declined="`land` keeps being read from the prompt, and doctor keeps warning (D-63).",
    ),
    Upgrade(
        id=UpgradeId("drop-agents-prs"),
        version=Version.parse("0.113.0"),  # the release that adds it (spec 047)
        table=AGENTS_TABLE,
        needs_table=True,
        removes="prs",
        changes=(
            "[agents] prs goes, which the gate ignores since spec 040: [autonomy] land decides whether open"
            " pull requests are its work, so no session changes what it does"
        ),
        why="doctor stops warning, and the repo no longer relies on a deprecated key (D-63, spec 047)",
        off="none: nothing reads prs; set it again and doctor warns again",
        declined=(
            "`[agents] prs` stays, doctor keeps warning, and `shipmill deprecations` keeps listing this repo"
            " under `agents-prs` (D-63)."
        ),
    ),
    Upgrade(
        id=UpgradeId("drop-roadmap"),
        version=Version.parse("0.113.0"),  # the release that adds it (spec 047)
        table="roadmap",
        needs_table=True,
        drops=True,
        key="wip",
        into=AGENTS_TABLE,
        turns_on="triage keeps at most {value} issues in progress at once",
        changes=(
            "the [roadmap] table goes, which nothing reads since D-32; a wip it sets moves to [agents], where"
            " triage reads it, when [agents] sets none"
        ),
        why="doctor stops warning, and the repo no longer relies on a deprecated table (D-63, spec 047)",
        off="delete wip from [agents] to turn the limit off; nothing reads [roadmap]",
        declined=(
            "`[roadmap]` stays, read by nothing, doctor keeps warning, and `shipmill deprecations` keeps listing"
            " this repo under `roadmap` (D-63)."
        ),
    ),
)


# Upgrades shipmill no longer offers, each with why: a run closes the open issue that proposes
# one, since its id names nothing `upgrade --apply` knows
WITHDRAWN: Mapping[UpgradeId, str] = {
    # S-031-21: withdrawn; the key it added is refused since (S-031-22)
    UpgradeId("plugin-update"): (
        "gate sessions load the installed plugin and report its lag (spec 031), so `[agents] plugin_update`"
        " was removed and the gate changes no install"
    ),
}


def find(upgrade_id: UpgradeId) -> Upgrade:
    for upgrade in CATALOGUE:
        if upgrade.id == upgrade_id:
            return upgrade
    known = ", ".join(str(u.id) for u in CATALOGUE)
    raise ReleaseError(f"unknown upgrade {upgrade_id}; known: {known}")


def pending(raw: Mapping[str, Any]) -> tuple[Upgrade, ...]:
    """The upgrades that apply to the config and that it hasn't decided"""
    return tuple(u for u in CATALOGUE if u.applies(raw) and not u.decided(raw))


# -- proposal issues -------------------------------------------------------------------------


def marker(upgrade: Upgrade) -> str:
    """The first line of the upgrade's issue: its id, and the release that last changed it"""
    return f"<!-- shipmill-upgrade: {upgrade.id} {upgrade.version} -->"


def marked(issue: Issue) -> UpgradeId | None:
    """The upgrade an issue proposes, from the marker on its body's first line; None for an
    issue without one, or whose marker names no well-formed id"""
    first = issue.body.replace("\r\n", "\n").split("\n", 1)[0]
    found = _MARKER.match(first)
    return UpgradeId(found[1]) if found and _ID.match(found[1]) else None


def asked(issue: Issue) -> Version | None:
    """The upgrade's version the issue was last asked about, which its marker records; None for
    a marker without a version shipmill reads"""
    first = issue.body.replace("\r\n", "\n").split("\n", 1)[0]
    found = _MARKER.match(first)
    if found is None:
        return None
    try:
        return Version.parse(found[2])
    except ReleaseError:
        return None


def renewed(upgrade: Upgrade, issue: Issue) -> bool:
    """Whether the issue's "not now" lapses: it carries shipmill-upgrade-later, and the upgrade
    is newer, in version order, than the version its marker records. An unreadable version
    keeps the label: the question waits for the next release that changes the upgrade"""
    if UPGRADE_LATER_LABEL not in issue.labels:
        return False
    version = asked(issue)
    return version is not None and upgrade.version > version


def ahead(upgrade: Upgrade, issue: Issue) -> bool:
    """Whether a newer shipmill wrote the issue: its marker records a version newer, in version
    order, than this catalogue's version of the upgrade (spec 047). An unreadable version is not
    newer: the run rewrites the issue with its own marker, as S-014-14 has it"""
    version = asked(issue)
    return version is not None and version > upgrade.version


@dataclass(frozen=True, slots=True)
class Offer:
    """A pending upgrade with no declined proposal, and its open issue when it has one"""

    upgrade: Upgrade
    issue: int | None


def _issues(issues: Sequence[Issue], upgrade: Upgrade) -> tuple[list[Issue], list[Issue]]:
    """The upgrade's open issues and its closed ones, each by number"""
    mine = sorted((i for i in issues if marked(i) == upgrade.id), key=lambda i: i.number)
    return [i for i in mine if not i.closed], [i for i in mine if i.closed]


def offers(raw: Mapping[str, Any], issues: Sequence[Issue]) -> tuple[Offer, ...]:
    """The pending upgrades, less those declined: an upgrade whose issue was closed, and has
    no open one, while the config lacks its key. issues are the shipmill-upgrade issues, open
    and closed (GitHub.labelled_issues)"""
    found = []
    for upgrade in pending(raw):
        opened, closed = _issues(issues, upgrade)
        if opened:
            found.append(Offer(upgrade, opened[0].number))
        elif not closed:
            found.append(Offer(upgrade, None))
    return tuple(found)


def title(upgrade: Upgrade) -> str:
    return f"shipmill upgrade: turn on {upgrade.id}"


def _takes_out(upgrade: Upgrade) -> bool:
    """Whether the issue's body shows the edit as the lines it takes out: one with no key of its
    own, or one that drops a table"""
    return upgrade.key is None or upgrade.drops


def _edit_text(upgrade: Upgrade, raw: Mapping[str, Any]) -> str:
    """What the edit does to the config, for the issue's body, ending where the toml block starts"""
    config = CONFIG_PATH.as_posix()
    if upgrade.drops:
        dropped = (
            f"It deletes the `[{upgrade.table}]` table from `{config}` (its header, its keys, and its lines up to"
            " the next table's header) and keeps every other line"
        )
        moved = upgrade.settings(raw)
        if not moved:
            return f"{dropped}. It adds no line: {upgrade.unmoved(raw)}."
        ((key, value),) = moved.items()
        limit = upgrade.turns_on.format(value=value)
        return (
            f"{dropped}. It moves `{key} = {_toml(value)}` into `[{upgrade.target}]`, which turns it on, since"
            f" nothing reads `[{upgrade.table}]`'s `{key}` today: {limit}."
        )
    if upgrade.key is None:
        assert upgrade.removes is not None  # __post_init__: a key-less upgrade takes a key or a table out
        return (
            f"It deletes the `{upgrade.removes}` line from `[{upgrade.table}]` in `{config}`, a trailing comment"
            " with it, keeps every other line, and adds none."
        )
    if upgrade.removes is None:
        created = "".join(f" and creates `{f.path.as_posix()}`" for f in upgrade.files)
        what = "these lines" if upgrade.also else "this line"
        table = " (the table too, when the file has none)" if upgrade.creates else ""
        return f"It adds {what} under `[{upgrade.table}]`{table} in `{config}`{created}:"
    keys = ", ".join(f"`{k}`" for k in (upgrade.key, *upgrade.unless))
    return (
        f"It deletes the `{upgrade.removes}` line from `[{upgrade.table}]` in `{config}`, keeps every other line,"
        f" and, when the table sets none of {keys}, adds this one in its place:"
    )


def _decided_text(upgrade: Upgrade) -> str:
    """When the config has decided the upgrade, for the issue's body"""
    if upgrade.drops:
        return f"`{CONFIG_PATH.as_posix()}` has no `[{upgrade.table}]` table"
    if upgrade.removes is None:
        if upgrade.also:
            keys = ", ".join(f"`{key}`" for key in upgrade.keys)
            return f"`[{upgrade.table}]` sets any of {keys}, to any value"
        return f"`[{upgrade.table}]` sets `{upgrade.key}`, to any value"
    return f"`[{upgrade.table}]` no longer sets `{upgrade.removes}`"


def _diff(upgrade: Upgrade, raw: Mapping[str, Any]) -> list[str]:
    """The edit as a diff block, for the issue's body: each line it takes out, and each it adds
    under its table's header"""
    taken = [f"-{line}" for line in upgrade.removed(raw)]
    shown = taken if upgrade.drops else [f" [{upgrade.table}]", *taken]
    added = upgrade.lines(raw) if upgrade.adds(raw) else ()
    if added:
        shown += [f" [{upgrade.target}]", *(f"+{line}" for line in added)]
    return ["```diff", *shown, "```"]


def body(upgrade: Upgrade, raw: Mapping[str, Any] | None = None) -> str:
    """The issue's body; its lines carry the values for raw, the config being upgraded"""
    lines = [
        marker(upgrade),
        f"shipmill {upgrade.version} offers **{upgrade.id}**, which needs an opt-in in `{CONFIG_PATH.as_posix()}`."
        " shipmill never turns it on by itself.",
        "",
        f"- What it changes: {upgrade.changes}",
        f"- Why: {upgrade.why}",
        f"- To turn it off later: {upgrade.off}",
        "",
        _edit_text(upgrade, raw or {}),
        "",
        *(
            _diff(upgrade, raw or {})
            if _takes_out(upgrade)
            else ["```toml", f"[{upgrade.table}]", *upgrade.lines(raw or {}), "```"]
        ),
        "",
        "### Accept",
        "",
        "- Answer the question shipmill's agent asks on this issue, or",
        "- Make the change yourself and open a pull request with it:",
        "",
        "```",
        f"{UVX} upgrade --apply {upgrade.id}",
        "```",
        "",
        "### Decline",
        "",
        f"Say so here, or close this issue: shipmill won't propose {upgrade.id} again."
        + (f" {upgrade.declined}" if upgrade.declined else ""),
        "",
        f"Each release shipmill cuts updates this issue while the upgrade is pending, and closes it once"
        f" {_decided_text(upgrade)}.",
    ]
    return "\n".join(lines) + "\n"


class Outcome(StrEnum):
    OPENED = "opened"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    RENEWED = "renewed"  # updated, and shipmill-upgrade-later taken off: the question is asked again
    CLOSED = "closed"  # the config holds the key: closed as completed
    WITHDRAWN = "withdrawn"  # shipmill no longer offers the upgrade: closed, naming why


@dataclass(frozen=True, slots=True)
class Proposed:
    id: UpgradeId
    issue: int
    outcome: Outcome

    def record(self) -> dict[str, object]:
        return {"id": str(self.id), "issue": self.issue, "outcome": str(self.outcome)}


@dataclass(frozen=True, slots=True)
class Proposals:
    """What the gate's sweep's proposal did (spec 047), as sweep.json's upgrades holds it: each
    issue it wrote or left, or the first line of the error that stopped it"""

    done: tuple[Proposed, ...] = ()
    error: str | None = None

    def record(self) -> dict[str, object]:
        if self.error is not None:
            return {"error": self.error}
        return {"proposed": [d.record() for d in self.done]}

    @classmethod
    def of(cls, data: object) -> Proposals:
        """sweep.json's upgrades; anything but one of the two shapes raises ValueError"""
        if not isinstance(data, dict) or set(data) not in ({"error"}, {"proposed"}):
            raise ValueError(f"upgrades needs exactly error or proposed, got {data!r}")
        if "error" in data:
            if not isinstance(data["error"], str) or not data["error"]:
                raise ValueError(f"upgrades' error must be a non-empty string: {data!r}")
            return cls(error=data["error"])
        if not isinstance(data["proposed"], list):
            raise ValueError(f"upgrades' proposed must be a list: {data!r}")
        done = []
        for entry in data["proposed"]:
            if not isinstance(entry, dict) or set(entry) != {"id", "issue", "outcome"}:
                raise ValueError(f"a proposal needs exactly id, issue, and outcome, got {entry!r}")
            number, outcome = entry["issue"], entry["outcome"]
            if not isinstance(number, int) or isinstance(number, bool) or number < 1:
                raise ValueError(f"a proposal's issue must be a positive number: {entry!r}")
            if not isinstance(entry["id"], str) or outcome not in {o.value for o in Outcome}:
                raise ValueError(f"a proposal needs a string id and a known outcome: {entry!r}")
            try:
                done.append(Proposed(UpgradeId(entry["id"]), number, Outcome(outcome)))
            except ReleaseError as exc:
                raise ValueError(str(exc)) from None
        return cls(tuple(done))

    def line(self) -> str:
        """The swept tick's decision line's part: `upgrades: 1 opened`, `upgrades: none`, or
        `upgrades failed: <first line>`"""
        if self.error is not None:
            return f"upgrades failed: {self.error}"
        counts = {o: sum(1 for d in self.done if d.outcome is o) for o in Outcome}
        shown = ", ".join(f"{n} {o}" for o, n in counts.items() if n)
        return f"upgrades: {shown or 'none'}"


def propose(raw: Mapping[str, Any], level: Autonomy, github: GitHub, fix: str) -> list[Proposed]:
    """Close as completed the open issue of each upgrade the config decided, and the open issue
    of each WITHDRAWN upgrade, naming why; then, unless the
    upgrade autonomy is observe, open or update one issue per offer, taking shipmill-upgrade-later
    off an issue whose upgrade is newer than the version its marker records (before the update
    rewrites the marker). A run never moves an issue backwards (spec 047): it rewrites no issue
    whose marker records a newer version than its catalogue's, reporting it unchanged, and leaves
    out of the result, open and as it is, an issue whose id neither CATALOGUE nor WITHDRAWN knows.
    A failure names the upgrade, and fix says how to grant `issues: write` when GitHub refused it"""
    waiting = pending(raw)  # first: a malformed config fails before GitHub is asked
    try:
        issues = github.labelled_issues(UPGRADE_LABEL)
    except ReleaseError as exc:
        named = ", ".join(str(u.id) for u in waiting) or "no pending upgrade"
        raise ReleaseError(f"can't read the {UPGRADE_LABEL} issues ({named}): {exc}") from exc
    done: list[Proposed] = []
    for upgrade in CATALOGUE:
        if not upgrade.decided(raw):
            continue
        for issue in _issues(issues, upgrade)[0]:
            settled = "no longer sets" if upgrade.removes is not None else "sets"
            table = upgrade.section(raw) or {}
            keys = [upgrade.removes] if upgrade.removes is not None else [k for k in upgrade.keys if k in table]
            named = ", ".join(f"`{k}`" for k in keys)  # the keys that decided it, not only the first
            where = f"`[{upgrade.table}]` in `{CONFIG_PATH.as_posix()}` {settled} {named}"
            if upgrade.drops:
                where = f"`{CONFIG_PATH.as_posix()}` has no `[{upgrade.table}]` table"
            text = f"{where}: {upgrade.id} is decided, so this issue is done."
            with _named(upgrade.id, fix):
                github.close_issue(issue.number, text)
            done.append(Proposed(upgrade.id, issue.number, Outcome.CLOSED))
    for issue in sorted(issues, key=lambda i: i.number):  # S-031-21: an id no catalogue entry has any more
        name = marked(issue)
        if issue.closed or name is None or name not in WITHDRAWN:
            continue
        with _named(name, fix):
            github.close_issue(issue.number, f"shipmill no longer offers {name}: {WITHDRAWN[name]}.")
        done.append(Proposed(name, issue.number, Outcome.WITHDRAWN))
    if level is Autonomy.OBSERVE:
        return done
    for offer in offers(raw, issues):
        upgrade = offer.upgrade
        wanted_title, wanted = title(upgrade), body(upgrade, raw)
        with _named(upgrade.id, fix):
            if offer.issue is None:
                number = github.create_issue(wanted_title, wanted, (UPGRADE_LABEL,))
                done.append(Proposed(upgrade.id, number, Outcome.OPENED))
                continue
            issue = next(i for i in issues if i.number == offer.issue)
            if ahead(upgrade, issue):  # S-047-7: a newer shipmill wrote it; never move it backwards
                done.append(Proposed(upgrade.id, issue.number, Outcome.UNCHANGED))
                continue
            renew = renewed(upgrade, issue)
            if renew:  # first: a failed update after it leaves the old marker to compare again
                github.remove_label(issue.number, UPGRADE_LATER_LABEL)
            stored = unmarked(issue.body.replace("\r\n", "\n")).strip()  # less GhCli's marker (spec 050)
            same = (issue.title, stored) == (wanted_title, wanted.strip())
            if not same:
                github.update_issue(issue.number, wanted_title, wanted)
            outcome = Outcome.RENEWED if renew else Outcome.UNCHANGED if same else Outcome.UPDATED
            done.append(Proposed(upgrade.id, issue.number, outcome))
    return done


@contextmanager
def _named(upgrade: UpgradeId, fix: str) -> Iterator[None]:
    """Re-raise a GitHub failure naming the upgrade, with the fix for a refused write"""
    try:
        yield
    except ReleaseError as exc:
        raise ReleaseError(f"upgrade {upgrade}: {exc}; if GitHub refused it (403): {fix}") from exc


@dataclass(frozen=True, slots=True)
class Applied:
    upgrade: Upgrade
    created: tuple[Path, ...]  # relative to the repo root
    kept: tuple[Path, ...]  # owned files that already existed, left as they were
    added: bool = True  # whether the edit added the upgrade's line; an upgrade that removes a key may not
    lines: tuple[str, ...] = ()  # the lines the edit added, or would have added, with this config's values
    removed: tuple[str, ...] = ()  # the config's lines the edit took out, as the file wrote them, less line endings


def apply(root: Path, upgrade: Upgrade) -> Applied:
    """Add the upgrade's line to the config, or for one that removes a key take that key's line
    out (putting its line in that place when the table needs it), or for one that drops a table
    take the table out (moving its key when the upgrade does), and create its files; refuse
    one that doesn't apply or is decided, and a config whose table this edit can't find"""
    path = root / CONFIG_PATH
    if not path.is_file():
        raise ReleaseError(f"no {CONFIG_PATH} in {root}")
    text = path.read_bytes().decode("utf-8")
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ReleaseError(f"{path}: {exc}") from None
    bound = requires.check(raw)
    if not upgrade.applies(raw):
        if upgrade.drops:
            raise ReleaseError(f"upgrade {upgrade.id} doesn't apply: {CONFIG_PATH} has no [{upgrade.table}] table")
        if upgrade.removes is not None:
            raise ReleaseError(
                f"upgrade {upgrade.id} doesn't apply: [{upgrade.table}] in {CONFIG_PATH} sets no {upgrade.removes}"
            )
        missing = upgrade.when if upgrade.when is not None and upgrade.when not in raw else upgrade.table
        raise ReleaseError(f"upgrade {upgrade.id} doesn't apply: {CONFIG_PATH} has no [{missing}] section")
    if upgrade.decided(raw):
        keys = "/".join(upgrade.keys)
        raise ReleaseError(f"upgrade {upgrade.id} is already decided: [{upgrade.table}] {keys} is set in {CONFIG_PATH}")
    if upgrade.section(raw) is None and not upgrade.creates:
        raise ReleaseError(
            f"upgrade {upgrade.id}: {CONFIG_PATH} has no [{upgrade.table}] table to add {upgrade.key} to"
        )
    adds = upgrade.adds(raw)
    lines = upgrade.lines(raw)
    expected = copy.deepcopy(dict(raw))
    if upgrade.creates:
        expected.setdefault(upgrade.table, {})
    taken: tuple[str, ...] = ()
    if upgrade.drops:
        refused = ReleaseError(
            f"upgrade {upgrade.id}: can't take [{upgrade.table}] out of {CONFIG_PATH}; edit it by hand"
        )
        edited, taken = _drop(text, upgrade)
        del expected[upgrade.table]
        if adds:
            moved = append_to_table(edited, upgrade.target, lines)
            if moved is None:  # no one header line for the table the key moves to
                raise refused
            edited = moved
    elif upgrade.removes is None:
        edited = _insert(text, upgrade, lines)
        shown = "; ".join(lines)
        refused = ReleaseError(f"upgrade {upgrade.id}: can't add {shown} to {CONFIG_PATH}; add it by hand")
    else:
        edited, taken = _replace(text, upgrade, upgrade.removes, adds)
        del _table(expected, upgrade.table)[upgrade.removes]
        refused = ReleaseError(
            f"upgrade {upgrade.id}: can't take {upgrade.removes} out of [{upgrade.table}] in {CONFIG_PATH};"
            " edit it by hand"
        )
    if adds:
        _table(expected, upgrade.target).update(upgrade.settings(raw))
    needed = Requires.at(upgrade.version)
    if bound is not None and bound.floor < needed.floor:  # a higher or equal bound stays (S-031-7)
        edited = _set_requires(edited, needed, upgrade)
        expected[requires.KEY] = str(needed)
    try:
        meant = tomllib.loads(edited)
    except tomllib.TOMLDecodeError:
        raise refused from None
    if meant != expected:  # the text edit must mean exactly the one key more, or the one less
        raise refused
    created: list[Path] = []
    kept: list[Path] = []
    for owned in upgrade.files:
        target = root / owned.path
        if target.exists():
            kept.append(owned.path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(owned.render(raw), encoding="utf-8")
        created.append(owned.path)
    path.write_bytes(edited.encode("utf-8"))
    return Applied(upgrade, tuple(created), tuple(kept), adds, lines, taken)


def _table(config: dict[str, Any], dotted: str) -> dict[str, Any]:
    """The parsed config's table at the dotted name, which the caller knows it has"""
    found = config
    for part in dotted.split("."):
        found = found[part]
    return found


_REQUIRES_LINE = re.compile(rf"^(\s*{requires.KEY}\s*=\s*)(\"[^\"\n]*\"|'[^'\n]*')")


def _set_requires(text: str, bound: Requires, upgrade: Upgrade) -> str:
    """The text with its top-level requires line set to bound, its comment and line ending kept"""
    lines = _LINE.findall(text)
    outside = _outside_strings(lines)
    first = next((i for i, line in enumerate(lines) if outside[i] and _ANY_HEADER.match(line)), len(lines))
    found = [i for i in range(first) if outside[i] and _REQUIRES_LINE.match(lines[i])]
    if len(found) != 1:
        raise ReleaseError(
            f"upgrade {upgrade.id}: can't raise {requires.KEY} in {CONFIG_PATH} to {bound}; edit it by hand"
        )
    at = found[0]
    lines[at] = _REQUIRES_LINE.sub(lambda m: m[1] + json.dumps(str(bound)), lines[at], count=1)
    return "".join(lines)


def _headers(text: str, upgrade: Upgrade) -> list[int]:
    """The indexes of the lines that open the upgrade's table, [table], outside strings"""
    lines = _LINE.findall(text)  # not splitlines: it also breaks on U+2028 and the like, TOML only on \n
    outside = _outside_strings(lines)
    return [
        i
        for i, line in enumerate(lines)
        if outside[i] and (m := _HEADER.match(line)) and re.sub(r"\s", "", m[1]) == upgrade.table
    ]


def _bounds(text: str, table: str) -> tuple[list[str], list[bool], int, int] | None:
    """The text's lines, whether each starts outside a multi-line string, and the bounds of the
    table: its header line and the next header's (or the line count); None without exactly one
    header line for it"""
    lines = _LINE.findall(text)  # not splitlines: it also breaks on U+2028 and the like, TOML only on \n
    outside = _outside_strings(lines)
    headers = [i for i, line in enumerate(lines) if outside[i] and _ANY_HEADER.match(line)]
    found = [i for i in headers if (m := _HEADER.match(lines[i])) and re.sub(r"\s", "", m[1]) == table]
    if len(found) != 1:
        return None
    start = found[0]
    return lines, outside, start, next((i for i in headers if i > start), len(lines))


def _body(text: str, upgrade: Upgrade, key: str) -> tuple[list[str], list[bool], int, int]:
    """_bounds of the upgrade's table, which must have one header line"""
    bounds = _bounds(text, upgrade.table)
    if bounds is None:
        raise ReleaseError(f"upgrade {upgrade.id}: no [{upgrade.table}] header line in {CONFIG_PATH} to edit {key} in")
    return bounds


def _replace(text: str, upgrade: Upgrade, removes: str, adds: bool) -> tuple[str, tuple[str, ...]]:
    """The text without the line that sets removes in the upgrade's table, a trailing comment
    with it, and with adds the upgrade's line in its place, in that line's ending; and the line
    taken out, less its ending"""
    lines, outside, start, end = _body(text, upgrade, removes)
    key = re.compile(rf"^\s*{re.escape(removes)}\s*=")
    found = [i for i in range(start + 1, end) if outside[i] and key.match(lines[i])]
    if len(found) != 1:
        raise ReleaseError(
            f"upgrade {upgrade.id}: no {removes} line under [{upgrade.table}] in {CONFIG_PATH} to take out"
        )
    at = found[0]
    taken = lines[at].rstrip("\r\n")
    ending = lines[at][len(taken) :]
    lines[at : at + 1] = [upgrade.line + ending] if adds else []
    return "".join(lines), (taken,)


def _drop(text: str, upgrade: Upgrade) -> tuple[str, tuple[str, ...]]:
    """The text without the upgrade's table: its header line and every line up to the next
    table's header (or the end of the file); and the lines taken out, less their endings"""
    bounds = _bounds(text, upgrade.table)
    if bounds is None:
        raise ReleaseError(f"upgrade {upgrade.id}: no [{upgrade.table}] header line in {CONFIG_PATH} to take out")
    lines, _, start, end = bounds
    taken = tuple(line.rstrip("\r\n") for line in lines[start:end])
    del lines[start:end]
    return "".join(lines), taken


def _insert(text: str, upgrade: Upgrade, added: Sequence[str]) -> str:
    """The text with the added lines after the last line of the upgrade's table's body (the
    header when the body is empty), in the file's own line ending. An upgrade that creates its
    table, in a file without its header line, gets the header and the lines at the end"""
    newline = "\r\n" if "\r\n" in text else "\n"
    if upgrade.creates and not _headers(text, upgrade):
        ended = text if not text or text.endswith("\n") else text + newline
        gap = newline if ended else ""
        return ended + gap + f"[{upgrade.table}]{newline}" + "".join(line + newline for line in added)
    assert upgrade.key is not None  # __post_init__: an upgrade that only adds has a key
    _body(text, upgrade, upgrade.key)  # refuses a table without one header line, in the upgrade's words
    edited = append_to_table(text, upgrade.table, added)
    assert edited is not None  # _body found the header
    return edited


def append_to_table(text: str, table: str, added: Sequence[str]) -> str | None:
    """The text with the added lines after the last line of the table's body (the header when
    the body is empty), in the file's own line ending; None without exactly one header line for
    the table (a dotted name for a nested one: autonomy.deploy). The caller checks the result
    parses to what it meant"""
    bounds = _bounds(text, table)
    if bounds is None:
        return None
    newline = "\r\n" if "\r\n" in text else "\n"
    lines, outside, start, end = bounds
    last = start
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if not outside[i] or (stripped and not stripped.startswith("#")):
            last = i
    if not lines[last].endswith("\n"):
        lines[last] += newline
    lines[last + 1 : last + 1] = [line + newline for line in added]
    return "".join(lines)


def _outside_strings(lines: list[str]) -> list[bool]:
    """Per line, whether it starts outside a multi-line string"""
    starts: list[bool] = []
    state: str | None = None
    for line in lines:
        starts.append(state is None)
        state = _scan(line, state)
    return starts


def _scan(line: str, state: str | None) -> str | None:
    """The multi-line string (its delimiter) the line ends inside, given the one it starts in"""
    i = 0
    while i < len(line):
        if state is not None:
            if state == '"""' and line[i] == "\\":
                i += 2
            elif line.startswith(state, i):
                state, i = None, i + 3
            else:
                i += 1
            continue
        char = line[i]
        if char == "#":
            break
        if line.startswith(('"""', "'''"), i):
            state, i = line[i : i + 3], i + 3
        elif char == '"':
            i += 1
            while i < len(line) and line[i] != '"':
                i += 2 if line[i] == "\\" else 1
            i += 1
        elif char == "'":
            close = line.find("'", i + 1)
            i = len(line) if close < 0 else close + 1
        else:
            i += 1
    return state
