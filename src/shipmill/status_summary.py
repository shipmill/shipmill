"""Spec 091: the repo's status in a few lines. `shipmill status --summary` prints the gate's
state from its state directory (tick.json, gate.json, last-result.json) and the default
branch's last landed pull request, the totals of open issues and pull requests, and each open
item on one of four lines by who holds it. The split is read from the conditions
`status --item` gives each item (spec 088), and through them from watch_state.py's GATE_RETRY,
GATE_PAUSED, and GATE_IDLE rows, which come from the gate's hand-off record, handed.json
(spec 046, D-87, spec 089). It only reads (S-091-9). Spec 094 adds one record per open item,
its holder, why, and what clears it, from finer holders, and a schema version."""

import datetime as dt
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from shipmill.config import CONFIG_PATH
from shipmill.errors import ReleaseError
from shipmill.gate import (
    LAST_RESULT,
    RECORD,
    TICK,
    Action,
    LastResult,
    StateRunner,
    TickRecord,
    load_last_result,
    load_launch,
    load_tick,
)
from shipmill.item_status import CHILDREN, WAIT, Condition, Holder, Kind, PullDetail, Ref, explain
from shipmill.land_window import LandWindow
from shipmill.status import CHECK_FAILURES, CLOSED_STATES, Facts, Issue, ago, first_line, gh_read
from shipmill.walk import HISTORY, LANDED, Landed, last_landed

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
WIDTH = max(len(label) for _, label in LINES)
RUNS = frozenset({Action.RUNNING.value, Action.STALLED.value})  # tick.json names the session it waits on
LAUNCHES = frozenset({Action.LAUNCH.value, Action.SESSION_DEAD.value})  # gate.json names the session it started
LINKED_STATES = frozenset({"IN_PROGRESS", "AGENT_DRAFT", "AGENT_DRAFT_HELD"})  # its open pull requests, as --item reads
OPEN_PULL = re.compile(r"(?<![\w/])#(\d+):(?:open|draft)\b")
DONE = frozenset({"closed", "merged", "not_planned"})
SESSION_SHOWN = 8  # a session id's first characters on the text line


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


def resolve(own: Mapping[int, Holder], links: Mapping[int, tuple[int, ...]]) -> dict[int, Holder]:
    """S-091-7: each item's line"""
    return {n: holder for n, (holder, _) in placed(own, links).items()}


def placed(own: Mapping[int, Holder], links: Mapping[int, tuple[int, ...]]) -> dict[int, tuple[Holder, int | None]]:
    """S-091-7, S-094-2: each item's line, the first in PRECEDENCE among its own and its links'
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
    found: dict[int, tuple[Holder, int | None]] = {}

    def line(n: int) -> Holder:
        if n not in found:
            best: tuple[Holder, int | None] = (own[n], None)
            for m in () if n in looped else links.get(n, ()):
                theirs = line(m)
                if PRECEDENCE.index(theirs) < PRECEDENCE.index(best[0]):
                    best = (theirs, m)
            found[n] = best
        return found[n][0]

    for n in own:
        line(n)
    return found


@dataclass(frozen=True, slots=True)
class Split:
    """The open items by who holds them: each line's issues and pull requests, ascending"""

    issues: Mapping[Holder, tuple[int, ...]]
    pulls: Mapping[Holder, tuple[int, ...]]

    def record(self) -> dict[str, object]:
        return {h.value: {"issues": list(self.issues.get(h, ())), "pulls": list(self.pulls.get(h, ()))} for h in Holder}


@dataclass(frozen=True, slots=True)
class Item:
    """S-094-1: one open item's record: its line, the link it took it from, what it waits on,
    and the condition that places it"""

    number: int
    kind: Kind
    holder: Holder
    via: int | None
    accept: str | None
    why: str
    clears: str
    waits_on: tuple[str, ...]
    conditions: tuple[Condition, ...]

    def placing(self) -> dict[str, object]:
        """S-094-8: the keys --item adds to its explanation, the same as the summary's"""
        return {
            "holder": self.holder.value,
            "via": self.via,
            "accept": self.accept,
            "why": self.why,
            "clears": self.clears,
            "waits_on": list(self.waits_on),
        }

    def record(self) -> dict[str, object]:
        return {
            "number": self.number,
            "kind": self.kind.value,
            **self.placing(),
            "conditions": [c.record() for c in self.conditions],
        }


def items(
    facts: Facts,
    read_detail: Callable[[int], PullDetail],
    window: LandWindow | None,
    start: Sequence[int] | None = None,
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
    lines = placed(own, {n: links.get(n, ()) for n in conditions})

    def deciding(n: int) -> Condition:
        holder, via = lines[n]
        if via is not None:
            return deciding(via)
        return next(c for c in conditions[n] if c.holder is holder)

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
        )
    return found


def split_of(found: Mapping[int, Item]) -> Split:
    by_issue: dict[Holder, list[int]] = {}
    by_pull: dict[Holder, list[int]] = {}
    for n, item in found.items():
        (by_issue if item.kind is Kind.ISSUE else by_pull).setdefault(item.holder, []).append(n)
    return Split(
        {h: tuple(sorted(ns)) for h, ns in by_issue.items()},
        {h: tuple(sorted(ns)) for h, ns in by_pull.items()},
    )


def split(facts: Facts, read_detail: Callable[[int], PullDetail], window: LandWindow | None) -> Split:
    """S-091-4 to S-091-7: every open issue and pull request on exactly one line"""
    return split_of(items(facts, read_detail, window))


@dataclass(frozen=True, slots=True)
class Session:
    """The session the gate's last tick says runs: its id and the item it was handed"""

    session: str
    item: str | None

    def record(self) -> dict[str, object]:
        return {"session": self.session, "item": self.item}


@dataclass(frozen=True, slots=True)
class GateState:
    """S-091-2, S-091-3: the gate line's parts, each read on its own"""

    configured: bool
    tick: TickRecord | None = None
    tick_error: str | None = None
    running: Session | None = None
    running_error: str | None = None
    result: LastResult | None = None
    result_error: str | None = None
    landed: Landed | None = None

    def text(self, now: dt.datetime) -> str:
        if not self.configured:
            return f"none: no [agents] in {CONFIG_PATH}"
        if self.tick_error is not None:
            tick = f"unread {TICK}: {self.tick_error}"
        elif self.tick is None:
            tick = "no tick recorded"
        else:
            tick = f"{self.tick.action} {ago(now - self.tick.at)} ago"
        if self.running_error is not None:
            running = f"unread {RECORD}: {self.running_error}"
        elif self.running is None:
            running = "no session runs"
        else:
            running = f"session {self.running.session[:SESSION_SHOWN]} on {self.running.item or 'item not recorded'}"
        if self.result_error is not None:
            result = f"unread {LAST_RESULT}: {self.result_error}"
        elif self.result is None:
            result = "no session has ended with a result yet"
        else:
            found = self.result
            result = f"last result {ago(now - found.at)} ago (session {found.session[:SESSION_SHOWN]} on {found.item})"
        landed = (
            f"no landed pull request in the last {LANDED} commits"
            if self.landed is None
            else f"last landed #{self.landed.number} {ago(now - self.landed.at)} ago"
        )
        lead = f"{tick}: {running}" if self.tick is not None else f"{tick}; {running}"
        return f"{lead}; {result}; {landed}"

    def record(self) -> dict[str, object]:
        if not self.configured:
            return {"configured": False}
        tick = None if self.tick is None else {"at": self.tick.at.isoformat(), "action": self.tick.action}
        return {
            "configured": True,
            "tick": tick,
            "tick_error": self.tick_error,
            "running": None if self.running is None else self.running.record(),
            "running_error": self.running_error,
            "result": None if self.result is None else self.result.record(),
            "result_error": self.result_error,
            "landed": None if self.landed is None else self.landed.record(),
        }


def read_gate_state(state: Path, configured: bool, landed: Landed | None) -> GateState:
    """S-091-2, S-091-3: tick.json, the running session (tick.json's, or gate.json's for a tick
    that launched one), and last-result.json, each file's error its own part's (D-55)"""
    if not configured:
        return GateState(False)
    tick = tick_error = running = running_error = result = result_error = None
    try:
        tick = load_tick(state / TICK)
    except CHECK_FAILURES as exc:
        tick_error = first_line(exc)
    if tick is not None and tick.action in RUNS and tick.running is not None:
        running = Session(tick.running.session, tick.running.item)
    elif tick is not None and tick.action in LAUNCHES:
        try:
            launch = load_launch(state / RECORD)
            running = None if launch is None else Session(launch.session, launch.item)
        except CHECK_FAILURES as exc:
            running_error = first_line(exc)
    try:
        result = load_last_result(state / LAST_RESULT)
    except CHECK_FAILURES as exc:
        result_error = first_line(exc)
    return GateState(True, tick, tick_error, running, running_error, result, result_error, landed)


LANDED_QUERY = (
    "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) {"
    f" defaultBranchRef {{ target {{ {HISTORY} }} }} }} }}"
)


def read_landed(repo: str, run: StateRunner) -> Landed | None:
    """S-091-2: the newest merged pull request of the default branch's last LANDED commits,
    as the gate's change check reads it (S-048-21)"""
    owner, _, name = repo.partition("/")
    cmd = ["gh", "api", "graphql", "-f", f"query={LANDED_QUERY}", "-F", f"owner={owner}", "-F", f"name={name}"]
    text = gh_read(cmd, run, "gh api graphql (the default branch's last landed pull request)")
    try:
        default = json.loads(text)["data"]["repository"]["defaultBranchRef"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ReleaseError(f"gh api graphql printed {text[:300]!r} for the default branch") from exc
    if not isinstance(default, dict):
        raise ReleaseError(f"gh api graphql printed no default branch for {repo}: {text[:300]}")
    return last_landed(default)


@dataclass(frozen=True, slots=True)
class Summary:
    repo: str
    gate: GateState
    issues: int
    pulls: int
    split: Split
    items: tuple[Item, ...] = ()

    def text(self, now: dt.datetime) -> str:
        lines = [f"{self.repo}: {counted(self.issues, 'open issue')}, {counted(self.pulls, 'pull request')}"]
        lines.append(f"  {'gate':<{WIDTH}}  {self.gate.text(now)}")
        for holder, label in LINES:
            issues, pulls = self.split.issues.get(holder, ()), self.split.pulls.get(holder, ())
            parts = [counted(len(ns), what) for ns, what in ((issues, "issue"), (pulls, "pull request")) if ns]
            lines.append(f"  {label:<{WIDTH}}  {', '.join(parts) or 'none'}")
        return "\n".join(lines) + "\n"

    def record(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "repo": self.repo,
            "gate": self.gate.record(),
            "totals": {"issues": self.issues, "pulls": self.pulls},
            "split": self.split.record(),
            "items": [i.record() for i in self.items],
        }


def counted(count: int, what: str) -> str:
    return f"{count} {what}{'' if count == 1 else 's'}"


def summarize(facts: Facts, gate: GateState, found: Mapping[int, Item]) -> Summary:
    issues = sum(1 for i in facts.issues if i.state not in CLOSED_STATES and not i.closed)
    return Summary(facts.repo, gate, issues, len(facts.pulls), split_of(found), tuple(found.values()))
