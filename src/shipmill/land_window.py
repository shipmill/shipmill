"""The land window, `[land.window]` in .github/shipmill.toml (spec 056): the hours, in one
zone, when a pull request of a held class may merge, and the spacing between such merges"""

import datetime as dt
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from shipmill.config import Table
from shipmill.errors import ReleaseError
from shipmill.schedule import weekdays

SECTION = "[land.window]"
DEFAULT_QUEUED_LABEL = "land-queued"
_ENTRY = re.compile(r"(?:(?P<days>\S+)\s+)?(?P<start>\d\d:\d\d)-(?P<end>\d\d:\d\d)")
_DAY = 24 * 60  # minutes
# how far ahead `opens` and `closes` look: a week holds every entry's days, and one more day
# covers an entry that ends at 24:00
_HORIZON_DAYS = 9
# merged pull requests read per held label and page, and the pages read at most, when
# last_held_merge looks for the newest merge (spec 056: bounded reads)
MERGED_PAGE = 50
MERGED_PAGES = 4


def _minutes(text: str) -> int:
    hour, minute = int(text[:2]), int(text[3:])
    return hour * 60 + minute if minute < 60 else -1


@dataclass(frozen=True, slots=True)
class Span:
    """One `open` or `closed` entry: its days, read in the window's zone, and a start and an
    end on the same day, the start inside and the end not"""

    text: str
    days: frozenset[int]  # 0 = Monday
    start: int  # minutes after midnight
    end: int  # minutes after midnight, up to 24:00

    @classmethod
    def parse(cls, text: str, where: str) -> Span:
        """where names the key, as '<file> [land.window] open'"""
        fix = f"{where}: an entry is '[<days> ]HH:MM-HH:MM', such as 'Mon-Fri 10:00-18:00' or '08:00-08:30'"
        m = _ENTRY.fullmatch(text.strip())
        if m is None:
            raise ReleaseError(f"{fix}; got {text!r}")
        start, end = _minutes(m["start"]), _minutes(m["end"])
        if not 0 <= start < _DAY or not 0 <= end <= _DAY:
            raise ReleaseError(f"{fix}; {text!r} holds a time that isn't a time of day (00:00 to 24:00)")
        if end <= start:
            raise ReleaseError(
                f"{fix}, its end after its start; {text!r} doesn't end after it starts: write a window across"
                " midnight as two entries, such as 'Fri 22:00-24:00' and 'Sat 00:00-02:00'"
            )
        try:
            days = frozenset(range(7)) if m["days"] is None else weekdays(m["days"], text)
        except ReleaseError as exc:
            raise ReleaseError(f"{where}: {exc}") from None
        return cls(text, days, start, end)

    def holds(self, local: dt.datetime) -> bool:
        """Whether the wall-clock moment, in the window's zone, falls inside the entry"""
        minute = local.hour * 60 + local.minute
        return local.weekday() in self.days and self.start <= minute < self.end


@dataclass(frozen=True, slots=True)
class LandWindow:
    zone_name: str
    zone: ZoneInfo
    open: tuple[Span, ...] | None  # None: open at any moment outside closed
    closed: tuple[Span, ...]
    labels: tuple[str, ...]
    queued_label: str
    spacing_minutes: int
    bypass_labels: tuple[str, ...]

    @classmethod
    def parse(cls, t: Table) -> LandWindow:
        t.allow("timezone", "open", "closed", "labels", "queued_label", "spacing_minutes", "bypass_labels")
        name = t.string("timezone")
        try:
            zone = ZoneInfo(name)
        except ZoneInfoNotFoundError, ValueError:
            raise ReleaseError(
                f"{t.where}: timezone {name!r} is not a known time zone; use an IANA name, such as 'Europe/Berlin'"
            ) from None
        opened = None
        if "open" in t.raw:
            opened = tuple(Span.parse(e, f"{t.where} open") for e in t.strings("open"))
            if not opened:
                raise ReleaseError(
                    f"{t.where}: open lists no entry; leave it out to be open at any moment outside closed"
                )
        closed = tuple(Span.parse(e, f"{t.where} closed") for e in t.strings("closed", default=()))
        labels = t.strings("labels")
        if not labels:
            raise ReleaseError(f"{t.where}: labels lists no label; name the held classes, such as ['rollout:high']")
        queued = t.string("queued_label", default=DEFAULT_QUEUED_LABEL)
        if not queued.strip():
            raise ReleaseError(f"{t.where}: queued_label must not be empty; leave it out for {DEFAULT_QUEUED_LABEL!r}")
        spacing = t.integer("spacing_minutes", default=0, low=0, high=None)
        bypass = t.strings("bypass_labels", default=())
        if both := sorted(set(labels) & set(bypass)):
            raise ReleaseError(
                f"{t.where}: {both} in both labels and bypass_labels; a label holds a pull request or lets it"
                " through, so keep it in one"
            )
        return cls(name, zone, opened, closed, labels, queued, spacing or 0, bypass)

    def is_open(self, moment: dt.datetime) -> bool:
        """Open at the moment: inside an `open` entry (any moment without `open`) and inside
        no `closed` entry, read on the wall clock of the window's zone"""
        local = moment.astimezone(self.zone)
        opened = self.open is None or any(s.holds(local) for s in self.open)
        return opened and not any(s.holds(local) for s in self.closed)

    def state(self, now: dt.datetime) -> WindowState:
        """Open or closed at now, with the next moment that changes it: `opens` when closed,
        `closes` when open; None when nothing changes it within a week"""
        current = self.is_open(now)
        change = next((c for c in self._changes(now) if self.is_open(c) is not current), None)
        return WindowState(current, None if current else change, change if current else None)

    def _changes(self, now: dt.datetime) -> list[dt.datetime]:
        """The moments after now, in order, where the window may open or close: each entry's
        start and end on each day, in either reading of a wall-clock time a fall-back
        repeats, and each change of the zone's offset, where the wall clock jumps"""
        today = now.astimezone(self.zone).date()
        spans = (*(self.open or ()), *self.closed)
        found: set[dt.datetime] = set()
        for back in range(-1, _HORIZON_DAYS):
            day = today + dt.timedelta(days=back)
            for span in spans:
                for minute in (span.start, span.end):
                    on = day + dt.timedelta(days=minute // _DAY)
                    wall = dt.datetime.combine(on, dt.time((minute % _DAY) // 60, minute % 60), tzinfo=self.zone)
                    found.update(wall.replace(fold=f).astimezone(dt.UTC) for f in (0, 1))
            found.update(self._offset_changes(day))
        return sorted(c for c in found if c > now)

    def _offset_changes(self, day: dt.date) -> list[dt.datetime]:
        """The moment, in UTC, the zone's offset changes during the day, found to the second"""
        low = dt.datetime.combine(day, dt.time(), tzinfo=self.zone).astimezone(dt.UTC)
        high = low + dt.timedelta(days=1)
        if low.astimezone(self.zone).utcoffset() == high.astimezone(self.zone).utcoffset():
            return []
        before = low.astimezone(self.zone).utcoffset()
        while high - low > dt.timedelta(seconds=1):
            middle = low + (high - low) / 2
            if middle.astimezone(self.zone).utcoffset() == before:
                low = middle
            else:
                high = middle
        return [high.replace(microsecond=0)]

    def held(self, labels: Sequence[str]) -> tuple[str, ...]:
        """A pull request's held labels: those of `labels` it carries, none when it carries a
        bypass label"""
        if any(label in self.bypass_labels for label in labels):
            return ()
        return tuple(label for label in self.labels if label in labels)

    def next_merge(self, last_held_merge: dt.datetime | None, now: dt.datetime) -> dt.datetime:
        """When the spacing allows the next held merge: the last one plus spacing_minutes, or
        now when that has passed, the spacing is 0, or no held merge happened"""
        if last_held_merge is None or self.spacing_minutes == 0:
            return now
        return max(now, last_held_merge + dt.timedelta(minutes=self.spacing_minutes))


@dataclass(frozen=True, slots=True)
class WindowState:
    open: bool
    opens: dt.datetime | None  # when closed: the next opening
    closes: dt.datetime | None  # when open: the next closing


def read(top: Table) -> LandWindow | None:
    """The config's [land.window], or None without it; [land] holds only the window"""
    if "land" not in top.raw:
        return None
    land = top.table("land")
    land.allow("window")
    if "window" not in land.raw:
        return None
    return LandWindow.parse(Table(land.table("window").raw, f"{top.where} {SECTION}"))


class Graphql(Protocol):
    """GitHub's GraphQL API for the repository, with $owner and $name set; GhCli is one,
    tests pass a fake"""

    def graphql(self, query: str) -> Any: ...


def last_held_merge(github: Graphql, labels: Sequence[str]) -> dt.datetime | None:
    """The newest merge into the default branch of a pull request carrying one of labels;
    None when there is none. Each label's merged pull requests are read newest-updated first,
    a page each, and a label's next page only while its last one was updated after the
    newest merge found: a merge can't come after the update it made, so nothing older can
    be newer. MERGED_PAGES rounds at most; one that still can't tell is refused"""
    aliases = {f"l{i}": label for i, label in enumerate(labels)}
    after: dict[str, str | None] = dict.fromkeys(aliases)
    newest: dt.datetime | None = None
    default: str | None = None
    for _ in range(MERGED_PAGES):
        found = github.graphql(_query({a: (aliases[a], after[a]) for a in after}))
        repository = _repository(found)
        if default is None:
            default = _default_branch(repository)
        oldest: dict[str, dt.datetime] = {}
        pages: dict[str, str] = {}
        for alias in after:
            nodes, cursor = _page(repository, alias)
            for node in nodes:
                if node["baseRefName"] == default and (newest is None or node["mergedAt"] > newest):
                    newest = node["mergedAt"]
            if cursor is not None and nodes:
                oldest[alias], pages[alias] = nodes[-1]["updatedAt"], cursor
        after = {a: pages[a] for a in pages if newest is None or oldest[a] > newest}
        if not after:
            return newest
    raise ReleaseError(
        f"can't tell the last held merge from the newest {MERGED_PAGE * MERGED_PAGES} merged pull requests of"
        f" {list(labels)}: too many were updated after it; try again later"
    )


def _query(wanted: Mapping[str, tuple[str, str | None]]) -> str:
    pages = " ".join(
        f"{alias}: pullRequests(states: MERGED, labels: [{json.dumps(label)}], first: {MERGED_PAGE}"
        f"{'' if cursor is None else f', after: {json.dumps(cursor)}'}"
        ", orderBy: {field: UPDATED_AT, direction: DESC}) "
        "{ pageInfo { hasNextPage endCursor } nodes { mergedAt updatedAt baseRefName } }"
        for alias, (label, cursor) in wanted.items()
    )
    return (
        "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name)"
        f" {{ defaultBranchRef {{ name }} {pages} }} }}"
    )


def _refuse(found: object) -> ReleaseError:
    return ReleaseError(f"gh api graphql printed {str(found)[:300]} for the merged held pull requests")


def _repository(found: Any) -> dict[str, Any]:
    if not isinstance(found, dict) or found.get("errors"):
        raise _refuse(found)
    data = found.get("data")
    repository = data.get("repository") if isinstance(data, dict) else None
    if not isinstance(repository, dict):
        raise _refuse(found)
    return repository


def _default_branch(repository: dict[str, Any]) -> str:
    ref = repository.get("defaultBranchRef")
    if not isinstance(ref, dict) or not isinstance(ref.get("name"), str) or not ref["name"]:
        raise _refuse(repository)
    return str(ref["name"])


def _page(repository: dict[str, Any], alias: str) -> tuple[list[dict[str, Any]], str | None]:
    """A label's nodes, each with mergedAt and updatedAt as times, and the cursor of its next
    page, None on the last"""
    connection = repository.get(alias)
    if not isinstance(connection, dict) or not isinstance(connection.get("nodes"), list):
        raise _refuse(repository)
    info = connection.get("pageInfo")
    if not isinstance(info, dict) or not isinstance(info.get("hasNextPage"), bool):
        raise _refuse(connection)
    nodes = []
    for node in connection["nodes"]:
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("mergedAt"), str)
            or not isinstance(node.get("updatedAt"), str)
            or not isinstance(node.get("baseRefName"), str)
        ):
            raise _refuse(node)
        nodes.append(node | {"mergedAt": _time(node["mergedAt"]), "updatedAt": _time(node["updatedAt"])})
    cursor = info.get("endCursor")
    if info["hasNextPage"] and not isinstance(cursor, str):
        raise _refuse(connection)
    return nodes, cursor if info["hasNextPage"] else None


def _time(text: str) -> dt.datetime:
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        raise ReleaseError(f"GitHub sent {text!r}, not a time") from None
    if when.tzinfo is None:
        raise ReleaseError(f"GitHub sent a time without a zone: {text!r}")
    return when


def record(window: LandWindow | None, now: dt.datetime, last: dt.datetime | None) -> dict[str, Any]:
    """`shipmill window --json`'s object; without the section only `configured: false`"""
    if window is None:
        return {"configured": False}
    state = window.state(now)

    def stamp(moment: dt.datetime | None) -> str | None:
        return None if moment is None else moment.astimezone(window.zone).isoformat(timespec="seconds")

    return {
        "configured": True,
        "timezone": window.zone_name,
        "open": state.open,
        "opens": stamp(state.opens),
        "closes": stamp(state.closes),
        "labels": list(window.labels),
        "bypass_labels": list(window.bypass_labels),
        "queued_label": window.queued_label,
        "spacing_minutes": window.spacing_minutes,
        "last_held_merge": stamp(last),
        "next_merge": stamp(window.next_merge(last, now)),
    }
