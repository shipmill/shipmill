"""The config upgrades shipmill can propose (spec 014): features that need an opt-in in a
repo's .github/shipmill.toml, which shipmill never turns on by itself (D-10, D-22).

An upgrade is decided once the config holds its key, whatever the value: `plugin_update =
false` written by hand ends the proposal as surely as accepting it. Applying one edits the
config's text, adding its line at the end of its table and keeping every other byte (comments
included), and creates the files it owns; it commits nothing.

An upgrade that retires a deprecated key (spec 029) works the other way round: it applies
while its table sets that key, whatever the value, and is decided once the key is gone, so a
repo that edits it out by hand is done. Its edit takes the key's line out, a trailing comment
with it, and puts its own line in that place unless the table already sets one of the keys
that make it unneeded.

Proposing one opens an issue labelled shipmill-upgrade whose first line is the upgrade's
marker, kept up to date on later runs. Closing that issue while the config lacks the key is a
decline: the upgrade is never proposed again, nor listed as pending. An issue the maintainer
answered "not now" carries shipmill-upgrade-later, which a run takes off only once the upgrade's
version is newer than the one the issue's marker records (S-014-14)."""

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

from shipmill import UVX
from shipmill.autonomy import Autonomy
from shipmill.config import CONFIG_PATH
from shipmill.errors import ReleaseError
from shipmill.github import UPGRADE_LABEL, UPGRADE_LATER_LABEL, GitHub, Issue
from shipmill.policy import Style
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
                f"an upgrade id is lowercase words joined by '-', such as plugin-update; got {self.value!r}"
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


@dataclass(frozen=True, slots=True)
class Upgrade:
    id: UpgradeId
    version: Version  # the shipmill release that last changed it
    table: str  # the config table its key goes in, dotted for a nested one: lanes.stable
    key: str
    value: str | bool | int
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

    def __post_init__(self) -> None:
        for name in (*self.table.split("."), self.key, *([self.removes] if self.removes else []), *self.unless):
            if not _KEY.match(name):
                raise ReleaseError(f"upgrade {self.id}: {name!r} is not a bare TOML key")

    @property
    def line(self) -> str:
        """The config line it adds, such as fragments = "changelog.d" """
        value = ("true" if self.value else "false") if isinstance(self.value, bool) else json.dumps(self.value)
        return f"{self.key} = {value}"

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
        if self.removes is not None:
            table = self.section(raw)
            return table is not None and self.removes in table
        return not self.needs_table or self.section(raw) is not None

    def decided(self, raw: Mapping[str, Any]) -> bool:
        """The config holds the key, whatever its value: a maintainer's decision either way;
        for an upgrade that removes a key, the table no longer sets it"""
        if self.removes is not None:
            return not self.applies(raw)
        table = self.section(raw)
        return table is not None and self.key in table

    def adds(self, raw: Mapping[str, Any]) -> bool:
        """Whether applying it to the config adds its line: always, unless it removes a key from a
        table that already sets its key or one of unless"""
        table = self.section(raw)
        return self.removes is None or table is None or not any(k in table for k in (self.key, *self.unless))

    def record(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "version": str(self.version),
            "table": self.table,
            "line": self.line,
            "removes": self.removes,
            "files": [p.path.as_posix() for p in self.files],
            "changes": self.changes,
            "why": self.why,
            "off": self.off,
        }


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
        needs_table=False,
        changes=f"each pull request adds its changelog entry as a file in {FRAGMENTS}/ instead of editing CHANGELOG.md",
        why="pull requests stop conflicting on CHANGELOG.md; a stable release writes the fragments into its section",
        off="delete fragments from [changelog] once no fragment is pending",
        files=(OwnedFile(Path(FRAGMENTS) / "README.md", _config_readme),),
    ),
    Upgrade(
        id=UpgradeId("plugin-update"),
        version=Version.parse("0.37.0"),
        table="agents",
        key="plugin_update",
        value=True,
        needs_table=True,
        changes="shipmill gate updates the shipmill plugin keyed on its checkout, at most once a day (D-23)",
        why="the gate's sessions run the latest skills instead of the ones installed when it was set up",
        off="set plugin_update = false in [agents]",
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
)


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


def _edit_text(upgrade: Upgrade) -> str:
    """What the edit does to the config, for the issue's body, ending where the toml block starts"""
    config = CONFIG_PATH.as_posix()
    if upgrade.removes is None:
        created = "".join(f" and creates `{f.path.as_posix()}`" for f in upgrade.files)
        return f"It adds this line under `[{upgrade.table}]` in `{config}`{created}:"
    keys = ", ".join(f"`{k}`" for k in (upgrade.key, *upgrade.unless))
    return (
        f"It deletes the `{upgrade.removes}` line from `[{upgrade.table}]` in `{config}`, keeps every other line,"
        f" and, when the table sets none of {keys}, adds this one in its place:"
    )


def _decided_text(upgrade: Upgrade) -> str:
    """When the config has decided the upgrade, for the issue's body"""
    if upgrade.removes is None:
        return f"`[{upgrade.table}]` sets `{upgrade.key}`, to any value"
    return f"`[{upgrade.table}]` no longer sets `{upgrade.removes}`"


def body(upgrade: Upgrade) -> str:
    lines = [
        marker(upgrade),
        f"shipmill {upgrade.version} offers **{upgrade.id}**, which needs an opt-in in `{CONFIG_PATH.as_posix()}`."
        " shipmill never turns it on by itself.",
        "",
        f"- What it changes: {upgrade.changes}",
        f"- Why: {upgrade.why}",
        f"- To turn it off later: {upgrade.off}",
        "",
        _edit_text(upgrade),
        "",
        "```toml",
        f"[{upgrade.table}]",
        upgrade.line,
        "```",
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


@dataclass(frozen=True, slots=True)
class Proposed:
    upgrade: Upgrade
    issue: int
    outcome: Outcome


def propose(raw: Mapping[str, Any], level: Autonomy, github: GitHub, fix: str) -> list[Proposed]:
    """Close as completed the open issue of each upgrade the config decided; then, unless the
    upgrade autonomy is observe, open or update one issue per offer, taking shipmill-upgrade-later
    off an issue whose upgrade is newer than the version its marker records (before the update
    rewrites the marker). A failure names the upgrade, and fix says how to grant `issues: write`
    when GitHub refused it"""
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
            text = (
                f"`[{upgrade.table}]` in `{CONFIG_PATH.as_posix()}` {settled} `{upgrade.removes or upgrade.key}`:"
                f" {upgrade.id} is decided, so this issue is done."
            )
            with _named(upgrade, fix):
                github.close_issue(issue.number, text)
            done.append(Proposed(upgrade, issue.number, Outcome.CLOSED))
    if level is Autonomy.OBSERVE:
        return done
    for offer in offers(raw, issues):
        upgrade = offer.upgrade
        wanted_title, wanted = title(upgrade), body(upgrade)
        with _named(upgrade, fix):
            if offer.issue is None:
                number = github.create_issue(wanted_title, wanted, (UPGRADE_LABEL,))
                done.append(Proposed(upgrade, number, Outcome.OPENED))
                continue
            issue = next(i for i in issues if i.number == offer.issue)
            renew = renewed(upgrade, issue)
            if renew:  # first: a failed update after it leaves the old marker to compare again
                github.remove_label(issue.number, UPGRADE_LATER_LABEL)
            same = (issue.title, issue.body.replace("\r\n", "\n").strip()) == (wanted_title, wanted.strip())
            if not same:
                github.update_issue(issue.number, wanted_title, wanted)
            outcome = Outcome.RENEWED if renew else Outcome.UNCHANGED if same else Outcome.UPDATED
            done.append(Proposed(upgrade, issue.number, outcome))
    return done


@contextmanager
def _named(upgrade: Upgrade, fix: str) -> Iterator[None]:
    """Re-raise a GitHub failure naming the upgrade, with the fix for a refused write"""
    try:
        yield
    except ReleaseError as exc:
        raise ReleaseError(f"upgrade {upgrade.id}: {exc}; if GitHub refused it (403): {fix}") from exc


@dataclass(frozen=True, slots=True)
class Applied:
    upgrade: Upgrade
    created: tuple[Path, ...]  # relative to the repo root
    kept: tuple[Path, ...]  # owned files that already existed, left as they were
    added: bool = True  # whether the edit added the upgrade's line; an upgrade that removes a key may not


def apply(root: Path, upgrade: Upgrade) -> Applied:
    """Add the upgrade's line to the config, or for one that removes a key take that key's line
    out (putting its line in that place when the table needs it), and create its files; refuse
    one that doesn't apply or is decided, and a config whose table this edit can't find"""
    path = root / CONFIG_PATH
    if not path.is_file():
        raise ReleaseError(f"no {CONFIG_PATH} in {root}")
    text = path.read_bytes().decode("utf-8")
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ReleaseError(f"{path}: {exc}") from None
    if not upgrade.applies(raw):
        if upgrade.removes is not None:
            raise ReleaseError(
                f"upgrade {upgrade.id} doesn't apply: [{upgrade.table}] in {CONFIG_PATH} sets no {upgrade.removes}"
            )
        raise ReleaseError(f"upgrade {upgrade.id} doesn't apply: {CONFIG_PATH} has no [{upgrade.table}] section")
    if upgrade.decided(raw):
        raise ReleaseError(
            f"upgrade {upgrade.id} is already decided: [{upgrade.table}] {upgrade.key} is set in {CONFIG_PATH}"
        )
    if upgrade.section(raw) is None:
        raise ReleaseError(
            f"upgrade {upgrade.id}: {CONFIG_PATH} has no [{upgrade.table}] table to add {upgrade.key} to"
        )
    adds = upgrade.adds(raw)
    expected = copy.deepcopy(dict(raw))
    table = expected
    for part in upgrade.table.split("."):
        table = table[part]
    if upgrade.removes is None:
        edited = _insert(text, upgrade)
        refused = ReleaseError(f"upgrade {upgrade.id}: can't add {upgrade.line} to {CONFIG_PATH}; add it by hand")
    else:
        edited = _replace(text, upgrade, upgrade.removes, adds)
        del table[upgrade.removes]
        refused = ReleaseError(
            f"upgrade {upgrade.id}: can't take {upgrade.removes} out of [{upgrade.table}] in {CONFIG_PATH};"
            " edit it by hand"
        )
    if adds:
        table[upgrade.key] = upgrade.value
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
    return Applied(upgrade, tuple(created), tuple(kept), adds)


def _body(text: str, upgrade: Upgrade, key: str) -> tuple[list[str], list[bool], int, int]:
    """The text's lines, whether each starts outside a multi-line string, and the bounds of the
    upgrade's table: its header line and the next header's (or the line count)"""
    lines = _LINE.findall(text)  # not splitlines: it also breaks on U+2028 and the like, TOML only on \n
    outside = _outside_strings(lines)
    headers = [i for i, line in enumerate(lines) if outside[i] and _ANY_HEADER.match(line)]
    found = [i for i in headers if (m := _HEADER.match(lines[i])) and re.sub(r"\s", "", m[1]) == upgrade.table]
    if len(found) != 1:
        raise ReleaseError(f"upgrade {upgrade.id}: no [{upgrade.table}] header line in {CONFIG_PATH} to edit {key} in")
    start = found[0]
    return lines, outside, start, next((i for i in headers if i > start), len(lines))


def _replace(text: str, upgrade: Upgrade, removes: str, adds: bool) -> str:
    """The text without the line that sets removes in the upgrade's table, a trailing comment
    with it, and with adds the upgrade's line in its place, in that line's ending"""
    lines, outside, start, end = _body(text, upgrade, removes)
    key = re.compile(rf"^\s*{re.escape(removes)}\s*=")
    found = [i for i in range(start + 1, end) if outside[i] and key.match(lines[i])]
    if len(found) != 1:
        raise ReleaseError(
            f"upgrade {upgrade.id}: no {removes} line under [{upgrade.table}] in {CONFIG_PATH} to take out"
        )
    at = found[0]
    ending = lines[at][len(lines[at].rstrip("\r\n")) :]
    lines[at : at + 1] = [upgrade.line + ending] if adds else []
    return "".join(lines)


def _insert(text: str, upgrade: Upgrade) -> str:
    """The text with the upgrade's line after the last line of its table's body (the header
    when the body is empty), in the file's own line ending"""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines, outside, start, end = _body(text, upgrade, upgrade.key)
    last = start
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if not outside[i] or (stripped and not stripped.startswith("#")):
            last = i
    if not lines[last].endswith("\n"):
        lines[last] += newline
    lines.insert(last + 1, upgrade.line + newline)
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
