"""Spec 088: why one open issue or pull request is not closed. `shipmill status --item REF`
reads the item's own state first (is_open), then the picture's readings an explanation uses
(status.Facts, without the host's checks, #1469), plus one `gh pr view` for a pull request and
the land window at now, and names the item's bucket and every condition that keeps it open,
each with who clears it and how. It only reads (S-088-12)."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from shipmill.autonomy import HOLD_LABEL, Autonomy, Source, StageKind, StageLevel
from shipmill.config import CONFIG_PATH
from shipmill.errors import ReleaseError
from shipmill.gate import StateRunner
from shipmill.item_links import Holds, ItemRef, Links, Reach, local_holds, merged, waiters
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
GATE_RETRY = "GATE_RETRY"  # spec 089: its row for an item whose session ended error, held by the backoff
GATE_PAUSED = "GATE_PAUSED"  # spec 089: its row for the credential's pause, which holds every launch
# what pauses the gate, by a GATE_PAUSED row's subject (spec 089, spec 095)
PAUSE_CAUSES = {
    "limit": "a usage limit",
    "auth": "a refused credential",
    "github_limit": "GitHub's rate limit",
    "disk": "a full disk",
}
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


class Holder(StrEnum):
    """Who holds an open item, one of the summary's lines (spec 091, finer in spec 094)"""

    MAINTAINER = "maintainer"
    AGENT = "agent"
    ATTENTION = "attention"
    PEOPLE = "people"
    ELSEWHERE = "elsewhere"
    POSTPONED = "postponed"
    NOBODY = "nobody"


# S-094-4: a condition's holder from its who, unless the condition names another
WHO_HOLDER = {
    Who.MAINTAINER: Holder.MAINTAINER,
    Who.AGENT: Holder.AGENT,
    Who.PERSON: Holder.PEOPLE,
    Who.EVENT: Holder.NOBODY,
}


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
    return pull_detail(json.loads(text))


def pull_detail(raw: dict[str, Any]) -> PullDetail:
    checks = []
    for c in raw.get("statusCheckRollup") or ():
        if c.get("__typename") == "StatusContext":
            checks.append(Check(str(c["context"]), str(c["state"])))
        else:
            status, conclusion = str(c.get("status") or ""), str(c.get("conclusion") or "")
            checks.append(Check(str(c["name"]), conclusion if status == "COMPLETED" else status or "PENDING"))
    labels = tuple(str(label["name"]) for label in raw.get("labels") or ())
    return PullDetail(tuple(checks), str(raw.get("reviewDecision") or ""), labels)


def read_pull_details(repo: str, run: StateRunner) -> dict[int, PullDetail]:
    """S-094-10: every open pull request's checks, review decision, and labels in one read"""
    fields = "number,statusCheckRollup,reviewDecision,labels"
    cmd = ["gh", "pr", "list", "-R", repo, "--json", fields, "-L", "1000"]
    return {int(p["number"]): pull_detail(p) for p in json.loads(gh_read(cmd, run, "gh pr list (checks and reviews)"))}


def read_pull_detail(repo: str, number: int, run: StateRunner) -> PullDetail:
    fields = "statusCheckRollup,reviewDecision,labels"
    cmd = ["gh", "pr", "view", str(number), "-R", repo, "--json", fields]
    return parse_pull_detail(gh_read(cmd, run, f"gh pr view {number}"))


@dataclass(frozen=True, slots=True)
class Condition:
    reason: str
    who: Who
    clears: str
    held: bool = False  # spec 091: the gate's record holds it (GATE_RETRY, GATE_IDLE, GATE_PAUSED)
    where: Holder | None = None  # S-094-4: a holder other than its who's

    @property
    def holder(self) -> Holder:
        """S-094-4: attention when the gate's record holds it, else where, else its who's"""
        if self.held:
            return Holder.ATTENTION
        return self.where if self.where is not None else WHO_HOLDER[self.who]

    def record(self) -> dict[str, str]:
        return {"reason": self.reason, "who": self.who.value, "clears": self.clears, "holder": self.holder.value}


@dataclass(frozen=True, slots=True)
class Explanation:
    repo: str
    number: int
    kind: Kind
    bucket: str
    conditions: tuple[Condition, ...]
    links: Links | None = None  # #1473: step, blocks, and closes, when read

    @property
    def url(self) -> str:
        return f"{github(self.repo)}/{'pull' if self.kind is Kind.PULL else 'issues'}/{self.number}"

    def text(self) -> str:
        lines = [f"{self.repo}#{self.number} ({self.url}): {self.bucket}"]
        for c in self.conditions:
            lines += [f"  why:  {c.reason}", f"        clears: {c.who.text} ({c.clears})"]
        if self.links is not None:
            lines += self.links.lines()
        return "\n".join(lines) + "\n"

    def record(self) -> dict[str, object]:
        return {
            "repo": self.repo,
            "number": self.number,
            "kind": self.kind.value,
            "url": self.url,
            "bucket": self.bucket,
            "conditions": [c.record() for c in self.conditions],
            **({} if self.links is None else self.links.record()),
        }


# S-088-8: what a triaged issue's verdict waits on, and who clears it; an opportunity here is an
# opportunity issue itself (Issue.proposal), and a request handed to intake waits as below (#1643)
VERDICT_WAITS: dict[str, tuple[str, Who, str]] = {
    "opportunity": (
        "waits on the maintainer to accept or decline it",
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
# S-094-4: the verdicts whose holder is not their who's
VERDICT_HOLDER = {"postponed": Holder.POSTPONED, "upstream": Holder.ELSEWHERE}
CHILDREN = "children "  # triage_state.py's note of a parent starts with its children's progress
# #1611: an opportunity the maintainer accepted (labelled planned) is the spec gate's, not the maintainer's
ACCEPTED_WAITS = Condition(
    "triaged as opportunity and accepted: waits on triage's spec gate to give it a feature verdict",
    Who.AGENT,
    "triage's spec gate gives it a feature verdict and opens its spec",
)
# #1707: a goal plan the maintainer accepted, with items still to file, is product intake's
PLAN_ACCEPTED_WAITS = Condition(
    "triaged as plan and accepted: waits on product intake to file its items",
    Who.AGENT,
    "a product intake pass files its items",
)
PLANS = "PLANS"  # watch_state.py's row `PLAN_DUE G-1; PLAN_ACCEPTED #N ...`, from intake_state.py --plans
PLAN_ACCEPTED = "PLAN_ACCEPTED "
SPEC_DUE = "SPEC_DUE"  # watch_state.py's row `ACCEPTED #N ...`: intake_state.py's ACCEPTED opportunities (spec 074)
# #1643: a request triaged as an opportunity that no open opportunity issue names yet is product
# intake's to group, not the maintainer's to accept
INTAKE_WAITS = Condition(
    "triaged as opportunity: waits for product intake to group it", Who.AGENT, "a product intake pass groups it"
)


def accepts(issue: Issue) -> str | None:
    """S-094-6: the verdict the maintainer accepts or declines on the issue: a plan, or an
    opportunity issue itself (labelled opportunity or goal-plan, #1643); None for any other"""
    if issue.state != "TRIAGED" or issue.verdict not in ("opportunity", "plan"):
        return None
    return issue.verdict if issue.verdict == "plan" or issue.proposal else None


def grouped_waits(facts: Facts, issue: Issue) -> list[Condition]:
    """#1643: a request an open opportunity issue names waits on that opportunity's answer, an
    event, so it counts once, through the opportunity, and never as the maintainer's itself"""
    return [
        Condition(
            f"triaged as opportunity: grouped into #{n}, which waits on the maintainer's answer",
            Who.EVENT,
            f"#{n} accepted or declined; {facts.command} status --item {n} says what holds it",
        )
        for n in issue.grouped
    ]


def accepted(facts: Facts) -> frozenset[int]:
    """#1611: the opportunities intake_state.py reads ACCEPTED (open, labelled its --accepted-label,
    planned, and not yet handed off), as the watch's SPEC_DUE row names them; no read of its own"""
    return frozenset(int(n) for r in facts.rows if r.state == SPEC_DUE for n in OWN_NUMBER.findall(r.detail))


def plans_accepted(facts: Facts) -> frozenset[int]:
    """#1707: the plans intake_state.py reads PLAN_ACCEPTED (accepted, items still to file), as
    the watch's PLANS row names them in its PLAN_ACCEPTED part; no read of its own"""
    return frozenset(
        int(n)
        for r in facts.rows
        if r.state == PLANS
        for part in r.detail.split("; ")
        if part.startswith(PLAN_ACCEPTED)
        for n in OWN_NUMBER.findall(part)
    )


def not_open(ref: Ref, repo: str) -> ReleaseError:
    return ReleaseError(f"--item {ref.given!r}: #{ref.number} is no open issue or pull request of {repo}")


GONE = re.compile(r"\(HTTP 404\)|\(HTTP 410\)")  # gh api's error for a number with no item, or a deleted one


def is_open(repo: str, number: int, run: StateRunner) -> bool:
    """#1469: whether GitHub has an open issue or pull request numbered number, from its own
    state (the issues endpoint answers for both), read before anything else so a closed or
    missing item is answered at once; False for closed or none, refused for any other answer"""
    cmd = ["gh", "api", f"repos/{repo}/issues/{number}", "--jq", ".state"]
    first = run(cmd)
    if first.returncode != 0 and GONE.search(first.stderr):
        return False
    state = (first.stdout if first.returncode == 0 else gh_read(cmd, run, f"gh api {cmd[2]}")).strip()
    if state not in ("open", "closed"):
        raise ReleaseError(f"gh api {cmd[2]} printed the state {state!r}, neither open nor closed")
    return state == "open"


def _find(facts: Facts, ref: Ref) -> tuple[Kind, Issue | None, Pull | None]:
    issue = next(
        (i for i in facts.issues if i.number == ref.number and i.state not in CLOSED_STATES and not i.closed), None
    )
    pull = next((p for p in facts.pulls if p.number == ref.number), None)
    kind = Kind.ISSUE if issue is not None else Kind.PULL if pull is not None else None
    if kind is None:
        raise not_open(ref, facts.repo)
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
    held = parked(facts.rows)
    if any(n == number for n, _ in (*held.people, *held.waits)):
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
    wrote nothing on it waits for a change (GATE_IDLE); one whose session ended error waits for
    its backoff (GATE_RETRY), and while the sessions' credential is paused the gate takes up
    nothing (GATE_PAUSED), each said instead of "the gate takes it up on a coming tick" (S-089-13)"""
    if facts.gate.agents is None or any(r.state == "HOLD" for r in facts.rows):
        return []
    retry = [r for r in facts.rows if r.state == GATE_RETRY and names(r, number)]
    if retry:
        return [Condition(f"the gate hands it again {retry[0].detail}", Who.AGENT, "the backoff's end", held=True)]
    idle = [r for r in facts.rows if r.state == GATE_IDLE and names(r, number)]
    if idle:
        return [
            Condition(
                "the gate handed it to a session that wrote nothing on it; it waits for a change",
                Who.EVENT,
                "a new comment, push, or label on it",
                held=True,
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
    paused = next((r for r in facts.rows if r.state == GATE_PAUSED), None)
    if paused is not None:  # spec 089: the credential's pause holds every launch, spec 095: the host's
        cause = PAUSE_CAUSES.get(paused.subject, "a refused credential")
        until = paused.detail.partition(": ")[0]  # `until <when>`, its time holding no ": "
        if paused.subject in ("limit", "github_limit"):
            who, clears = Who.EVENT, "the limit's reset"
        elif paused.subject == "disk":
            who, clears = Who.MAINTAINER, paused.fix or "free disk space"
        else:
            who, clears = Who.MAINTAINER, paused.fix or "a new token"
        return [Condition(f"the gate starts no session {until}, paused by {cause}", who, clears, held=True)]
    return [Condition("the gate takes it up on a coming tick, in its tier order", Who.AGENT, "the next gate tick")]


WAIT = re.compile(r"(?P<ref>[\w.-]+/[\w.-]+#\d+):(?P<state>\w+)")
WINDOW = re.compile(r"veto window of (?P<pr>#\d+) until (?P<until>\S+)")


def assigned_to_maintainer(facts: Facts, issue: Issue) -> bool:
    """S-094-4: one of the issue's assignees or teams fills spec 036's maintainer role, compared
    case-blind as the role's logins and teams are"""
    mine = {f.key for f in facts.maintainer}
    return any(who.lower() in mine for who in (*issue.assignees, *issue.teams))


def issue_conditions(facts: Facts, issue: Issue) -> list[Condition]:
    """S-088-6, S-088-8: the issue's triage_state.py state and its note"""
    state, note = issue.state, issue.note
    if state == "NEEDS_DECISION":
        return [
            Condition("waits on the answer to its needs-decision question", Who.MAINTAINER, "answer the question on it")
        ]
    if state == "BLOCKED":
        own = Holder.POSTPONED if note.startswith(CHILDREN) else None  # S-094-4: a plan moving through its children
        found = [
            Condition(
                f"waits on {w['ref']} ({w['state'].lower()})",
                Who.EVENT,
                f"{w['ref']} closing or merging",
                where=own
                or (None if w["ref"].rpartition("#")[0].casefold() == facts.repo.casefold() else Holder.ELSEWHERE),
            )
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
                    where=own,
                )
            )
        if note == "labelled blocked":
            found.append(
                Condition(
                    "labelled blocked",
                    Who.MAINTAINER,
                    f"gh issue edit {issue.number} -R {facts.repo} --remove-label blocked once it can go on",
                    where=Holder.ELSEWHERE,  # S-094-4: it waits on an outside event, which the label marks
                )
            )
        return found or [Condition("blocked", Who.EVENT, "the items it waits on closing or merging", where=own)]
    if state == "POSTPONED":
        paths = note.removeprefix("waits on ") if note.startswith("waits on ") else None
        when = "a stable release that changes " + paths if paths else "the next stable release, when triage revisits it"
        return [Condition("postponed", Who.EVENT, when, where=Holder.POSTPONED)]
    if state == "WITH_PERSON":
        people = " ".join([*(f"@{p}" for p in issue.assignees), *issue.teams])
        if assigned_to_maintainer(facts, issue):  # S-094-4: it waits on them, whoever else it waits on
            return [
                Condition(
                    f"assigned to you: a person's item: waits on {people}",
                    Who.MAINTAINER,
                    "do the step and close it, with its other assignees",
                )
            ]
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
        return [
            Condition(
                "an upstream report: waits on the repo that owns the fault",
                Who.EVENT,
                "that repo's fix",
                where=Holder.ELSEWHERE,
            )
        ]
    if state == "UPSTREAM_UNOWNED":  # #1487: nobody linked it to an issue in another repo or took it
        return [
            Condition(
                "an upstream report nobody linked or took: waits for you to report it where it belongs",
                Who.MAINTAINER,
                "a Depends on line naming the issue in the owning repo, or an assignee",
            )
        ]
    if state == "TRIAGED":
        if issue.verdict is None:
            return [
                Condition(
                    "triaged with nothing pending", Who.EVENT, "a new comment or label that moves it back to triage"
                )
            ]
        if issue.verdict == "opportunity" and issue.number in accepted(facts):
            return [ACCEPTED_WAITS]
        if issue.verdict == "plan" and issue.number in plans_accepted(facts):
            return [PLAN_ACCEPTED_WAITS]
        if issue.verdict == "opportunity" and not issue.proposal:  # #1643: a request handed to intake
            return grouped_waits(facts, issue) or [INTAKE_WAITS]
        reason, who, clears = VERDICT_WAITS[issue.verdict]
        return [
            Condition(f"triaged as {issue.verdict}: {reason}", who, clears, where=VERDICT_HOLDER.get(issue.verdict))
        ]
    return []


def pull_waits(facts: Facts, number: int) -> tuple[str, ...]:
    """S-041-22: the items still open that the pull request's Depends on lines name, as
    watch_state.py's PRS_PARKED row lists them (WAITS_ON), owner/name#N"""
    return next((on for n, on in parked(facts.rows).waits if n == number), ())


def pull_holds(facts: Facts) -> Holds:
    """S-041-22: the repo's pull requests held by their Depends on lines, each with the items
    it waits on, as the BLOCKED issues' holds are read (local_holds), so what waits on an item
    names them too"""
    found: Holds = {}
    for p in facts.pulls:
        on = pull_waits(facts, p.number)
        if on:
            ref = ItemRef(facts.repo, p.number)
            found[ref.key] = (ref, "BLOCKED", tuple(ItemRef.parse(r) for r in on))
    return found


def pull_conditions(facts: Facts, pull: Pull, detail: PullDetail, window: LandWindow | None) -> list[Condition]:
    """S-088-10: what holds the pull request's merge"""
    found = [
        Condition(  # S-041-22: as a BLOCKED issue's hold, held elsewhere for another repo's item
            f"waits on {ref} (open)",
            Who.EVENT,
            f"{ref} closing or merging",
            where=None if ref.rpartition("#")[0].casefold() == facts.repo.casefold() else Holder.ELSEWHERE,
        )
        for ref in pull_waits(facts, pull.number)
    ]
    if pull.draft:
        if any(r.state == "AGENT_DRAFT" and names(r, pull.number) for r in facts.rows):
            found.append(
                Condition(
                    "the App's own draft: no session owns it any more (D-67)",
                    Who.AGENT,
                    "a gate session marks it ready once nothing it waits on is open",
                )
            )
        else:
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
    land = _level(facts, StageKind.LAND)
    proposes = facts.gate.agents is not None and land.effective is Autonomy.PROPOSE and land.source is not Source.HOLD
    if proposes and pull.number in to_land(facts.rows) and pull.number not in to_merge(facts):
        found.append(  # S-088-5: land at propose, land's default (D-51), merges only by the maintainer
            Condition(
                "[autonomy] land is propose: a session reviews it and labels it shipmill-ready, then you merge it",
                Who.MAINTAINER,
                'merge it once it is labelled shipmill-ready, or set land = "act" in [autonomy]',
            )
        )
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
    reach: Reach | None = None,
) -> Explanation:
    """S-088-1 to S-088-11: the item's bucket and conditions; every open item names one (S-088-4);
    with reach, S-088-13 to S-088-16: its step, what waits on it, and what its pull requests close"""
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
    links = None if reach is None else _links(facts, ItemRef(facts.repo, ref.number), reach)
    return Explanation(facts.repo, ref.number, kind, shown, tuple(dict.fromkeys(conditions)), links)


def _links(facts: Facts, item: ItemRef, reach: Reach) -> Links:
    """S-088-14: the walk's waiters and this repo's BLOCKED notes together, each of this repo
    with the picture's bucket"""
    opened = {i.number for i in facts.issues if i.state not in CLOSED_STATES and not i.closed}
    notes = [(i.number, i.state, i.note) for i in facts.issues if i.number in opened]
    pulls = pull_holds(facts)
    holds = merged(reach.chain or {}, local_holds(facts.repo, notes), pulls)

    def local(number: int) -> str | None:
        if number in opened:
            return bucket(facts, number, Kind.ISSUE)
        return bucket(facts, number, Kind.PULL) if (facts.repo.casefold(), number) in pulls else None

    blocks = () if reach.chain_error is not None else waiters(item, holds, local)
    return Links(item, reach.read.step, blocks, reach.chain_error, reach.read.closes)
