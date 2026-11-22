"""Spec 088: why one open issue or pull request is not closed. `shipmill status --item REF`
reads what the picture reads (status.Facts), plus one `gh pr view` for a pull request and the
land window at now, and names the item's bucket and every condition that keeps it open, each
with who clears it and how. It only reads (S-088-12)."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from shipmill.autonomy import HOLD_LABEL, Autonomy, Source, StageKind, StageLevel
from shipmill.config import CONFIG_PATH
from shipmill.errors import ReleaseError
from shipmill.gate import StateRunner
from shipmill.land_window import LandWindow
from shipmill.status import (
    CLOSED_STATES,
    ISSUE_LINES,
    READY_LABEL,
    Facts,
    Issue,
    Pull,
    Row,
    gh_read,
    github,
    parked,
    stage_levels,
    to_land,
    to_merge,
    waiting,
)

NUMBER = re.compile(r"[1-9]\d*")
URL = re.compile(
    r"https://github\.com/(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/(?P<kind>issues|pull)/(?P<number>[1-9]\d*)"
    r"/?(?:[?#].*)?"
)
# a #N of this repo in a row's subject or detail, never one of owner/repo#N
OWN_NUMBER = re.compile(r"(?<![\w/#])#(\d+)\b")
GATE_IDLE = "GATE_IDLE"  # watch_state.py's row for an item handed to a session that wrote nothing on it
FAILED = frozenset({"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"})
PENDING = frozenset({"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"})


class Kind(StrEnum):
    ISSUE = "issue"
    PULL = "pull"


SAID = {Kind.ISSUE: "an issue", Kind.PULL: "a pull request"}


class Who(StrEnum):
    """Who clears a condition: the maintainer, an agent (a gate tick), a person (an assignee or
    the reporter), or an event (a check finishing, the window opening, an item closing)"""

    MAINTAINER = "maintainer"
    AGENT = "agent"
    PERSON = "person"
    EVENT = "event"

    @property
    def text(self) -> str:
        return {"maintainer": "the maintainer", "agent": "an agent", "person": "a person", "event": "an event"}[
            self.value
        ]


@dataclass(frozen=True, slots=True)
class Ref:
    """The item --item names: its number, and its kind when a URL gave one"""

    given: str
    number: int
    kind: Kind | None


def parse_ref(text: str, repo: str) -> Ref:
    """S-088-2: a number, or a GitHub issue or pull request URL of repo (case-blind)"""
    given = text.strip()
    if NUMBER.fullmatch(given):
        return Ref(given, int(given), None)
    found = URL.fullmatch(given)
    if found is None:
        raise ReleaseError(
            f"--item {text!r} is neither a number nor a GitHub issue or pull request URL,"
            f" such as 12 or {github(repo)}/issues/12"
        )
    if found["repo"].casefold() != repo.casefold():
        raise ReleaseError(f"--item {text!r} is an item of {found['repo']}, not of {repo}; name {repo}'s own item")
    return Ref(given, int(found["number"]), Kind.ISSUE if found["kind"] == "issues" else Kind.PULL)


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    state: str  # a check run's conclusion or status, or a status context's state


@dataclass(frozen=True, slots=True)
class PullDetail:
    """One pull request's checks, review decision, and labels, from `gh pr view`"""

    checks: tuple[Check, ...]
    review: str
    labels: tuple[str, ...]


def parse_pull_detail(text: str) -> PullDetail:
    raw = json.loads(text)
    checks = []
    for c in raw.get("statusCheckRollup") or ():
        if c.get("__typename") == "StatusContext":
            checks.append(Check(str(c["context"]), str(c["state"])))
        else:
            status, conclusion = str(c.get("status") or ""), str(c.get("conclusion") or "")
            checks.append(Check(str(c["name"]), conclusion if status == "COMPLETED" else status or "PENDING"))
    labels = tuple(str(label["name"]) for label in raw.get("labels") or ())
    return PullDetail(tuple(checks), str(raw.get("reviewDecision") or ""), labels)


def read_pull_detail(repo: str, number: int, run: StateRunner) -> PullDetail:
    fields = "statusCheckRollup,reviewDecision,labels"
    cmd = ["gh", "pr", "view", str(number), "-R", repo, "--json", fields]
    return parse_pull_detail(gh_read(cmd, run, f"gh pr view {number}"))


@dataclass(frozen=True, slots=True)
class Condition:
    reason: str
    who: Who
    clears: str

    def record(self) -> dict[str, str]:
        return {"reason": self.reason, "who": self.who.value, "clears": self.clears}


@dataclass(frozen=True, slots=True)
class Explanation:
    repo: str
    number: int
    kind: Kind
    bucket: str
    conditions: tuple[Condition, ...]

    @property
    def url(self) -> str:
        return f"{github(self.repo)}/{'pull' if self.kind is Kind.PULL else 'issues'}/{self.number}"

    def text(self) -> str:
        lines = [f"{self.repo}#{self.number} ({self.url}): {self.bucket}"]
        for c in self.conditions:
            lines += [f"  why:  {c.reason}", f"        clears: {c.who.text} ({c.clears})"]
        return "\n".join(lines) + "\n"

    def record(self) -> dict[str, object]:
        return {
            "repo": self.repo,
            "number": self.number,
            "kind": self.kind.value,
            "url": self.url,
            "bucket": self.bucket,
            "conditions": [c.record() for c in self.conditions],
        }


# S-088-8: what a triaged issue's verdict waits on, and who clears it
VERDICT_WAITS: dict[str, tuple[str, Who, str]] = {
    "opportunity": (
        "waits for product intake to group it and the maintainer to accept it",
        Who.MAINTAINER,
        "accept or decline the opportunity",
    ),
    "feature": ("waits on its spec", Who.AGENT, "the spec gate opens its spec, which the maintainer approves"),
    "clarify": ("waits on the reporter's answer", Who.PERSON, "the reporter answers on the issue"),
    "needs a decision": ("waits on the maintainer's decision", Who.MAINTAINER, "decide on the issue"),
    "plan": ("waits on the maintainer's answer to the plan", Who.MAINTAINER, "accept or change the plan"),
    "postponed": ("waits for a later release", Who.EVENT, "a stable release that makes triage revisit it"),
    "won't fix": ("was declined and waits to be closed", Who.MAINTAINER, "close it"),
    "duplicate": ("is a duplicate and waits to be closed", Who.MAINTAINER, "close it"),
    "upstream": ("waits on the repo that owns the fault", Who.EVENT, "the upstream report closing"),
}


def _find(facts: Facts, ref: Ref) -> tuple[Kind, Issue | None, Pull | None]:
    issue = next(
        (i for i in facts.issues if i.number == ref.number and i.state not in CLOSED_STATES and not i.closed), None
    )
    pull = next((p for p in facts.pulls if p.number == ref.number), None)
    kind = Kind.ISSUE if issue is not None else Kind.PULL if pull is not None else None
    if kind is None:
        raise ReleaseError(f"--item {ref.given!r}: #{ref.number} is no open issue or pull request of {facts.repo}")
    if ref.kind is not None and ref.kind is not kind:
        raise ReleaseError(
            f"--item {ref.given!r}: #{ref.number} of {facts.repo} is an open {SAID[kind]}, not {SAID[ref.kind]}"
        )
    return kind, issue, pull


def bucket(facts: Facts, number: int, kind: Kind) -> str:
    """S-088-3: the label of the picture's line the item is on (item_lines' order), else open"""
    wait = waiting(facts)
    if number in (wait.issues if kind is Kind.ISSUE else wait.pulls):
        return "needs decision"
    if kind is Kind.ISSUE:
        if any(o.issue == number for o in facts.upgrades):
            return "upgrade"
        state = next(i.state for i in facts.issues if i.number == number)
        return next((name for name, states in ISSUE_LINES if state in states), "open")
    merge = to_merge(facts)
    if number in to_land(facts.rows) and number not in merge:
        return "to land"
    if number in merge:
        return "to merge"
    if any(n == number for n, _ in parked(facts.rows).people):
        return "parked"
    if any(p.number == number and p.draft for p in facts.pulls):
        return "drafts"
    return "open"


def names(r: Row, number: int) -> bool:
    return any(int(n) == number for n in OWN_NUMBER.findall(f"{r.subject} {r.detail}"))


def _level(facts: Facts, stage: str) -> StageLevel:
    return next(level for level in stage_levels(facts.autonomy, facts.environments, facts.rows) if level.stage == stage)


def repo_conditions(facts: Facts, stage: str | None) -> list[Condition]:
    """S-088-5: a hold, no gate, and the item's stage below act, each the maintainer's"""
    found = []
    holds = [n for r in facts.rows if r.state == "HOLD" for n in OWN_NUMBER.findall(r.subject)[:1]]
    for n in holds:
        found.append(
            Condition(
                f"the {HOLD_LABEL} issue #{n} holds what the gate does", Who.MAINTAINER, f"close #{n} once it can go on"
            )
        )
    if stage is None:  # what no gate or a level holds back is the gate's work only
        return found
    if facts.gate.agents is None:
        found.append(
            Condition(
                f"no gate works on it: no [agents] in {CONFIG_PATH}",
                Who.MAINTAINER,
                f"add [agents] to {CONFIG_PATH}, or do the step by hand",
            )
        )
        return found
    level = _level(facts, stage)
    if level.source is Source.HOLD:
        return found  # the hold's condition says it
    if level.effective is Autonomy.OBSERVE:
        found.append(
            Condition(
                f"[autonomy] {stage} is observe: no session acts on it",
                Who.MAINTAINER,
                f'set {stage} = "propose" or "act" in [autonomy], or do it by hand',
            )
        )
    elif level.effective is Autonomy.PROPOSE and stage != StageKind.LAND:
        found.append(
            Condition(
                f"[autonomy] {stage} is propose: a session proposes and waits for your answer",
                Who.MAINTAINER,
                f'answer the proposal on it, or set {stage} = "act" in [autonomy]',
            )
        )
    return found


def gate_conditions(facts: Facts, number: int, kind: Kind, stage: str | None) -> list[Condition]:
    """S-088-9: the gate's work is the rows it starts a session on (their agent mark), and the
    open pull requests unless land is observe (gate.decide); an item it handed to a session that
    wrote nothing on it waits for a change (GATE_IDLE)"""
    if facts.gate.agents is None or any(r.state == "HOLD" for r in facts.rows):
        return []
    idle = [r for r in facts.rows if r.state == GATE_IDLE and names(r, number)]
    if idle:
        return [
            Condition(
                "the gate handed it to a session that wrote nothing on it; it waits for a change",
                Who.EVENT,
                "a new comment, push, or label on it",
            )
        ]
    land = _level(facts, StageKind.LAND).effective
    work = [
        r
        for r in facts.rows
        if names(r, number)
        and (r.agent or (r.state == "PRS_OPEN" and kind is Kind.PULL and land is not Autonomy.OBSERVE))
    ]
    if not work or stage is None or _level(facts, stage).effective is not Autonomy.ACT:
        return []
    return [Condition("the gate takes it up on a coming tick, in its tier order", Who.AGENT, "the next gate tick")]


WAIT = re.compile(r"(?P<ref>[\w.-]+/[\w.-]+#\d+):(?P<state>\w+)")
WINDOW = re.compile(r"veto window of (?P<pr>#\d+) until (?P<until>\S+)")


def issue_conditions(facts: Facts, issue: Issue) -> list[Condition]:
    """S-088-6, S-088-8: the issue's triage_state.py state and its note"""
    state, note = issue.state, issue.note
    if state == "NEEDS_DECISION":
        return [
            Condition("waits on the answer to its needs-decision question", Who.MAINTAINER, "answer the question on it")
        ]
    if state == "BLOCKED":
        found = [
            Condition(f"waits on {w['ref']} ({w['state'].lower()})", Who.EVENT, f"{w['ref']} closing or merging")
            for w in WAIT.finditer(note)
            if w["state"].lower() not in ("closed", "merged", "not_planned")
        ]
        window = WINDOW.search(note)
        if window is not None:
            found.append(
                Condition(
                    f"the veto window of {window['pr']}'s approval is open",
                    Who.EVENT,
                    f"the window passing at {window['until']}",
                )
            )
        if note == "labelled blocked":
            found.append(
                Condition(
                    "labelled blocked",
                    Who.MAINTAINER,
                    f"gh issue edit {issue.number} -R {facts.repo} --remove-label blocked once it can go on",
                )
            )
        return found or [Condition("blocked", Who.EVENT, "the items it waits on closing or merging")]
    if state == "POSTPONED":
        paths = note.removeprefix("waits on ") if note.startswith("waits on ") else None
        when = "a stable release that changes " + paths if paths else "the next stable release, when triage revisits it"
        return [Condition("postponed", Who.EVENT, when)]
    if state == "WITH_PERSON":
        people = " ".join([*(f"@{p}" for p in issue.assignees), *issue.teams])
        return [Condition(f"a person's item: waits on {people}", Who.PERSON, "its assignees do the step and close it")]
    if state in ("IN_PROGRESS", "AGENT_DRAFT", "AGENT_DRAFT_HELD"):
        opened = [int(n) for n in re.findall(r"(?<![\w/])#(\d+):(?:open|draft)\b", note)]
        return [
            Condition(
                f"its pull request #{n} is open",
                Who.EVENT,
                f"#{n} merging; {facts.command} status --item {n} says what holds it",
            )
            for n in opened
        ]
    if state == "UPSTREAM":
        return [Condition("an upstream report: waits on the repo that owns the fault", Who.EVENT, "that repo's fix")]
    if state == "TRIAGED":
        if issue.verdict is None:
            return [
                Condition(
                    "triaged with nothing pending", Who.EVENT, "a new comment or label that moves it back to triage"
                )
            ]
        reason, who, clears = VERDICT_WAITS[issue.verdict]
        return [Condition(f"triaged as {issue.verdict}: {reason}", who, clears)]
    return []


def pull_conditions(facts: Facts, pull: Pull, detail: PullDetail, window: LandWindow | None) -> list[Condition]:
    """S-088-10: what holds the pull request's merge"""
    found = []
    if pull.draft:
        found.append(Condition("a draft: it belongs to its author (D-67)", Who.PERSON, "its author marks it ready"))
    if pull.number in waiting(facts).pulls:
        found.append(
            Condition("waits on the answer to its needs-decision question", Who.MAINTAINER, "answer the question on it")
        )
    if pull.merge == "BEHIND":
        found.append(
            Condition(
                f"behind {pull.base}", Who.AGENT, f"gh pr update-branch {pull.number} -R {facts.repo}, by a session"
            )
        )
    elif pull.merge == "DIRTY":
        found.append(Condition(f"conflicts with {pull.base}", Who.AGENT, "a session rebases it"))
    elif pull.merge == "BLOCKED":
        found.append(
            Condition("branch protection blocks the merge", Who.EVENT, "what the rules require: checks, a review")
        )
    for c in detail.checks:
        if c.state in FAILED:
            found.append(Condition(f"check {c.name} failed", Who.AGENT, "a session fixes the cause or reruns a flake"))
        elif c.state in PENDING:
            found.append(Condition(f"check {c.name} is pending", Who.EVENT, "its run finishing"))
    if detail.review == "CHANGES_REQUESTED":
        found.append(Condition("a review requested changes", Who.AGENT, "a session addresses the review"))
    elif detail.review == "REVIEW_REQUIRED":
        found.append(Condition("a review is required", Who.MAINTAINER, "a review of its head"))
    if pull.number in to_merge(facts):
        found.append(
            Condition(
                f'labelled {READY_LABEL} under [autonomy] land = "propose"',
                Who.MAINTAINER,
                "merge it once you have read it",
            )
        )
    if window is not None and window.held(detail.labels):
        state = window.state(facts.now)
        if not state.open:
            opens = "" if state.opens is None else f" at {state.opens.isoformat(timespec='minutes')}"
            held = ", ".join(window.held(detail.labels))
            found.append(Condition(f"the land window is closed for {held}", Who.EVENT, f"the window opening{opens}"))
    return found


def explain(
    facts: Facts,
    ref: Ref,
    read_detail: Callable[[int], PullDetail],
    window: LandWindow | None,
) -> Explanation:
    """S-088-1 to S-088-11: the item's bucket and conditions; every open item names one (S-088-4)"""
    kind, issue, pull = _find(facts, ref)
    shown = bucket(facts, ref.number, kind)
    if kind is Kind.PULL:
        stage: str | None = StageKind.LAND
    elif shown == "to triage":
        stage = StageKind.TRIAGE
    elif shown in ("to build", "in progress"):
        stage = StageKind.FIX
    else:
        stage = None
    conditions = repo_conditions(facts, stage if shown in ("to triage", "to build", "to land") else None)
    if issue is not None:
        conditions += issue_conditions(facts, issue)
    if pull is not None:
        conditions += pull_conditions(facts, pull, read_detail(pull.number), window)
    conditions += gate_conditions(facts, ref.number, kind, stage)
    if not conditions:
        conditions.append(
            Condition("no reason read: the gate's next tick reads it again", Who.AGENT, "the next gate tick")
        )
    return Explanation(facts.repo, ref.number, kind, shown, tuple(dict.fromkeys(conditions)))
