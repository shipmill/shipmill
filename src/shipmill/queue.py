"""Spec 094: who holds each open issue and pull request of a gated repo, why, and what clears
it. `shipmill queue` builds one record per open item from one read of the repo's facts, by the
code `status --item` explains one item with (spec 088), places each on a holder (finer than spec
091's four lines), and with --fleet does so for every gate job on this host, one repo at a time.
It only reads."""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from shipmill.item_links import Holds, ItemRef, Waiter, local_holds, merged, waiters
from shipmill.item_status import CHILDREN, WAIT, Condition, Holder, Kind, PullDetail, Ref, bucket, explain
from shipmill.land_window import LandWindow
from shipmill.status import CLOSED_STATES, Facts, Issue

SCHEMA = 1  # S-094-9: raised by a change that removes or renames a key, or changes a value's meaning
# S-091-5, S-091-6, S-094-5: an item counts on the first of these that holds
PRECEDENCE = (
    Holder.ATTENTION,
    Holder.MAINTAINER,
    Holder.AGENT,
    Holder.PEOPLE,
    Holder.ELSEWHERE,
    Holder.POSTPONED,
    Holder.NOBODY,
)
# S-091-1, S-094-7: the lines in the order they print, with their labels
LINES = (
    (Holder.MAINTAINER, "waits on you"),
    (Holder.AGENT, "agent takes it"),
    (Holder.ATTENTION, "needs attention"),
    (Holder.PEOPLE, "waits on people"),
    (Holder.ELSEWHERE, "waits elsewhere"),
    (Holder.POSTPONED, "postponed"),
    (Holder.NOBODY, "waits on nobody"),
)
ACCEPTS = frozenset({"opportunity", "plan"})  # S-094-6: verdicts the maintainer accepts or declines
LINKED_STATES = frozenset({"IN_PROGRESS", "AGENT_DRAFT", "AGENT_DRAFT_HELD"})  # its open pull requests, as --item reads
OPEN_PULL = re.compile(r"(?<![\w/])#(\d+):(?:open|draft)\b")
DONE = frozenset({"closed", "merged", "not_planned"})
RATE_LIMIT = re.compile(r"rate limit", re.IGNORECASE)  # S-094-12: GitHub's primary or secondary limit


def own_holder(conditions: Sequence[Condition]) -> Holder:
    """S-091-5, S-091-6, S-094-5: the first holder in PRECEDENCE among its conditions'; nobody
    for none"""
    return min((c.holder for c in conditions), key=PRECEDENCE.index, default=Holder.NOBODY)


def linked(repo: str, issue: Issue, opened: frozenset[int]) -> tuple[int, ...]:
    """S-091-7: the open items of the repo the issue counts with: its open pull requests
    (IN_PROGRESS, AGENT_DRAFT) or the open items it waits on (BLOCKED), as --item names them; a
    parent moving through its children counts by its own conditions alone (S-094-5)"""
    found: list[int] = []
    if issue.state in LINKED_STATES:
        found = [int(n) for n in OPEN_PULL.findall(issue.note)]
    elif issue.state == "BLOCKED" and not issue.note.startswith(CHILDREN):
        for w in WAIT.finditer(issue.note):
            own, _, number = w["ref"].rpartition("#")
            if own.casefold() == repo.casefold() and w["state"].lower() not in DONE:
                found.append(int(number))
    return tuple(dict.fromkeys(n for n in found if n in opened and n != issue.number))


def waits_on(repo: str, issue: Issue) -> tuple[str, ...]:
    """S-094-3: the not-closed targets of a BLOCKED note, of this repo or another, and the open
    pull requests of an IN_PROGRESS or AGENT_DRAFT note, as owner/name#N"""
    if issue.state in LINKED_STATES:
        found = [f"{repo}#{n}" for n in OPEN_PULL.findall(issue.note)]
    elif issue.state == "BLOCKED":
        found = [w["ref"] for w in WAIT.finditer(issue.note) if w["state"].lower() not in DONE]
    else:
        found = []
    return tuple(dict.fromkeys(found))


def placed[H](
    own: Mapping[int, H], links: Mapping[int, tuple[int, ...]], order: Sequence[H]
) -> dict[int, tuple[H, int | None]]:
    """S-091-7, S-094-2: each item's line, the first in order among its own and its links'
    lines, and the link it took it from (None for its own, which wins a tie); an item on a
    cycle of links counts by its own conditions alone, so every walk ends"""

    def reaches(start: int) -> bool:
        seen: set[int] = set()
        todo = list(links.get(start, ()))
        while todo:
            n = todo.pop()
            if n == start:
                return True
            if n not in seen:
                seen.add(n)
                todo.extend(links.get(n, ()))
        return False

    looped = {n for n in own if reaches(n)}
    found: dict[int, tuple[H, int | None]] = {}

    def line(n: int) -> H:
        if n not in found:
            best: tuple[H, int | None] = (own[n], None)
            for m in () if n in looped else links.get(n, ()):
                theirs = line(m)
                if order.index(theirs) < order.index(best[0]):
                    best = (theirs, m)
            found[n] = best
        return found[n][0]

    for n in own:
        line(n)
    return found


def blocking(repo: str, number: int, holds: Holds, buckets: Mapping[int, str]) -> tuple[Waiter, ...]:
    """S-094-14: the open issues that wait on the item, by the code --item's blocks come from
    (S-088-14): each of the repo with its bucket, any other with its walk state's line"""
    return waiters(ItemRef(repo, number), holds, buckets.get)


@dataclass(frozen=True, slots=True)
class Item:
    """S-094-1: one open item's record: its line, the link it took it from, what it waits on,
    what waits on it, its umbrella, and the condition that places it"""

    number: int
    kind: Kind
    holder: Holder
    via: int | None
    accept: str | None
    why: str
    clears: str
    waits_on: tuple[str, ...]
    conditions: tuple[Condition, ...]
    blocks: tuple[Waiter, ...] = ()
    parent: str | None = None

    def placing(self) -> dict[str, object]:
        """S-094-8, S-094-16: the keys --item adds to its explanation, the same as the
        summary's; its blocks come from its own walk (S-088-14)"""
        return {
            "holder": self.holder.value,
            "via": self.via,
            "accept": self.accept,
            "why": self.why,
            "clears": self.clears,
            "waits_on": list(self.waits_on),
            "parent": self.parent,
        }

    def record(self) -> dict[str, object]:
        return {
            "number": self.number,
            "kind": self.kind.value,
            **self.placing(),
            "blocks": [w.record() for w in self.blocks],
            "conditions": [c.record() for c in self.conditions],
        }


def local_links(facts: Facts) -> tuple[Holds, dict[int, str]]:
    """S-094-14: the repo's BLOCKED open issues with what each waits on, from the notes the
    facts already hold, and the bucket of each, as --item reads them (S-088-14)"""
    opened = [i for i in facts.issues if i.state not in CLOSED_STATES and not i.closed]
    holds = local_holds(facts.repo, [(i.number, i.state, i.note) for i in opened])
    return holds, {ref.number: bucket(facts, ref.number, Kind.ISSUE) for ref, _, _ in holds.values()}


def items(
    facts: Facts,
    read_detail: Callable[[int], PullDetail],
    window: LandWindow | None,
    start: Sequence[int] | None = None,
    held: tuple[Holds, Mapping[int, str]] | None = None,
) -> dict[int, Item]:
    """S-094-1, S-094-2, S-094-8: the records of the open items from start (every open item
    when None) and of the open items of the repo they count with, by number; --item and the
    summary both build theirs here"""
    issues = {i.number: i for i in facts.issues if i.state not in CLOSED_STATES and not i.closed}
    kinds = {n: Kind.ISSUE for n in issues} | {p.number: Kind.PULL for p in facts.pulls}
    opened = frozenset(kinds)
    links = {n: linked(facts.repo, i, opened) for n, i in issues.items()}
    todo = list(kinds if start is None else start)
    conditions: dict[int, tuple[Condition, ...]] = {}
    while todo:  # the closure over links, each item explained once
        n = todo.pop()
        if n not in conditions:
            conditions[n] = explain(facts, Ref(str(n), n, kinds.get(n)), read_detail, window).conditions
            todo.extend(links.get(n, ()))
    own = {n: own_holder(found) for n, found in conditions.items()}
    lines = placed(own, {n: links.get(n, ()) for n in conditions}, PRECEDENCE)

    def deciding(n: int) -> Condition:
        holder, via = lines[n]
        if via is not None:
            return deciding(via)
        return next(c for c in conditions[n] if c.holder is holder)

    holds, buckets = local_links(facts) if held is None else held
    found = {}
    for n in sorted(conditions):
        holder, via = lines[n]
        issue = issues.get(n)
        verdict = None if issue is None or issue.state != "TRIAGED" else issue.verdict
        decided = deciding(n)
        found[n] = Item(
            n,
            kinds[n],
            holder,
            via,
            verdict if verdict in ACCEPTS else None,
            decided.reason,
            decided.clears,
            () if issue is None else waits_on(facts.repo, issue),
            conditions[n],
            blocking(facts.repo, n, holds, buckets),
            None if issue is None else issue.parent,
        )
    return found


def split_of(found: Mapping[int, Item]) -> dict[Holder, dict[Kind, tuple[int, ...]]]:
    """S-094-1: each holder's issues and pull requests, ascending"""
    by: dict[Holder, dict[Kind, list[int]]] = {h: {Kind.ISSUE: [], Kind.PULL: []} for h in Holder}
    for n, item in found.items():
        by[item.holder][item.kind].append(n)
    return {h: {k: tuple(sorted(ns)) for k, ns in kinds.items()} for h, kinds in by.items()}


@dataclass(frozen=True, slots=True)
class Queue:
    """S-094-1, S-094-7: the repo's open items by who holds them"""

    repo: str
    issues: int
    pulls: int
    items: tuple[Item, ...]
    holds: Holds = field(default_factory=dict)  # S-094-15: its BLOCKED issues' holds, for the fleet
    buckets: Mapping[int, str] = field(default_factory=dict)  # and their buckets

    def linked(self, fleet: Holds) -> Queue:
        """S-094-15: its records with what waits on each across the fleet's repos, its own
        holds and the other repos' together"""
        held = merged(self.holds, fleet)
        found = tuple(replace(i, blocks=blocking(self.repo, i.number, held, self.buckets)) for i in self.items)
        return replace(self, items=found)

    def record(self) -> dict[str, object]:
        split = split_of({i.number: i for i in self.items})
        return {
            "schema": SCHEMA,
            "repo": self.repo,
            "totals": {"issues": self.issues, "pulls": self.pulls},
            "split": {
                h.value: {"issues": list(ks[Kind.ISSUE]), "pulls": list(ks[Kind.PULL])} for h, ks in split.items()
            },
            "items": [i.record() for i in self.items],
        }

    def text(self) -> str:
        lines = [f"{self.repo}: {counted(self.issues, 'open issue')}, {counted(self.pulls, 'pull request')}"]
        for holder, label in LINES:
            held = [i for i in self.items if i.holder is holder]
            lines.append(f"  {label}{'' if held else ': none'}")
            lines += [f"    #{i.number} {i.kind.value}: {i.why} (clears: {i.clears})" for i in held]
        return "\n".join(lines) + "\n"


def counted(count: int, what: str) -> str:
    return f"{count} {what}{'' if count == 1 else 's'}"


def queue(facts: Facts, read_detail: Callable[[int], PullDetail], window: LandWindow | None) -> Queue:
    issues = sum(1 for i in facts.issues if i.state not in CLOSED_STATES and not i.closed)
    holds, buckets = local_links(facts)
    found = tuple(items(facts, read_detail, window, held=(holds, buckets)).values())
    return Queue(facts.repo, issues, len(facts.pulls), found, holds, buckets)


def fleet_linked(queues: Sequence[Queue]) -> list[Queue]:
    """S-094-15: each repo's queue with the waiters of every repo the fleet read"""
    fleet = merged(*(q.holds for q in queues))
    return [q.linked(fleet) for q in queues]


def rate_limited(error: str) -> bool:
    """S-094-12: a read GitHub refused for its rate limit"""
    return RATE_LIMIT.search(error) is not None


def not_read(repo: str) -> dict[str, object]:
    """S-094-12: a fleet entry left unread once GitHub's rate limit was reached"""
    return {"schema": SCHEMA, "repo": repo, "error": "not read: GitHub's rate limit was reached on an earlier repo"}
