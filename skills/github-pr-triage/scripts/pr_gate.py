#!/usr/bin/env python3
"""Merge gate: is each PR open, mergeable, and green on every CI check that has finished?
And does it keep to the repo's direction (spec 024)?

- An agent's PR (authored by --bot-login, or every PR named with --agent) carries a
  `## Plan` section with `Serves:`, `Files:`, `Order:`, and `Proof:` lines, and its
  `Serves:` names goal ids docs/product.md lists, `quality bar`, or quality-bar ids it
  lists, alone (`Q-6`) or as `quality bar (Q-4, Q-6)`; without a
  docs/product.md the plan isn't checked. A person's PR is never refused for its plan
- A PR whose files match a REVIEW.md Protected areas glob, or that edits docs/product.md
  or docs/product/, waits on the maintainer (needs-decision) until their answer on GitHub
  accepts it (below), or --maintainer-accepted says they accepted it

The maintainer's answer (spec 055), read only for a PR that would read NEEDS_DECISION: the
newest needs-decision question (its first line `<!-- shipmill:needs-decision -->`, by an
OWNER, MEMBER, or COLLABORATOR or the --bot-login) on the PR, or, when the PR has none, on an
issue its title or body closes or names as `Part of #N`; its first answer as retro.py reads one
(a trusted person's reply without the agent marker, or the --bot-login's relay whose first line
is `Decision by @<login>` naming the maintainer: a user `[agents.roles] maintainer` lists on that
branch, or, when it lists none, a login whose permission on the repo is admin, one read of
`repos/<o>/<r>/collaborators/<login>/permission` made only for a relay; one that can't be read is
no maintainer); that answer taking the option marked (recommended) as it stands. It
lifts the asks, and CI decides, when it covers the judged head: one given on an issue before the
PR opened covers every head; any other covers the head the PR had when it was given (after a
force-push since, the first push's beforeCommit; else the newest commit whose committedDate is
at or before it) and every head whose own change, `git diff $(git merge-base origin/<base>
<head>) <head>`, is the same, or, for a PR adding a spec, whose spec files `specs.py
same-approval` reads the same (exit 0) and whose other files' patch is the same. Otherwise
the asks stay, with `  needs-decision:
answered at <sha7>, and the change differs since`, `  needs-decision: the answer doesn't take
the recommended option`, or `  needs-decision: the head the answer was given at can't be named`.
It costs one GraphQL read of the PR's newest 100 comments and force-pushes, and one of the
issues' when the PR has no question; a never zone stays MAINTAINER_ONLY whatever the answer.

REVIEW.md and docs/product.md are read from the default branch of the checkout
(--checkout, default the current directory, at origin/HEAD, or at origin/<the PR's base
branch> when origin/HEAD isn't set), never from the PR. Outside a git checkout, or when
that branch holds neither file, the gate judges CI alone, as it did before spec 024. A
glob matches as decisions.py's scopes do: fnmatch, where `*` also matches `/`, or the path
sits under it (`skills/**`, `docs/product`), relative to the repo's root, and for a
subdirectory's REVIEW.md relative to its folder too.

A downstream check (spec 032), `downstream: <name>`, is a CheckRun in the rollup read like any
check, with no logic of its own: FAILURE, TIMED_OUT, or ACTION_REQUIRED fails, IN_PROGRESS is
pending, and a report-only one's NEUTRAL counts green.

The decision policy (spec 030): when that branch's .github/shipmill.toml has an [agents]
table, the zones come from `shipmill --repo <checkout> decide classify --pr N --ref <the
branch> --json`, run as `uvx shipmill==<the version in the plugin's plugin.json>` (or `uvx
--from <tool> shipmill` with --tool), in place of the direction and Protected areas checks
above; the plan check stays. Each zone by its level, read from that branch, never the PR:

- never: MAINTAINER_ONLY, `  maintainer-only: <zone>: <reason>`; --maintainer-accepted
  doesn't lift it, since only the maintainer merges it, by hand (D-48)
- ask: NEEDS_DECISION, `  needs-decision: <zone>: <reason>`, until the maintainer's answer
  or --maintainer-accepted
- notify: the verdict stays, with `  notify: <zone>: <reason>`; the skill posts the decided
  comment before it merges
- act: nothing

Without [agents] on that branch the gate judges as it did before spec 030.

A spec pull request (spec 053), one that adds a file docs/specs/NNN-<slug>.md (the files API's
`status: added`; an edit, a rename, or a copy is not checked), names its feature issue: a line
of its body, outside a code fence, starting `Spec for #N` (after an optional list bullet;
`owner/repo#N` of the same repo reads the same) whose N is an open issue of the repo, not a pull
request. Without one it is REFUSED, `  spec: names no feature issue: ...`, whoever opened it,
and --maintainer-accepted doesn't lift it. The check reads the files API, and GitHub's GraphQL
once for the issues the lines name; a PR that gh pr view lists whole, with no spec path, reads
neither.

A draft PR is read as DRAFT, whatever its checks, plan, or zones, and the gate reads neither its
files nor its zones (D-67). A person's draft belongs to them: it enters triage once marked ready.
A draft the --bot-login authored has no owner once its session ended (#914): its line says so, and
a gate session marks it ready once nothing it waits on is open, then runs the gate again.

The base branch (D-75): the gate reads the checks on its head commit, one read of the commit's
statuses (which names the commit) and one of its check runs, once per base branch and pass, and
keeps the newest run per check as it does the PR's own (#962). A completed check there that failed
(not one queued or running, nor a cancelled, skipped, neutral, or stale one) makes the verdict
FAILED, `  base: red: <check> failed on <base>@<sha>`, save for the PR whose body has a line
`Repairs: <URL>` naming it (after an optional list bullet, outside a fence): a workflow run's URL
names its every job, a job's or a check run's URL that one, a commit status's exact target URL that
status. A named failure prints `  base: repairs: ...` for the reviewer to check the claim. A
failure outside the code clears by re-running the failed run on the default branch.

Closing keywords (D-76, D-79): a merge never closes an issue its PR is only part of, or one whose
check has not run. A commit's (gh pr view's) closing keyword counts as GitHub closes by it (#988):
any of close, closes, closed, fix, fixes, fixed, resolve, resolves, resolved as a whole word, in any
case, an optional colon, whitespace, then #N, or owner/repo#N or an issue's URL
https://github.com/owner/repo/issues/N naming the PR's own repo (#993; a /pull/N URL names
nothing), anywhere in its message, mid-line, in backticks, and in a fence too. The title and the body are read by
triage_state.py's keyword_closes, the rule shipped.py reads too (#416): in the body, a keyword
starting a line, after an optional list bullet, outside a fence; in the title, one anywhere outside
a code span; one mid-line in the body, in backticks, or naming owner/repo#N names nothing there. The
title is the squash commit's subject (D-33), so it reads as a commit (#987). Whoever opened it, it
is REFUSED, `  refused: <the title or commit <sha7>> closes #N, which the body lists as Part of #N`,
when the title's or a commit's keyword names an issue its body lists as `Part of #N`, and `  refused:
<the title, commit <sha7>, or the body> closes #N, an open issue with a ## Check: write Part of #N
instead` when one names an open issue of the repo whose body has a `## Check` section. The issues
are read in one GraphQL query, only when a keyword names one, or a commit names owner/repo#N or a URL.

The land window (spec 056): when the base's .github/shipmill.toml has [land.window], the gate
reads it with `shipmill --repo <checkout> window --json --ref <the base>`, run as `decide
classify` is, once per base branch and pass for every open PR there, and the labels of a PR
that would read READY with one `gh pr view N --json labels`; a PR into another branch than
the one the config was read from is not held (one window per repo, for PRs into the default
branch). A PR carrying one of its `labels` and none
of its `bypass_labels` that would otherwise read READY reads QUEUED: while the window is closed,
`  queued: held by the land window (<its held labels>); opens <YYYY-MM-DD HH:MM> <timezone>`,
and while it is open and `next_merge` is later than now, `  queued: spacing: the next held merge
after <HH:MM> <timezone>`. A red, pending, conflicting, refused, or held-for-a-decision PR keeps
that verdict: QUEUED only takes READY's place.

Exit codes: 0 every PR is ready; 1 a check failed, on the PR's head or the base's (D-75),
or gh failed; 3 a check is still pending (or --wait timed out); 4 a PR is not open or
conflicts; 5 a PR needs the maintainer's decision; 6 an agent's PR is refused for its plan, a
spec PR names no open feature issue, or a PR's closing keyword names a Part of issue or an open
one with a ## Check (D-76); 7 a PR only the maintainer
merges, by hand (a `never` zone); 8 a draft PR (D-67); 10 a held PR waits for the land window
or its spacing (spec 056); 2 bad arguments,
a base branch the checkout lacks, a git failure, a REVIEW.md, docs/product.md, or config the
gate can't read, or a `shipmill decide classify` or `shipmill window` that fails or prints what
the gate can't read. With several PRs the exit code is
the worst verdict's, ranked 0, 1, 3, 10, 4, 8, 5, 7, 6.

--wait polls while the worst verdict is PENDING, or is NEEDS_DECISION and a NEEDS_DECISION PR has
a check still pending on its own head (#1028): the question waits until its CI finished, and the
exit code and its ranking stay as above. The base's checks are never pending (D-75), a PR with no
checks has none pending, and every other verdict, QUEUED too, stops the wait.
"""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

GREEN = {"SUCCESS", "NEUTRAL", "SKIPPED"}
READY, FAILED, PENDING, BLOCKED, NEEDS_DECISION, REFUSED, MAINTAINER_ONLY, DRAFT = 0, 1, 3, 4, 5, 6, 7, 8
QUEUED = 10  # a held PR outside the land window or inside its spacing (spec 056)
LABELS = {
    READY: "READY",
    FAILED: "FAILED",
    PENDING: "PENDING",
    QUEUED: "QUEUED",
    BLOCKED: "BLOCKED",
    NEEDS_DECISION: "NEEDS_DECISION",
    REFUSED: "REFUSED",
    MAINTAINER_ONLY: "MAINTAINER_ONLY",
    DRAFT: "DRAFT",
}
# the worst verdict last: MAINTAINER_ONLY ranks above NEEDS_DECISION and below REFUSED (spec 030); DRAFT
# ranks above BLOCKED and below the verdicts that ask something of the maintainer (D-52, kept by D-67);
# QUEUED ranks between PENDING and BLOCKED (spec 056)
RANK = (READY, FAILED, PENDING, QUEUED, BLOCKED, DRAFT, NEEDS_DECISION, MAINTAINER_ONLY, REFUSED)

# github-ship-watch's watch_state.py: one reading of the config's [agents] and of the plugin's
# pinned CLI for every skill script
WATCH_STATE = Path(__file__).resolve().parents[2] / "github-ship-watch" / "scripts" / "watch_state.py"
# github-issue-triage's decisions.py: the zone table's one copy, its ZONES and LEVELS
DECISIONS = Path(__file__).resolve().parents[2] / "github-issue-triage" / "scripts" / "decisions.py"
# github-issue-triage's triage_state.py: the closing-keyword rule and the ## Check section, one
# reading for every script (#416, D-76)
TRIAGE_STATE = Path(__file__).resolve().parents[2] / "github-issue-triage" / "scripts" / "triage_state.py"
# github-ship-watch's retro.py: the needs-decision question, its first trusted answer, and whether
# that answer takes the (recommended) option (S-030-18), one reading for every script (spec 055)
RETRO = Path(__file__).resolve().parents[2] / "github-ship-watch" / "scripts" / "retro.py"
# github-issue-triage's specs.py: same-approval compares a spec PR's answered and judged heads (D-81)
SPECS = Path(__file__).resolve().parents[2] / "github-issue-triage" / "scripts" / "specs.py"
# a body's "Part of #N", as triage_state.py's closes() reads a partial PR
PART_OF = re.compile(r"\bpart of:?\s+#([0-9]+)\b", re.IGNORECASE)
CONFIG = ".github/shipmill.toml"

DIRECTION = "docs/product.md"
DIRECTION_DIR = "docs/product/"
REVIEW = "REVIEW.md"
PROTECTED = "Protected areas"
LIST_SECTIONS = {"Users": "U", "Goals": "G", "Non-goals": "N", "Quality bar": "Q"}
DIRECTION_SECTIONS = ("Mission", *LIST_SECTIONS)
PLAN_FIELDS = ("Serves", "Files", "Order", "Proof")
QUALITY_BAR = "quality bar"

_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_ITEM = re.compile(r"^- ([A-Za-z]+)-([1-9][0-9]*): \S.*$")
_MEASURE = re.compile(r"^  measure: \S.*$")  # a goal's measure line (spec 027)
_MOVED = re.compile(r"^See \[([^\]]+)\]\(product/([A-Za-z0-9][A-Za-z0-9_-]*\.md)\)\.$")
_PROTECTED_ITEM = re.compile(r"- `([^`]*)`: (\S.*)")
_PLAN_FIELD = re.compile(r"^\s*(?:[-*]\s+)?(" + "|".join(PLAN_FIELDS) + r"):(.*)$")
_GOAL = re.compile(r"G-[1-9][0-9]*")
_QUALITY = re.compile(r"Q-[1-9][0-9]*")
# `quality bar (Q-4, Q-6)` in a `Serves:` line, read before the line is split on commas (#1016)
_QUALITY_IDS = re.compile(r"quality bar \(([^()]*)\)")
# a check's startedAt: seconds, an optional fraction, and a zone, Z or an offset (#962)
TIMESTAMP = re.compile(
    r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]+))?(Z|[+-][0-9]{2}:[0-9]{2})"
)
# a spec file, named as specs.py's NAME names one, under docs/specs/ (spec 053)
SPEC_FILE = re.compile(r"docs/specs/[0-9]{3,}-[a-z0-9]+(?:-[a-z0-9]+)*\.md")
# a body line naming the issue a spec pull request specifies: #N, or owner/repo#N
_SPEC_FOR = re.compile(r"^\s*(?:[-*]\s+)?Spec for\s+([\w.-]+/[\w.-]+)?#([0-9]+)\b")
NO_ISSUE = 'names no feature issue: add "Spec for #N" for the open issue it specifies'
GRAPHQL_INT = 2**31 - 1  # an issue number past it is no issue, and GraphQL refuses the query
# a base check that finished so is not red: the PR's green, and a run cancelled or gone stale (D-75)
NOT_RED = GREEN | {"CANCELLED", "STALE"}
# a body line naming the failed base run the PR repairs, and the ids an Actions or check run URL names
_REPAIRS = re.compile(r"^\s*(?:[-*]\s+)?Repairs:\s*(\S+)")
_ACTIONS_URL = re.compile(r"https://[^/]+/[^/]+/[^/]+/actions/runs/([0-9]+)(?:/job/([0-9]+)|/attempts/[0-9]+)?/?")
_CHECK_RUN_URL = re.compile(r"https://[^/]+/[^/]+/[^/]+/runs/([0-9]+)/?")


class GateError(Exception):
    """A state the gate can't judge: it stops with exit 2 and the message"""


@dataclass(frozen=True)
class Check:
    name: str
    done: bool
    conclusion: str
    # a pending check's own word, its pending line's suffix (#1014): queued, running since HH:MM
    # UTC, or a status context's pending; a queued check waits, it isn't stalled
    waits: str = ""


@dataclass(frozen=True)
class Gate:
    number: int
    state: str
    mergeable: str
    base: str
    head: str  # the full headRefOid it judged, the verdict line's head= for --match-head-commit (#1017)
    checks: tuple[Check, ...]
    refused: tuple[str, ...] = ()  # why an agent's PR is refused for its plan, or any PR for its closers (D-76)
    asks: tuple[str, ...] = ()  # why the PR waits on the maintainer
    never: tuple[str, ...] = ()  # the never zones: only the maintainer merges it, by hand (spec 030)
    notices: tuple[str, ...] = ()  # the notify zones: decided without waiting, the verdict kept
    draft: bool = False  # a person's is theirs until marked ready (D-67)
    spec: tuple[str, ...] = ()  # why a spec PR is refused: it names no open feature issue (spec 053)
    own: bool = False  # a draft the --bot-login authored: a gate session marks it ready (D-67, #914)
    base_red: tuple[str, ...] = ()  # the base head's failed checks no Repairs: line names (D-75)
    base_repairs: tuple[str, ...] = ()  # the ones a Repairs: line names, for the reviewer to check
    queued: tuple[str, ...] = ()  # why a held PR waits for the land window or its spacing (spec 056)

    @property
    def verdict(self) -> int:
        if self.state != "OPEN":
            return BLOCKED
        if self.draft:
            return DRAFT
        if self.mergeable == "CONFLICTING":
            return BLOCKED
        if self.refused or self.spec:
            return REFUSED
        if self.never:
            return MAINTAINER_ONLY
        if self.asks:
            return NEEDS_DECISION
        if self.base_red or any(c.done and c.conclusion not in GREEN for c in self.checks):
            return FAILED
        if not self.checks or any(not c.done for c in self.checks) or self.mergeable != "MERGEABLE":
            return PENDING
        if self.queued:  # QUEUED only takes READY's place (spec 056)
            return QUEUED
        return READY


@dataclass(frozen=True)
class Protected:
    glob: str
    why: str
    file: str  # the REVIEW.md that lists it

    def covers(self, path: str) -> bool:
        """The glob from the repo's root, or, in a subdirectory's REVIEW.md, from its folder
        too (`shipmill review protect --dir` writes it so); matching more is the safe side"""
        folder = self.file[: -len(REVIEW)]
        inner = path[len(folder) :] if folder and path.startswith(folder) else None
        return matches(self.glob, path) or (inner is not None and matches(self.glob, inner))


@dataclass(frozen=True)
class Base:
    """What the default branch holds: the direction's ids (None without docs/product.md),
    every REVIEW.md, read for the files a PR changes, and whether its config has [agents]
    (spec 030: then `shipmill decide classify` at ref names the zones)"""

    ids: frozenset[str] | None
    reviews: dict[str, str]  # REVIEW.md path -> its text
    agents: bool = False
    ref: str | None = None  # the ref it was read at
    # the users [agents.roles] maintainer lists, lowercased; none: a login with admin on the repo is
    # the maintainer (a relayed answer counts only when it names one, spec 055)
    maintainers: frozenset[str] = frozenset()
    window: bool = False  # the config has [land.window]: `shipmill window` reads it (spec 056)

    def protected(self, files: tuple[str, ...]) -> list[Protected]:
        wanted = {REVIEW}
        for path in files:
            parts = path.split("/")[:-1]
            wanted.update("/".join(parts[: i + 1]) + "/" + REVIEW for i in range(len(parts)))
        found: list[Protected] = []
        for name in sorted((n for n in self.reviews if n in wanted), key=lambda n: (n.count("/"), n)):
            found.extend(protected_areas(self.reviews[name], name))
        return found


def check_of(entry: dict) -> Check:
    """A CheckRun (status, conclusion) or a StatusContext (state)"""
    if "state" in entry and "status" not in entry:
        state = str(entry["state"])
        pending = state == "PENDING"
        return Check(str(entry.get("context", "?")), not pending, state, "pending" if pending else "")
    status = str(entry.get("status", ""))
    done = status == "COMPLETED"
    return Check(str(entry.get("name", "?")), done, str(entry.get("conclusion") or ""), "" if done else waits_of(entry))


def waits_of(entry: dict) -> str:
    """What a CheckRun not completed does, from its own status and startedAt: running since
    its start, else its status (queued, waiting, ...) lowercased"""
    status = str(entry.get("status", ""))
    if status != "IN_PROGRESS":
        return status.lower() or "pending"
    started = started_of(entry)
    if started is None:
        return "running"
    return f"running since {started.astimezone(timezone.utc).strftime('%H:%M UTC')}"  # noqa: UP017 (3.10)


def started_of(entry: dict) -> datetime | None:
    """When the entry started, as gh gives it for both shapes (a StatusContext's createdAt);
    None when it hasn't (missing, or gh's zero time for a queued run)"""
    raw = entry.get("startedAt")
    if raw is None or raw == "":
        return None
    started = moment(raw, "a check's startedAt")
    return None if started.year == 1 else started


def moment(raw: object, what: str) -> datetime:
    """A GitHub timestamp, with its zone; anything else stops the gate"""
    found = TIMESTAMP.fullmatch(raw) if isinstance(raw, str) else None
    if found is None:
        raise GateError(f"{what} is not a timestamp: {raw!r}")
    seconds, fraction, zone = found.groups()
    # Python 3.10's fromisoformat takes neither Z nor a fraction other than 3 or 6 digits
    micro = "." + (fraction + "000000")[:6] if fraction else ""
    try:
        return datetime.fromisoformat(seconds + micro + ("+00:00" if zone == "Z" else zone))
    except ValueError as error:
        raise GateError(f"{what} is not a timestamp: {raw!r}") from error


def newest_checks(rollup: Iterable[dict]) -> tuple[Check, ...]:
    return tuple(check_of(entry) for entry in newest_entries(rollup))


def newest_entries(rollup: Iterable[dict]) -> list[dict]:
    """One check per CheckRun (workflowName, name) or StatusContext context: a head checked
    twice (a PR closed and reopened) lists both runs, and only the newest counts (#962). The
    later start wins; without both starts the later rollup entry does, except that a run
    not started and not done is never replaced by a started one, so a run in flight is
    never hidden behind an older pass wherever the rollup lists it"""
    newest: dict[tuple[str, ...], tuple[datetime | None, dict]] = {}
    for entry in rollup:
        if "state" in entry and "status" not in entry:
            key: tuple[str, ...] = ("status", str(entry.get("context", "?")))
        else:
            key = ("run", str(entry.get("workflowName") or ""), str(entry.get("name", "?")))
        started = started_of(entry)
        kept = newest.get(key)
        if kept is None or started is None:
            newest[key] = (started, entry)
        elif kept[0] is None:
            if check_of(kept[1]).done:
                newest[key] = (started, entry)
        elif started >= kept[0]:
            newest[key] = (started, entry)
    return [entry for _, entry in newest.values()]


def sections(text: str) -> list[tuple[int, str | None, list[tuple[int, str]]]]:
    """Split at level-one and level-two headings outside fenced code, as review.py does; the
    first entry, level 0 and headed None, holds the text before the first heading"""
    found: list[tuple[int, str | None, list[tuple[int, str]]]] = [(0, None, [])]
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        opened = _FENCE.match(line)
        if fence is not None:
            if opened is not None and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence):
                fence = None
        elif opened is not None:
            fence = opened.group(1)
        else:
            heading = _HEADING.match(line)
            if heading is not None and len(heading.group(1)) <= 2:
                found.append((len(heading.group(1)), (heading.group(2) or "").strip(), []))
                continue
        found[-1][2].append((number, line))
    return found


def protected_areas(text: str, file: str) -> list[Protected]:
    """A REVIEW.md's Protected areas items, with review.py's line rule; a line that breaks
    it stops the gate, since a glob it can't read could guard anything"""
    found: list[Protected] = []
    for _, heading, body in sections(text):  # a level-one heading counts too, as in review.py
        if heading != PROTECTED:
            continue
        for number, line in body:
            if not line.strip():
                continue
            item = _PROTECTED_ITEM.fullmatch(line)
            if item is None or not item.group(1) or item.group(1) != item.group(1).strip():
                raise GateError(
                    f"{file}:{number}: a Protected areas item is one line ``- `<glob>`: <why>``; "
                    "fix it on the default branch (`shipmill review check`)"
                )
            found.append(Protected(item.group(1), item.group(2).strip(), file))
    return found


def matches(glob: str, path: str) -> bool:
    """fnmatch, where `*` also matches `/`, or the path sits under the glob's directory"""
    stem = glob.rstrip("*").rstrip("/")
    return path == glob or fnmatch.fnmatchcase(path, glob) or (bool(stem) and path.startswith(stem + "/"))


def direction_ids(read: Callable[[str], str | None]) -> frozenset[str]:
    """Every item id docs/product.md lists, moved sections followed; a list line that isn't
    `- <prefix>-<n>: <text>` with its section's prefix, or a broken link, stops the gate; a
    goal's `  measure: ...` line right under its item line is skipped (spec 027).
    `shipmill product check` holds the full grammar"""
    text = read(DIRECTION)
    if text is None:
        raise GateError(f"no {DIRECTION} on the default branch")
    ids: set[str] = set()
    for level, heading, body in sections(text):
        if level < 2:  # the text before the name, and the name
            continue
        if heading not in DIRECTION_SECTIONS:
            raise GateError(f"{DIRECTION}: `## {heading}` is not a direction heading; run `shipmill product check`")
        prefix = LIST_SECTIONS.get(heading)
        if prefix is None:
            continue
        lines = [(n, line.rstrip()) for n, line in body if line.strip()]
        file, listed = DIRECTION, body
        if len(lines) == 1 and lines[0][1].startswith("See ["):
            moved = _MOVED.match(lines[0][1])
            if moved is None or moved.group(1) != heading:
                raise GateError(f"{DIRECTION}:{lines[0][0]}: a broken `See [...]` line; run `shipmill product check`")
            file = DIRECTION_DIR + moved.group(2)
            linked = read(file)
            if linked is None:
                raise GateError(f"{DIRECTION}:{lines[0][0]}: {file} doesn't exist; run `shipmill product check`")
            parts = sections(linked)
            heads = [(lv, h) for lv, h, _ in parts[1:]]
            if heads != [(2, heading)] or any(line.strip() for _, line in parts[0][2]):
                raise GateError(f"{file} holds only `## {heading}`; run `shipmill product check`")
            listed = parts[1][2]
        after_goal = False  # the line before was a goal's item line, which a measure line may follow
        for number, raw in listed:
            line = raw.rstrip()
            if not line.strip():
                after_goal = False
                continue
            if after_goal and _MEASURE.match(line):  # spec 027: read no more from it
                after_goal = False
                continue
            item = _ITEM.match(line)
            if item is None or item.group(1) != prefix:
                raise GateError(f"{file}:{number}: not a `- {prefix}-<n>: <text>` item; run `shipmill product check`")
            ids.add(f"{prefix}-{item.group(2)}")
            after_goal = prefix == "G"
    return frozenset(ids)


def plan_problems(body: str, ids: frozenset[str]) -> list[str]:
    """Why a PR body's plan doesn't hold: no `## Plan` section, a missing field, or a
    `Serves:` naming something other than listed goal ids, `quality bar`, or listed quality-bar
    ids, alone (`Q-6`) or in `quality bar (Q-4, Q-6)`"""
    plans = [lines for level, heading, lines in sections(body) if level == 2 and heading == "Plan"]
    if not plans:
        return ["no `## Plan` section; an agent's pull request carries its plan (Serves, Files, Order, Proof)"]
    if len(plans) > 1:
        return ["a second `## Plan` section; the body holds one"]
    fields: dict[str, list[str]] = {}
    for _, line in plans[0]:
        field = _PLAN_FIELD.match(line)
        if field is not None:
            fields.setdefault(field.group(1), []).append(field.group(2).strip())
    problems = [f"the plan has no `{name}:` line" for name in PLAN_FIELDS if name not in fields]
    problems += [f"the plan has {len(v)} `{k}:` lines; it holds one" for k, v in fields.items() if len(v) > 1]
    serves = fields.get("Serves", [""])[0]
    if "Serves" in fields and not serves:
        problems.append(f"`Serves:` is empty; it names goal ids from {DIRECTION}, `{QUALITY_BAR}`, or quality-bar ids")
    grouped = [part.strip() for found in _QUALITY_IDS.finditer(serves) for part in found.group(1).split(",")]
    for name in (part.strip() for part in _QUALITY_IDS.sub(QUALITY_BAR, serves).split(",") if serves):
        if name == QUALITY_BAR:
            continue
        if not (_GOAL.fullmatch(name) or _QUALITY.fullmatch(name)):
            problems.append(
                f"`Serves:` names {name!r}; it names goal ids (G-n), `{QUALITY_BAR}`, or quality-bar ids (Q-n)"
            )
        elif name not in ids:
            problems.append(f"`Serves:` names {name}, which {DIRECTION} doesn't list")
    for name in grouped:
        if not _QUALITY.fullmatch(name):
            problems.append(f"`Serves:` names {name!r} in `{QUALITY_BAR} (...)`; it holds quality-bar ids (Q-n)")
        elif name not in ids:
            problems.append(f"`Serves:` names {name}, which {DIRECTION} doesn't list")
    return problems


def unfenced(text: str) -> list[str]:
    """The lines of a body outside fenced code, with sections()' fence rule"""
    found: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        opened = _FENCE.match(line)
        if fence is not None:
            if opened is not None and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence):
                fence = None
        elif opened is not None:
            fence = opened.group(1)
        else:
            found.append(line)
    return found


def spec_refs(body: str) -> list[tuple[str | None, int]]:
    """Each `Spec for` line's issue, in order: its owner/repo (None for a plain #N) and number.
    Only a line that starts with it, after an optional list bullet, outside a fence, names one"""
    found: list[tuple[str | None, int]] = []
    for line in unfenced(body):
        named = _SPEC_FOR.match(line)
        if named is not None:
            found.append((named.group(1), int(named.group(2))))
    return found


def run(cmd: list[str], what: str) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise GateError(f"{what} failed: {proc.stderr.strip()}")
    return proc.stdout


def git(checkout: str, *args: str) -> str:
    return run(["git", "-C", checkout, *args], f"git {args[0]} in {checkout}")


NO_BASE = Base(None, {})  # nothing to read: the gate judges CI alone, as before spec 024


def quiet(checkout: str, *args: str) -> str | None:
    """A git call whose failure is an answer (no such ref, not a checkout): its output or None"""
    proc = subprocess.run(["git", "-C", checkout, *args], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def same_repo(url: str, repo: str) -> bool:
    """Whether origin's URL names -R's [HOST/]OWNER/NAME; GitHub's names ignore case"""
    tail = re.split(r"[:/]", re.sub(r"(\.git)?/*$", "", url.lower()))[-2:]
    return tail == repo.lower().strip("/").split("/")[-2:]


class Bases:
    """The default branch's REVIEW.md files and direction, read once per ref. Outside a git
    checkout, or in a checkout of another repo than -R names, there is nothing to read"""

    def __init__(self, checkout: str | None, repo: str | None) -> None:
        self.checkout = checkout or "."
        self.read: dict[str, Base] = {}
        self.inside = quiet(self.checkout, "rev-parse", "--is-inside-work-tree") == "true"
        if not self.inside and checkout is not None:
            raise GateError(f"--checkout {checkout} is not a git checkout")
        if self.inside and repo:
            url = quiet(self.checkout, "remote", "get-url", "origin") or ""
            if not same_repo(url, repo):
                print(
                    f"note: {self.checkout} is not a checkout of {repo}; REVIEW.md and the direction unread",
                    file=sys.stderr,
                )
                self.inside = False
        self.default = (
            quiet(self.checkout, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") if self.inside else None
        )

    def base(self, base_branch: str) -> Base:
        """origin/HEAD, or the PR's own base branch at origin when origin/HEAD isn't set"""
        if not self.inside:
            return NO_BASE
        ref = self.default or f"origin/{base_branch}"
        if ref not in self.read:
            if quiet(self.checkout, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") is None:
                raise GateError(
                    f"neither origin/HEAD nor {ref} is in {self.checkout}: run `git -C {self.checkout} fetch origin`"
                )
            self.read[ref] = read_base(self.checkout, ref)
        return self.read[ref]


def read_base(checkout: str, ref: str) -> Base:
    names = [n for n in git(checkout, "ls-tree", "-r", "-z", "--name-only", ref).split("\0") if n]
    tree = set(names)

    def read(path: str) -> str | None:
        return git(checkout, "show", f"{ref}:{path}") if path in tree else None

    reviews = {n: git(checkout, "show", f"{ref}:{n}") for n in names if n.rsplit("/", 1)[-1] == REVIEW}
    ids = direction_ids(read) if DIRECTION in tree else None
    config = read(CONFIG)
    where = f"{CONFIG} at {ref}"
    agents = config is not None and has_agents(config, where)
    maintainers = frozenset() if config is None else maintainer_users(config, where)
    window = config is not None and has_land_window(config, where)
    return Base(ids, reviews, agents, ref, maintainers, window)


def has_land_window(text: str, where: str) -> bool:
    """Whether the config has [land.window] (spec 056); `shipmill window` checks the section
    itself. On Python 3.10, without tomllib, a [land.window] header, a window key or dotted key
    under [land], or a land key or dotted key at the top counts: a form it can't read runs
    `shipmill window`, which reads it, rather than letting a held PR through"""
    ws = watch_state()
    if ws.tomllib is None:
        tables = ws.toml_tables(text)
        under = re.search(r"^\s*[\"']?window[\"']?\s*[.=]", tables.get("land", ""), re.MULTILINE)
        top = re.search(r"^\s*[\"']?land[\"']?\s*[.=]", tables.get("", ""), re.MULTILINE)
        headers = any(n == "land.window" or n.startswith("land.window.") for n in tables)
        return headers or under is not None or top is not None
    try:
        raw = ws.tomllib.loads(text)
    except ws.tomllib.TOMLDecodeError as exc:
        raise GateError(f"{where}: {exc}") from None
    land = raw.get("land")
    return isinstance(land, dict) and "window" in land


def maintainer_users(text: str, where: str) -> frozenset[str]:
    """The users `[agents.roles] maintainer` lists, lowercased; a team names none here. A roles
    table the gate can't read stops it, as every reader of the config does (S-036-2); on Python
    3.10, without tomllib, an [agents.roles] table is not read but refused"""
    ws = watch_state()
    if ws.tomllib is None:
        if any(name == "agents.roles" or name.startswith("agents.roles.") for name in ws.toml_tables(text)):
            raise GateError(f"{where}: can't read [agents.roles] on Python 3.10: use 3.11+")
        return frozenset()
    try:
        raw = ws.tomllib.loads(text)
    except ws.tomllib.TOMLDecodeError as exc:
        raise GateError(f"{where}: {exc}") from None
    agents = raw.get("agents")
    roles = agents.get("roles") if isinstance(agents, dict) else None
    fillers = roles.get("maintainer") if isinstance(roles, dict) else None
    if roles is not None and not isinstance(roles, dict):
        raise GateError(f"{where}: [agents.roles] is not a table")
    if fillers is None:
        return frozenset()
    if not isinstance(fillers, list) or not all(isinstance(f, str) for f in fillers):
        raise GateError(f"{where}: [agents.roles] maintainer is not an array of logins and @org/team entries")
    return frozenset(f.lower() for f in fillers if not f.startswith("@"))


class Maintainers:
    """Whether a login a relay names is the maintainer's (spec 055): one [agents.roles] maintainer
    lists, or, when it lists no user, one whose permission on the repo is admin, read from GitHub
    once per login and only when asked; a permission that can't be read is no maintainer's"""

    def __init__(self, listed: frozenset[str], repo: str | None) -> None:
        self.listed = listed
        self.repo = repo
        self.read: dict[str, bool] = {}

    def __contains__(self, login: object) -> bool:
        if not isinstance(login, str):
            return False
        if self.listed:
            return login.lower() in self.listed
        if login not in self.read:
            self.read[login] = self.admin(login)
        return self.read[login]

    def admin(self, login: str) -> bool:
        cmd, env = api([f"repos/{{owner}}/{{repo}}/collaborators/{login}/permission"], self.repo)
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            return False  # a 404 or any other failure: not a maintainer, fail closed
        try:
            answer = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return False
        return isinstance(answer, dict) and answer.get("permission") == "admin"


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GateError(f"can't load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


_MODULES: dict[str, ModuleType] = {}


def module(name: str, path: Path) -> ModuleType:
    """A sibling skill's script, loaded once and only when the gate needs it"""
    if name not in _MODULES:
        _MODULES[name] = load(name, path)
    return _MODULES[name]


def watch_state() -> ModuleType:
    return module("shipmill_watch_state", WATCH_STATE)


def has_agents(text: str, where: str) -> bool:
    """Whether the config has an [agents] table, read as watch_state.py reads it"""
    ws = watch_state()
    try:
        return ws.agents_table(text, Path(where)) is not None
    except ws.Refused as refused:
        raise GateError(str(refused).removeprefix("error: ")) from None


@dataclass(frozen=True)
class Zone:
    """A zone `shipmill decide classify` detects, at the base's level, with why"""

    zone: str
    level: str
    reason: str

    def line(self) -> str:
        return f"{self.zone}: {self.reason}"


class Classifier:
    """`shipmill decide classify --pr N --ref <base> --json` in the checkout, once per PR head"""

    def __init__(self, checkout: str, tool: str | None) -> None:
        self.checkout = checkout
        self.tool = tool
        self.found: dict[tuple[int, str, str], tuple[Zone, ...]] = {}

    def zones(self, number: int, ref: str, head: str) -> tuple[Zone, ...]:
        key = (number, ref, head)
        if key not in self.found:
            self.found[key] = self.run(number, ref)
        return self.found[key]

    def run(self, number: int, ref: str) -> tuple[Zone, ...]:
        ws = watch_state()
        try:
            cli: list[str] = ws.shipmill_cli(self.tool)
        except ws.Refused as refused:
            raise GateError(str(refused).removeprefix("error: ")) from None
        cmd = [*cli, "--repo", self.checkout, "decide", "classify", "--pr", str(number), "--ref", ref, "--json"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            raise GateError(
                f"{cmd[0]} is not on PATH: the gate reads the zones with `shipmill decide classify`; install uv, "
                "https://docs.astral.sh/uv/"
            ) from None
        if proc.returncode != 0:
            why = proc.stderr.strip() or proc.stdout.strip()
            raise GateError(f"`{' '.join(cmd)}` failed for #{number}: {why}; {self.fix(cli)}")
        return parse_zones(proc.stdout, number)

    def fix(self, cli: list[str]) -> str:
        """What to do when classify fails: the shipmill --tool names, or the release the plugin pins"""
        if self.tool is not None:
            return f"check that --tool {self.tool} is a shipmill uvx can run"
        return (
            f"{cli[-1]} is the release the plugin pins: if PyPI doesn't serve it yet, wait for its publish, "
            "or pass --tool <path or URL> to run another shipmill"
        )


@dataclass(frozen=True)
class Window:
    """What the gate reads of `shipmill window --json` (spec 056)"""

    timezone: str
    open: bool
    opens: datetime | None  # when closed: the next opening, in the window's zone
    labels: tuple[str, ...]
    bypass_labels: tuple[str, ...]
    next_merge: datetime  # when the spacing allows the next held merge, in the window's zone

    def held(self, labels: Iterable[str]) -> tuple[str, ...]:
        """The PR's held labels: those of `labels` it carries, none when it carries a bypass label"""
        carried = set(labels)
        if carried & set(self.bypass_labels):
            return ()
        return tuple(label for label in self.labels if label in carried)

    def queued(self, labels: Iterable[str], now: datetime) -> tuple[str, ...]:
        """The queued: line of a held PR that would otherwise read READY, at now; none when the
        PR isn't held or the window and its spacing let it through"""
        held = self.held(labels)
        if not held:
            return ()
        if not self.open:
            opens = "doesn't open within a week" if self.opens is None else f"opens {self.opens:%Y-%m-%d %H:%M}"
            return (f"held by the land window ({', '.join(held)}); {opens} {self.timezone}",)
        if self.next_merge > now:
            return (f"spacing: the next held merge after {self.next_merge:%H:%M} {self.timezone}",)
        return ()


class Windows:
    """`shipmill --repo <checkout> window --json --ref <base>`, run as `decide classify` is, once
    per base ref and pass (spec 056); a run that fails or prints what the gate can't read stops
    the gate, so a malformed [land.window] holds every merge rather than letting a held one through"""

    def __init__(self, checkout: str, tool: str | None) -> None:
        self.checkout = checkout
        self.tool = tool
        self.found: dict[str, Window | None] = {}

    def window(self, ref: str) -> Window | None:
        if ref not in self.found:
            self.found[ref] = self.run(ref)
        return self.found[ref]

    def run(self, ref: str) -> Window | None:
        ws = watch_state()
        try:
            cli: list[str] = ws.shipmill_cli(self.tool)
        except ws.Refused as refused:
            raise GateError(str(refused).removeprefix("error: ")) from None
        cmd = [*cli, "--repo", self.checkout, "window", "--json", "--ref", ref]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            raise GateError(
                f"{cmd[0]} is not on PATH: the gate reads the land window with `shipmill window`; install uv, "
                "https://docs.astral.sh/uv/"
            ) from None
        if proc.returncode != 0:
            why = proc.stderr.strip() or proc.stdout.strip()
            raise GateError(f"`{' '.join(cmd)}` failed: {why}; every PR into {ref} waits until it reads")
        return parse_window(proc.stdout, ref)


def parse_window(text: str, ref: str) -> Window | None:
    """`shipmill window --json`'s object; None for `configured: false`, and anything the gate can't
    read stops it"""
    what = f"`shipmill window --json --ref {ref}`"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GateError(f"{what} printed no JSON: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("configured"), bool):
        raise GateError(f"{what} printed no configured flag")
    if not data["configured"]:
        return None

    def strings(key: str) -> tuple[str, ...]:
        found = data.get(key)
        if not isinstance(found, list) or not all(isinstance(s, str) for s in found):
            raise GateError(f"{what} printed {key} {found!r}, not a list of labels")
        return tuple(found)

    def when(key: str, missing: bool) -> datetime | None:
        found = data.get(key)
        if found is None and missing:
            return None
        if not isinstance(found, str):
            raise GateError(f"{what} printed {key} {found!r}, not a time")
        try:
            moment = datetime.fromisoformat(found)
        except ValueError:
            raise GateError(f"{what} printed {key} {found!r}, not a time") from None
        if moment.tzinfo is None:
            raise GateError(f"{what} printed {key} {found!r}, a time without a zone")
        return moment

    if not isinstance(data.get("open"), bool) or not isinstance(data.get("timezone"), str):
        raise GateError(f"{what} printed no open flag or timezone")
    next_merge = when("next_merge", False)
    assert next_merge is not None  # when() refuses a missing one
    return Window(
        data["timezone"], data["open"], when("opens", True), strings("labels"), strings("bypass_labels"), next_merge
    )


def labels_of(number: int, repo: str | None) -> tuple[str, ...]:
    """The PR's labels, read only on a base with [land.window] (spec 056)"""
    cmd = ["gh", "pr", "view", str(number), "--json", "labels"]
    if repo:
        cmd += ["-R", repo]
    data = json.loads(gh(cmd, number))
    found = data.get("labels") if isinstance(data, dict) else None
    if not isinstance(found, list) or not all(isinstance(e, dict) and isinstance(e.get("name"), str) for e in found):
        raise GateError(f"gh pr view {number} --json labels printed no labels list: {str(data)[:200]}")
    return tuple(e["name"] for e in found)


def parse_zones(text: str, number: int) -> tuple[Zone, ...]:
    """classify's JSON zones, each a known zone at a known level; anything else stops the gate"""
    decisions = module("shipmill_decisions", DECISIONS)
    what = f"`shipmill decide classify --pr {number} --json`"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GateError(f"{what} printed no JSON: {exc}") from None
    listed = data.get("zones") if isinstance(data, dict) else None
    if not isinstance(listed, list):
        raise GateError(f"{what} printed no zones list")
    found = []
    for entry in listed:
        if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) for k in ("zone", "level", "reason")):
            raise GateError(f"{what} printed a zone that isn't {{zone, level, reason}}: {entry!r}")
        if entry["zone"] not in decisions.ZONES or entry["level"] not in decisions.LEVELS:
            raise GateError(
                f"{what} printed zone {entry['zone']!r} at {entry['level']!r}, which this gate doesn't know"
            )
        found.append(Zone(entry["zone"], entry["level"], entry["reason"]))
    return tuple(found)


def author_of(entry: dict) -> str:
    """The login as REST and --bot-login spell it: gh prints an App's as `app/<slug>`"""
    login = str(entry.get("login") or "")
    if login.startswith("app/"):
        return login[len("app/") :] + "[bot]"
    if entry.get("is_bot") and not login.endswith("[bot]"):
        return login + "[bot]"
    return login


# the fields the gate reads; the github-pr-triage eval cases record this read, so a change here
# re-records it there (#673)
FIELDS = "state,isDraft,mergeable,baseRefName,headRefOid,statusCheckRollup,author,body,files,changedFiles,commits,title"


def fetch(number: int, repo: str | None) -> dict:
    cmd = ["gh", "pr", "view", str(number), "--json", FIELDS]
    if repo:
        cmd += ["-R", repo]
    data = json.loads(gh(cmd, number))
    data["files"] = tuple(str(f["path"]) for f in data.get("files") or ())
    return data


def gh(cmd: list[str], number: int, env: dict[str, str] | None = None) -> str:
    """gh's output; a failure exits 1 with the message, as the gate always has"""
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        sys.exit(f"pr_gate: gh failed for #{number}: {proc.stderr.strip()}")
    return proc.stdout


def all_files(data: dict, number: int, repo: str | None) -> tuple[str, ...]:
    """Every file the PR changes: gh pr view lists the first 100, so past them the files API is
    read, which pages where `gh pr diff` refuses a diff over 300 files (#630). Each file is its
    path after the change, as gh pr view's `path` is; the API lists at most 3000, and a partial
    list stops the gate rather than being judged"""
    files: tuple[str, ...] = data["files"]
    if len(files) >= int(data.get("changedFiles") or 0):
        return files
    data["statuses"] = files_api(data, number, repo)
    return tuple(data["statuses"])


def api(args: list[str], repo: str | None) -> tuple[list[str], dict[str, str] | None]:
    """A `gh api` call and its env: gh fills {owner}/{repo} in from GH_REPO, which takes what -R
    takes, else from the cwd's repo, as gh pr view does"""
    cmd = ["gh", "api", *args]
    env = None
    if repo:
        env = {**os.environ, "GH_REPO": repo}
        host = re.fullmatch(r"([^/:]+)/[^/]+/[^/]+", repo.strip("/"))  # [HOST/]OWNER/NAME: gh api's host is its own
        cmd[2:2] = ["--hostname", host.group(1)] if host else []
    return cmd, env


def files_api(data: dict, number: int, repo: str | None) -> dict[str, str]:
    """Every file the PR changes, from the files API, each with its status (added, modified,
    renamed, ...); a list short of changedFiles stops the gate"""
    changed = int(data.get("changedFiles") or 0)
    cmd, env = api(["--paginate", f"repos/{{owner}}/{{repo}}/pulls/{number}/files?per_page=100", "--jq", ".[]"], repo)
    entries = [json.loads(line) for line in gh(cmd, number, env).splitlines() if line.strip()]
    statuses = {str(e["filename"]): str(e["status"]) for e in entries}
    if len(statuses) < changed:
        sys.exit(
            f"pr_gate: #{number} changes {changed} files but GitHub lists {len(statuses)} (its files API stops at "
            "3000); the gate judges no partial list: review and land it by hand"
        )
    return statuses


def added_specs(data: dict, number: int, repo: str | None) -> tuple[str, ...]:
    """The spec files the PR adds (spec 053). The files API is read only when a listed file has a
    spec's path, or gh pr view lists only part of the files, and not again after all_files read it"""
    statuses: dict[str, str] | None = data.get("statuses")
    if statuses is None:
        files: tuple[str, ...] = data["files"]
        whole = len(files) >= int(data.get("changedFiles") or 0)
        if whole and not any(SPEC_FILE.fullmatch(f) for f in files):
            return ()
        statuses = files_api(data, number, repo)
    data["statuses"] = statuses  # read once: the answer's spec comparison asks again (spec 055)
    return tuple(f for f, status in statuses.items() if status == "added" and SPEC_FILE.fullmatch(f))


def issues_read(numbers: list[int], wanted: str = "state") -> list[str]:
    """`gh api`'s arguments for the GraphQL read of the numbers, each under the alias i<N>, an issue
    with the wanted fields; the github-pr-triage eval cases record this read, so a change here
    re-records it there"""
    fields = " ".join(
        f"i{n}: issueOrPullRequest(number: {n}) {{ __typename ... on Issue {{ {wanted} }} }}" for n in numbers
    )
    query = (
        "query($owner: String!, $repo: String!) { repository(owner: $owner, name: $repo) { nameWithOwner "
        f"{fields} }} }}"
    )
    return ["graphql", "-F", "owner={owner}", "-F", "repo={repo}", "-f", f"query={query}"]


def issues_of(
    numbers: list[int], number: int, repo: str | None, wanted: str = "state"
) -> tuple[str, dict[int, dict | None]]:
    """The repo's owner/name and, for each number, its issue or pull request ({__typename} and, for
    an issue, the wanted fields), or None for a number the repo lacks: one GraphQL read. A NOT_FOUND
    error for one of the numbers is an answer; any other failure exits 1, as gh's always has"""
    aliases = {f"i{n}": n for n in numbers}
    cmd, env = api(issues_read(numbers, wanted), repo)
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    try:
        answer = json.loads(proc.stdout) if proc.stdout.strip() else None
    except json.JSONDecodeError:
        answer = None
    data = answer.get("data") if isinstance(answer, dict) else None
    found = data.get("repository") if isinstance(data, dict) else None
    errors = (answer.get("errors") if isinstance(answer, dict) else None) or []
    missing = all(
        isinstance(e, dict) and e.get("type") == "NOT_FOUND" and e.get("path") in [["repository", a] for a in aliases]
        for e in errors
    )
    if not isinstance(found, dict) or not isinstance(found.get("nameWithOwner"), str) or not missing:
        sys.exit(f"pr_gate: gh failed for #{number}: {proc.stderr.strip() or proc.stdout.strip()}")
    if proc.returncode != 0 and not errors:
        sys.exit(f"pr_gate: gh failed for #{number}: {proc.stderr.strip()}")
    return found["nameWithOwner"], {n: found.get(alias) for alias, n in aliases.items()}


def spec_problems(data: dict, number: int, repo: str | None) -> list[str]:
    """Why a spec PR is refused (spec 053): it adds a spec file, and no `Spec for` line of its body
    names an open issue of the repo; a PR that adds none, or edits a spec, isn't checked"""
    if not added_specs(data, number, repo):
        return []
    refs = spec_refs(str(data.get("body") or ""))
    numbers = sorted({n for _, n in refs if 0 < n <= GRAPHQL_INT})
    if not numbers:
        return [NO_ISSUE]
    name, nodes = issues_of(numbers, number, repo)
    for owner_repo, n in refs:
        if owner_repo is not None and owner_repo.lower() != name.lower():
            continue  # another repo's issue: the spec's feature issue is this repo's
        node = nodes.get(n)
        if isinstance(node, dict) and node.get("__typename") == "Issue" and node.get("state") == "OPEN":
            return []
    return [NO_ISSUE]


def base_head(branch: str, number: int, repo: str | None) -> tuple[str, list[dict]]:
    """The base branch's head commit and its checks, the newest run of each as newest_checks reads
    the PR's (#962): one read of the commit's statuses, which names the commit, then one of its
    check runs, every page. Each check is rollup-shaped, with the URLs a Repairs: line may name"""
    ref = urllib.parse.quote(branch, safe="")
    cmd, env = api([f"repos/{{owner}}/{{repo}}/commits/{ref}/status?per_page=100"], repo)
    combined = json.loads(gh(cmd, number, env))
    sha = combined.get("sha") if isinstance(combined, dict) else None
    statuses = combined.get("statuses") if isinstance(combined, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{7,64}", sha) or not isinstance(statuses, list):
        raise GateError(f"the status of {branch}'s head is not a combined status: {combined!r}")
    if len(statuses) < int(combined.get("total_count") or 0):
        raise GateError(f"{branch}@{sha[:7]} has more than 100 commit statuses; the gate judges no partial list")
    entries = [status_entry(s, branch) for s in statuses]
    path = f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs?per_page=100"
    cmd, env = api(["--paginate", path, "--jq", ".check_runs[]"], repo)
    entries += [run_entry(json.loads(line), branch) for line in gh(cmd, number, env).splitlines() if line.strip()]
    return sha, newest_entries(entries)


def status_entry(status: object, branch: str) -> dict:
    """A commit status as the rollup's StatusContext, with its target URL"""
    if not isinstance(status, dict) or not all(isinstance(status.get(k), str) for k in ("context", "state")):
        raise GateError(f"a commit status on {branch}'s head is not {{context, state}}: {status!r}")
    return {
        "context": status["context"],
        "state": status["state"].upper(),
        "startedAt": status.get("created_at"),
        "urls": [str(status.get("target_url") or "")],
    }


def run_entry(run_: object, branch: str) -> dict:
    """A check run as the rollup's CheckRun, keyed by its check suite, which a rerun of its jobs
    stays in, with its id (an Actions job's) and its URLs"""
    suite = run_.get("check_suite") if isinstance(run_, dict) else None
    if (
        not isinstance(run_, dict)
        or not isinstance(run_.get("id"), int)
        or not all(isinstance(run_.get(k), str) for k in ("name", "status"))
        or not isinstance(suite, dict)
        or not isinstance(suite.get("id"), int)
    ):
        raise GateError(f"a check run on {branch}'s head is not {{id, name, status, check_suite}}: {run_!r}")
    return {
        "workflowName": f"suite {suite['id']}",
        "name": run_["name"],
        "status": run_["status"].upper(),
        "conclusion": str(run_.get("conclusion") or "").upper(),
        "startedAt": run_.get("started_at"),
        "urls": [str(run_.get(k) or "") for k in ("html_url", "details_url")],
        "id": run_["id"],
    }


def repairs_of(body: str) -> list[str]:
    """Each Repairs: line's URL, in order; only a line starting with it, after an optional list
    bullet, outside a fence, names one"""
    return [found.group(1) for found in map(_REPAIRS.match, unfenced(body)) if found is not None]


def repaired(entry: dict, named: list[str]) -> bool:
    """Whether a Repairs: URL names the failed check: its workflow run's URL, its job's, its check
    run's, or, for a commit status, its exact target URL"""
    urls = {u for u in entry["urls"] if u}
    runs = {int(found.group(1)) for found in map(_ACTIONS_URL.fullmatch, urls) if found is not None}
    for url in named:
        actions, check_run = _ACTIONS_URL.fullmatch(url), _CHECK_RUN_URL.fullmatch(url)
        if url in urls:
            return True
        if actions is not None and actions.group(2) is not None:
            if int(actions.group(2)) == entry.get("id"):
                return True
        elif actions is not None and int(actions.group(1)) in runs:
            return True
        if check_run is not None and int(check_run.group(1)) == entry.get("id"):
            return True
    return False


def base_failures(branch: str, sha: str, entries: list[dict], body: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The base head's failed checks no Repairs: line of the body names, and those one does"""
    named = repairs_of(body)
    red: list[str] = []
    repairs: list[str] = []
    for entry in entries:
        check = check_of(entry)
        if check.done and check.conclusion not in NOT_RED:
            (repairs if repaired(entry, named) else red).append(f"{check.name} failed on {branch}@{sha[:7]}")
    return tuple(red), tuple(repairs)


def triage_state() -> ModuleType:
    return module("shipmill_triage_state", TRIAGE_STATE)


def commit_messages(data: dict, number: int) -> list[tuple[str, str]]:
    """Each of the PR's commits, its short sha and its whole message, as gh pr view lists them"""
    commits = data.get("commits")
    if not isinstance(commits, list):
        raise GateError(f"gh pr view {number} listed no commits")
    found = []
    for commit in commits:
        if not isinstance(commit, dict) or not isinstance(commit.get("oid"), str):
            raise GateError(f"a commit of #{number} is not {{oid, messageHeadline, messageBody}}: {commit!r}")
        message = f"{commit.get('messageHeadline') or ''}\n{commit.get('messageBody') or ''}"
        found.append((commit["oid"][:7], message))
    return found


def closing_problems(data: dict, number: int, repo: str | None) -> list[str]:
    """Why the PR is refused for its closing keywords (D-76, D-79). A commit's keyword counts
    anywhere in its message, as GitHub closes by it: commit_closes' rule (#988). The title and the
    body are read by triage_state.py's keyword_closes, the rule shipped.py reads too (#416): in the
    body, one starting a line, after an optional list bullet, outside a fence; in the title, one
    anywhere outside a code span; in either, mid-line in the body, in backticks, or naming
    owner/repo#N, it names nothing. The title is read as the squash commit it becomes (D-33, #987).
    The title's or a commit's keyword naming an issue its body lists as Part of #N, then the
    title's, a commit's, or the body's naming an open issue of the repo with a ## Check section,
    read once in GraphQL for every number the keywords name; a commit naming owner/repo#N or an
    issue's URL takes that read even when nothing else is named, since it names the PR's repo"""
    ts = triage_state()
    body = str(data.get("body") or "")
    parts = {int(n) for n in PART_OF.findall(body)}
    title = [("the title", n) for n in sorted(ts.keyword_closes(str(data.get("title") or ""), ""))]
    commits = [(f"commit {sha}", ref) for sha, text in commit_messages(data, number) for ref in commit_closes(ts, text)]
    in_body = [("the body", n) for n in closed_by(ts, body)]
    read: tuple[str, dict[int, dict | None]] | None = None
    if any(owner is not None for _, (owner, _) in commits):
        every = {n for _, n in title + in_body} | {n for _, (_, n) in commits}
        wanted = sorted(n for n in every if 0 < n <= GRAPHQL_INT)
        read = issues_of(wanted, number, repo, "state body") if wanted else ("", {})
    own = read[0].lower() if read is not None else ""
    # the title and the commits: what lands as commits under a squash merge
    landed = title + [(where, n) for where, (owner, n) in commits if owner is None or owner.lower() == own]
    parted = [(where, n) for where, n in landed if n in parts]
    problems = [f"{where} closes #{n}, which the body lists as Part of #{n}" for where, n in parted]
    named = [pair for pair in landed if pair not in parted] + in_body
    numbers = sorted({n for _, n in named if 0 < n <= GRAPHQL_INT})
    if not numbers:
        return problems
    _, nodes = read if read is not None else issues_of(numbers, number, repo, "state body")
    for where, n in named:
        node = nodes.get(n)
        if not isinstance(node, dict) or node.get("__typename") != "Issue" or node.get("state") != "OPEN":
            continue
        if ts.CHECK.search(str(node.get("body") or "")) is not None:
            problems.append(f"{where} closes #{n}, an open issue with a ## Check: write Part of #{n} instead")
    return problems


def closed_by(ts: ModuleType, text: str) -> list[int]:
    """The issues a text's closing keywords name, by keyword_closes' line rule"""
    return sorted(ts.keyword_closes("", text))


def commit_closes(ts: ModuleType, message: str) -> list[tuple[str | None, int]]:
    """Each issue a commit message's closing keywords name, as GitHub closes by them once the
    commit reaches the default branch (D-79, #988): any of triage_state.py's KEYWORDS as a whole
    word, in any case, an optional colon, whitespace, then #N, owner/repo#N, or an issue's URL
    https://github.com/owner/repo/issues/N (#993; a /pull/N URL names nothing), anywhere in the
    message, mid-line, in backticks, and in a fence too. Each with its owner/repo, None for #N"""
    closer = re.compile(
        rf"\b{ts.KEYWORDS}:?\s+(?:([\w.-]+/[\w.-]+)?#([0-9]+)|https://github\.com/([\w.-]+/[\w.-]+)/issues/([0-9]+))\b",
        re.IGNORECASE,
    )
    return [(owner or url_owner or None, int(n or url_n)) for owner, n, url_owner, url_n in closer.findall(message)]


def retro() -> ModuleType:
    """retro.py, which imports metrics from its own folder, as when it runs from there"""
    if "shipmill_retro" not in _MODULES:
        folder = str(RETRO.parent)
        sys.path.insert(0, folder)
        try:
            _MODULES["shipmill_retro"] = load("shipmill_retro", RETRO)
        finally:
            sys.path.remove(folder)
    return _MODULES["shipmill_retro"]


# what the answer is read from (spec 055): a pull request's or an issue's creation and its newest
# comments, and a pull request's force-pushes; the github-pr-triage eval cases record this read
THREAD = (
    "createdAt comments(last: 100) { pageInfo { hasPreviousPage } "
    "nodes { author { __typename login } authorAssociation body createdAt } }"
)
FORCE_PUSHES = (
    "timelineItems(last: 100, itemTypes: [HEAD_REF_FORCE_PUSHED_EVENT]) { pageInfo { hasPreviousPage } "
    "nodes { ... on HeadRefForcePushedEvent { createdAt beforeCommit { oid } } } }"
)
FULL_SHA = re.compile(r"[0-9a-f]{40}")
DIFFERS = "answered at {sha7}, and the change differs since"
NOT_RECOMMENDED = "the answer doesn't take the recommended option"
UNNAMED = "the head the answer was given at can't be named"


def thread_read(number: int) -> list[str]:
    """`gh api`'s arguments for the GraphQL read of pull request number's thread"""
    query = (
        "query($owner: String!, $repo: String!) { repository(owner: $owner, name: $repo) { "
        f"pullRequest(number: {number}) {{ {THREAD} {FORCE_PUSHES} }} }} }}"
    )
    return ["graphql", "-F", "owner={owner}", "-F", "repo={repo}", "-f", f"query={query}"]


def pr_thread(number: int, repo: str | None) -> dict:
    """The pull request's thread, one GraphQL read; a gh failure exits 1, a shape the gate can't
    read stops it"""
    cmd, env = api(thread_read(number), repo)
    answer = json.loads(gh(cmd, number, env))
    data = answer.get("data") if isinstance(answer, dict) else None
    found = data.get("repository") if isinstance(data, dict) else None
    node = found.get("pullRequest") if isinstance(found, dict) else None
    if not isinstance(node, dict):
        raise GateError(f"GitHub's GraphQL gave no thread for #{number}: {answer!r}")
    return node


def comments_of(node: dict, where: str) -> tuple[list[dict], bool]:
    """A thread's comments, oldest first, and whether they are all of them"""
    comments = node.get("comments")
    nodes = comments.get("nodes") if isinstance(comments, dict) else None
    info = comments.get("pageInfo") if isinstance(comments, dict) else None
    if not isinstance(nodes, list) or not isinstance(info, dict):
        raise GateError(f"the comments of {where} are not {{nodes, pageInfo}}: {comments!r}")
    for comment in nodes:
        if not isinstance(comment, dict) or not all(isinstance(comment.get(k), str) for k in ("body", "createdAt")):
            raise GateError(f"a comment of {where} is not {{body, createdAt}}: {comment!r}")
    return nodes, info.get("hasPreviousPage") is False


def newest_question(comments: list[dict], bots: frozenset[str]) -> int | None:
    """The index of the newest needs-decision question, as retro.py reads one: its first line is
    the marker, by an OWNER, MEMBER, or COLLABORATOR or the --bot-login"""
    rt = retro()
    for i in range(len(comments) - 1, -1, -1):
        if rt.first_line(comments[i]["body"]) == rt.NEEDS_DECISION_MARK and rt.trusted(comments[i], bots):
            return i
    return None


def issue_question(data: dict, number: int, repo: str | None, bots: frozenset[str]) -> tuple[list[dict], int] | None:
    """The newest question on an issue the pull request closes (triage_state.py's keyword_closes) or
    names as Part of #N, with that issue's comments: one GraphQL read; None without one"""
    body = str(data.get("body") or "")
    refs = triage_state().keyword_closes(str(data.get("title") or ""), body) | {int(n) for n in PART_OF.findall(body)}
    numbers = sorted(n for n in refs if 0 < n <= GRAPHQL_INT and n != number)
    if not numbers:
        return None
    _, nodes = issues_of(numbers, number, repo, THREAD)
    newest: tuple[datetime, list[dict], int] | None = None
    for n in numbers:
        node = nodes.get(n)
        if not isinstance(node, dict) or node.get("__typename") != "Issue":
            continue
        comments, _ = comments_of(node, f"#{n}")
        asked = newest_question(comments, bots)
        if asked is None:
            continue
        at = moment(comments[asked]["createdAt"], f"a comment of #{n}'s createdAt")
        if newest is None or at > newest[0]:
            newest = (at, comments, asked)
    return None if newest is None else (newest[1], newest[2])


def head_at(data: dict, thread: dict, at: datetime, number: int) -> str | None:
    """The pull request's head when the answer was given (spec-gate.md's rule): after a force-push
    since then, the beforeCommit of the first one after it; else the newest commit whose
    committedDate is at or before it. None when neither can be named"""
    items = thread.get("timelineItems")
    nodes = items.get("nodes") if isinstance(items, dict) else None
    info = items.get("pageInfo") if isinstance(items, dict) else None
    if not isinstance(nodes, list) or not isinstance(info, dict):
        raise GateError(f"the force-pushes of #{number} are not {{nodes, pageInfo}}: {items!r}")
    pushes = []
    for event in nodes:
        if not isinstance(event, dict):
            raise GateError(f"a force-push of #{number} is not {{createdAt, beforeCommit}}: {event!r}")
        before = event.get("beforeCommit")
        oid = before.get("oid") if isinstance(before, dict) else None
        pushes.append((moment(event.get("createdAt"), f"a force-push of #{number}'s createdAt"), oid))
    after = [push for push in pushes if push[0] > at]
    if after:
        if info.get("hasPreviousPage") is not False and len(after) == len(pushes):
            return None  # the first push after the answer may be older than the ones read
        oid = min(after, key=lambda push: push[0])[1]
        return oid if isinstance(oid, str) and FULL_SHA.fullmatch(oid) else None
    newest: tuple[datetime, str] | None = None
    for commit in data.get("commits") or ():
        if not isinstance(commit, dict) or not isinstance(commit.get("oid"), str):
            raise GateError(f"a commit of #{number} is not {{oid, committedDate}}: {commit!r}")
        when = moment(commit.get("committedDate"), f"a commit of #{number}'s committedDate")
        if when <= at and (newest is None or when >= newest[0]):
            newest = (when, commit["oid"])
    return None if newest is None else newest[1]


def has_commit(checkout: str, sha: str) -> bool:
    """Whether the checkout holds the commit, fetched from origin when it doesn't yet"""
    if quiet(checkout, "cat-file", "-e", f"{sha}^{{commit}}") is not None:
        return True
    quiet(checkout, "fetch", "--quiet", "origin", sha)
    return quiet(checkout, "cat-file", "-e", f"{sha}^{{commit}}") is not None


def own_change(checkout: str, base_ref: str, sha: str, leaving: tuple[str, ...] = ()) -> str:
    """The pull request's own change at a head: the patch from its merge-base with the base to it,
    leaving out the files named"""
    merge_base = git(checkout, "merge-base", base_ref, sha).strip()
    paths = ("--", ".", *(f":(exclude,literal){path}" for path in leaving)) if leaving else ()
    return git(checkout, "diff", "--no-color", "--no-ext-diff", merge_base, sha, *paths)


def same_approval(checkout: str, base_ref: str, spec: str, answered: str, head: str) -> bool:
    """specs.py same-approval (D-81): exit 0 covers the judged head, any other exit doesn't"""
    cmd = [sys.executable, str(SPECS), "same-approval", "--base", base_ref, spec, answered, head]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=checkout).returncode == 0


def same_change(checkout: str, base_ref: str, answered: str, head: str, specs: tuple[str, ...]) -> bool:
    """Whether the answered head's own change is the judged head's: a spec PR's spec files by
    same-approval, every other file's patch byte for byte; a head the checkout can't read isn't"""
    if not has_commit(checkout, answered) or not has_commit(checkout, head):
        return False
    if not all(same_approval(checkout, base_ref, spec, answered, head) for spec in specs):
        return False
    return own_change(checkout, base_ref, answered, specs) == own_change(checkout, base_ref, head, specs)


def acceptance(
    data: dict, number: int, repo: str | None, bot_login: str | None, checkout: str, maintainers: Maintainers
) -> tuple[bool, str | None]:
    """Whether the maintainer's answer covers the judged head (spec 055), and, when it doesn't,
    the needs-decision line that says why (None for no line): the newest question on the pull
    request, else on an issue it closes or names as Part of #N; its first trusted answer, by
    retro.py's answer_at (a relay by the --bot-login counts when it names one of maintainers);
    taking the (recommended) option, by
    retro.py's takes_recommended; given on an issue before the pull request opened, or at a head
    whose own change is the judged head's. Anything else leaves the question open"""
    rt = retro()
    bots = frozenset({bot_login}) if bot_login else frozenset()
    thread = pr_thread(number, repo)
    comments, whole = comments_of(thread, f"#{number}")
    asked = newest_question(comments, bots)
    on_issue = False
    if asked is None:
        if not whole:
            return False, None  # its own question may be older than the comments read
        found = issue_question(data, number, repo, bots)
        if found is None:
            return False, None
        (comments, asked), on_issue = found, True
    later = comments[asked + 1 :]
    answer = rt.answer_at(later, bots, maintainers)
    if answer is None:
        return False, None
    index, said = answer
    if not rt.takes_recommended(comments[asked]["body"], said):
        return False, NOT_RECOMMENDED
    at = moment(later[index]["createdAt"], f"the answer on #{number}'s createdAt")
    if on_issue and at < moment(thread.get("createdAt"), f"#{number}'s createdAt"):
        return True, None  # given before the pull request opened: it covers every head
    head = str(data["headRefOid"])
    answered = head_at(data, thread, at, number)
    if answered is None:
        return False, UNNAMED
    if answered == head:
        return True, None
    base_ref = f"origin/{data['baseRefName']}"
    if quiet(checkout, "rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}") is None:
        raise GateError(f"{base_ref} is not in {checkout}: run `git -C {checkout} fetch origin`")
    specs = added_specs(data, number, repo)
    if same_change(checkout, base_ref, answered, head, specs):
        return True, None
    return False, DIFFERS.format(sha7=answered[:7])


def judge(
    data: dict,
    number: int,
    base: Base,
    agent: bool,
    accepted: bool,
    zones: tuple[Zone, ...] | None = None,
    spec: tuple[str, ...] = (),
) -> Gate:
    """zones, classify's for the PR, are given when the base's config has [agents] (spec 030);
    they replace the direction and Protected areas checks. spec is spec_problems' answer, which
    --maintainer-accepted doesn't lift (spec 053). A draft is judged for nothing else (D-67);
    agent, for a draft, says the --bot-login authored it, so its line says to mark it ready"""
    checks = newest_checks(data.get("statusCheckRollup") or ())
    if data["isDraft"]:
        head = data["headRefOid"]
        return Gate(number, data["state"], data["mergeable"], data["baseRefName"], head, checks, draft=True, own=agent)
    files: tuple[str, ...] = data["files"]
    refused: list[str] = []
    if agent and base.ids is not None:
        refused = plan_problems(str(data.get("body") or ""), base.ids)
    refused += data.get("closes") or ()  # whoever opened it (D-76)
    asks: list[str] = []
    never: list[str] = []
    notices: list[str] = []
    if zones is not None:
        never = [z.line() for z in zones if z.level == "never"]  # --maintainer-accepted never lifts it (D-48)
        asks = [] if accepted else [z.line() for z in zones if z.level == "ask"]
        notices = [z.line() for z in zones if z.level == "notify"]
    elif not accepted and (base.ids is not None or base.reviews):
        edited = [f for f in files if f == DIRECTION or f.startswith(DIRECTION_DIR)]
        asks += [f"{f} edits the product's direction, which only the maintainer changes (D-34)" for f in edited]
        for area in base.protected(files):
            asks += [f"{f} matches `{area.glob}` ({area.file}): {area.why}" for f in files if area.covers(f)]
    return Gate(
        number,
        data["state"],
        data["mergeable"],
        data["baseRefName"],
        data["headRefOid"],
        checks,
        tuple(refused),
        tuple(asks),
        tuple(never),
        tuple(notices),
        spec=spec,
    )


def render(gate: Gate) -> str:
    green = sum(c.done and c.conclusion in GREEN for c in gate.checks)
    failed = [c for c in gate.checks if c.done and c.conclusion not in GREEN]
    pending = [c for c in gate.checks if not c.done]
    lines = [
        f"#{gate.number} {LABELS[gate.verdict]} state={gate.state} mergeable={gate.mergeable} base={gate.base} "
        f"head={gate.head} checks={len(gate.checks)} green={green} pending={len(pending)} failed={len(failed)}"
    ]
    lines += [f"  failed: {c.name} ({c.conclusion})" for c in failed]
    lines += [f"  pending: {c.name} ({c.waits})" for c in pending]
    lines += [f"  base: red: {line}" for line in gate.base_red]
    lines += [f"  base: repairs: {line}" for line in gate.base_repairs]
    lines += [f"  refused: {reason}" for reason in gate.refused]
    lines += [f"  spec: {reason}" for reason in gate.spec]
    lines += [f"  maintainer-only: {reason}" for reason in gate.never]
    lines += [f"  needs-decision: {reason}" for reason in gate.asks]
    lines += [f"  notify: {reason}" for reason in gate.notices]
    if gate.verdict == QUEUED:
        lines += [f"  queued: {reason}" for reason in gate.queued]
    if gate.verdict == DRAFT and gate.own:
        lines.append(
            "  draft: the App's own, no session owns it: once nothing it waits on is open, mark it ready"
            f" (gh pr ready {gate.number}, through shipmill gh) and run the gate again (D-67)"
        )
    elif gate.verdict == DRAFT:
        lines.append("  draft: left to its author until marked ready (D-67)")
    return "\n".join(lines)


def polls(gates: list[Gate]) -> bool:
    """Whether --wait polls again: while the worst verdict is PENDING, or is NEEDS_DECISION and a
    NEEDS_DECISION PR has a check still pending on its own head, so the question waits for its CI
    (#1028); the base's checks are never pending (D-75), and every other verdict stops the wait"""
    worst = max((g.verdict for g in gates), key=RANK.index)
    if worst == PENDING:
        return True
    return worst == NEEDS_DECISION and any(
        g.verdict == NEEDS_DECISION and any(not c.done for c in g.checks) for g in gates
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prs", nargs="+", type=int, help="PR numbers")
    parser.add_argument("-R", "--repo", help="owner/name; default: the current checkout's repo")
    parser.add_argument(
        "--wait",
        action="store_true",
        help="poll until no check is pending, on a NEEDS_DECISION PR's head too, so its question waits for CI",
    )
    parser.add_argument("--interval", type=int, default=30, help="seconds between polls (default 30)")
    parser.add_argument("--timeout", type=int, default=1800, help="seconds before --wait gives up (default 1800)")
    parser.add_argument(
        "--checkout",
        help="the repo's checkout, read at origin/HEAD, else at the PR's base branch on origin (default: ., "
        "and outside a checkout nothing is read)",
    )
    parser.add_argument("--bot-login", help="the login agents write as, such as <slug>[bot]; its PRs are agents'")
    parser.add_argument("--agent", action="store_true", help="every PR named is an agent's (a handover)")
    parser.add_argument(
        "--maintainer-accepted",
        action="store_true",
        help="the maintainer accepted these PRs' protected or direction changes, or their ask zones; don't ask "
        "again (a never zone stays: the maintainer merges it by hand)",
    )
    parser.add_argument(
        "--tool",
        help="with [agents] on the base: where uvx gets shipmill for `decide classify` (default: "
        "shipmill==<the plugin.json version>)",
    )
    args = parser.parse_args()
    if args.interval < 1 or args.timeout < 1:
        parser.error("--interval and --timeout must be positive")
    if args.bot_login is not None and not args.bot_login.strip():
        parser.error("--bot-login names a login, such as <slug>[bot]")
    deadline = time.monotonic() + args.timeout
    try:
        bases = Bases(args.checkout, args.repo)
        classifier = Classifier(bases.checkout, args.tool)
        specs: dict[tuple[int, str, str], tuple[str, ...]] = {}  # by PR, head, and body: a --wait reads each once
        closings: dict[tuple[int, str, str, str], tuple[str, ...]] = {}  # the same and the title, for its
        # closing keywords (D-76, #987)
        maintainers: dict[frozenset[str], Maintainers] = {}  # who a relayed answer may name (spec 055)
        while True:
            gates = []
            heads: dict[str, tuple[str, list[dict]]] = {}  # each base branch's head, read once a pass (D-75)
            windows = Windows(bases.checkout, args.tool)  # each base's land window, read once a pass (spec 056)
            for number in args.prs:
                data = fetch(number, args.repo)
                base = bases.base(str(data["baseRefName"]))
                own = args.bot_login is not None and author_of(data.get("author") or {}) == args.bot_login
                if data["isDraft"]:  # neither its files nor its zones are read (D-67)
                    gates.append(judge(data, number, base, own, args.maintainer_accepted))
                    continue
                if base.ids is not None or base.reviews:
                    data["files"] = all_files(data, number, args.repo)
                agent = args.agent or own
                spec: tuple[str, ...] = ()
                if data["state"] == "OPEN":  # a closed PR reads BLOCKED: nothing to read for it
                    key = (number, str(data["headRefOid"]), str(data.get("body") or ""))
                    if key not in specs:
                        specs[key] = tuple(spec_problems(data, number, args.repo))
                    spec = specs[key]
                    closing = (*key, str(data.get("title") or ""))
                    if closing not in closings:
                        closings[closing] = tuple(closing_problems(data, number, args.repo))
                    data["closes"] = closings[closing]
                zones = None
                if base.agents and base.ref is not None:
                    zones = classifier.zones(number, base.ref, str(data["headRefOid"]))
                judged = judge(data, number, base, agent, args.maintainer_accepted, zones, spec)
                if judged.verdict == NEEDS_DECISION:  # the answer on GitHub lifts the asks (spec 055)
                    if base.maintainers not in maintainers:  # one per base read: its permission reads too
                        maintainers[base.maintainers] = Maintainers(base.maintainers, args.repo)
                    who = maintainers[base.maintainers]
                    covered, why = acceptance(data, number, args.repo, args.bot_login, bases.checkout, who)
                    judged = replace(judged, asks=() if covered else (*judged.asks, *([why] if why else [])))
                if data["state"] == "OPEN":
                    branch = str(data["baseRefName"])
                    if branch not in heads:
                        heads[branch] = base_head(branch, number, args.repo)
                    red, repairs = base_failures(branch, *heads[branch], str(data.get("body") or ""))
                    judged = replace(judged, base_red=red, base_repairs=repairs)
                    # one window per repo, for PRs into the branch its config was read from (spec 056)
                    if base.window and base.ref == f"origin/{branch}":
                        window = windows.window(base.ref)  # read for every PR there: a failure stops them all
                        if window is not None and judged.verdict == READY:
                            now = datetime.now(timezone.utc)  # noqa: UP017 (3.10)
                            judged = replace(judged, queued=window.queued(labels_of(number, args.repo), now))
                gates.append(judged)
            worst = max((g.verdict for g in gates), key=RANK.index)
            if not args.wait or not polls(gates) or time.monotonic() >= deadline:
                print("\n".join(render(g) for g in gates))
                return worst
            time.sleep(args.interval)
    except GateError as exc:
        print(f"pr_gate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
