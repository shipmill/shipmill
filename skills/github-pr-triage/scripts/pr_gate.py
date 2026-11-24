#!/usr/bin/env python3
"""Merge gate: is each PR open, mergeable, and green on every CI check that has finished?
And does it keep to the repo's direction (spec 024)?

- An agent's PR (authored by --bot-login, every PR named with --agent, or one whose body
  carries the agent marker `<!-- shipmill:agent -->` on a line of its own, whoever its author:
  spec 055, D-62) carries a `## Plan` section with `Serves:`, `Files:`, `Order:`, and `Proof:` lines, and its
  `Serves:` names goal ids docs/product.md lists, `quality bar`, or quality-bar ids it
  lists, alone (`Q-6`) or as `quality bar (Q-4, Q-6)`; without a
  docs/product.md the plan isn't checked. A person's PR is never refused for its plan
- A PR whose files match a REVIEW.md Protected areas glob, or that edits docs/product.md
  or docs/product/, waits on the maintainer (needs-decision) until their answer on GitHub
  accepts it (below)

The maintainer's answer (spec 055), read only for a PR that would read NEEDS_DECISION: the
newest needs-decision question (its first line `<!-- shipmill:needs-decision -->`, by an
OWNER, MEMBER, or COLLABORATOR or the --bot-login) on the PR, or, when the PR has none and the
--bot-login or an OWNER, MEMBER, or COLLABORATOR opened it, on an issue its title or body closes
or names as `Part of #N`; its newest answer as retro.py reads one (D-89; a trusted person's reply
without the agent marker, or the --bot-login's relay whose first line is `Decision by @<login>`
naming the maintainer: a user `[agents.roles] maintainer` lists on that branch, or, when it lists
none, a login whose permission on the repo is admin, one read of
`repos/<o>/<r>/collaborators/<login>/permission` made only for a relay; one that can't be read is
no maintainer); that answer's whole reply (every non-blank line) being one line that takes the
option marked (recommended) as it stands. A relay is read by its grammar (needs-decision.md,
D-93; retro.py's parse_relay): past its first line, an optional `Answered in the session:`, the
answer line (an option as listed, or `own: <text>`, the person's own words), an optional
`Basis: item|round|standing` (recorded, deciding nothing), and a `Note:` line after which nothing
is read; a relay with any other line before `Note:`, or a number followed by words naming no
option as listed, is not counted, `  needs-decision: relay not counted: format`. It lifts the
asks, and CI decides, when it covers the judged head: one given on an issue
before the PR opened covers every head; any other covers the head its question names in full
on its line `<!-- shipmill:head <sha> -->` (under its visible `CI on <sha7>` line), that exact
commit, and every head whose own change, `git diff $(git merge-base origin/<base> <head>)
<head>`, is the same as that commit's, or, for a PR adding a spec, whose spec files `specs.py
same-approval` reads the same (exit 0) and whose other files' patch is the same. Otherwise the
asks stay, with `  needs-decision: answered at <sha7>, and the change differs since`,
`  needs-decision: the answer doesn't take the recommended option`, or `  needs-decision: the
question names no head: ask again with its `<!-- shipmill:head <sha> -->` line`. It reads the PR's
opener, newest 100 comments, and force-pushes, and the issues' threads, from the one GraphQL read
the veto below makes for every open PR; a never zone stays MAINTAINER_ONLY whatever the answer. The answer
is the only acceptance: --maintainer-accepted, which once said the maintainer accepted, exits 2
before any read.

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

- never: MAINTAINER_ONLY, `  maintainer-only: <zone>: <reason>`; no answer lifts it, since
  only the maintainer merges it, by hand (D-48)
- ask: NEEDS_DECISION, `  needs-decision: <zone>: <reason>`, until the maintainer's answer
  accepts it
- notify: the verdict stays, with `  notify: <zone>: <reason>`; the skill posts the decided
  comment before it merges
- act: nothing

The spec of accepted work (spec 067): classify's `accepted-spec` zone at notify, a level read from
that branch, never the PR, lifts no ask on its own. The --bot-login's newest decided comment on the
PR (its first line `<!-- shipmill:decided zone=<id> until=<time> -->`, read from the PR's thread as
the answer is) must name the zone accepted-spec and, on its line `<!-- shipmill:head <sha> -->`, the
judged head, or a head whose own change is the judged head's as the answer's is (the spec files by
`specs.py same-approval`, the decisions log by entry, every other file byte for byte; a D-n the PR
claims renumbered by a rebase, and the lines citing it, read the same, #1265). Otherwise the PR reads NEEDS_DECISION,
`  needs-decision: accepted-spec: <why>`, which a new decided comment or the maintainer's answer
lifts; a decided comment by anyone else, the maintainer too, never counts.

Without [agents] on that branch the gate judges as it did before spec 030.

A veto (D-48, #1309): an open PR is BLOCKED, `  decided: vetoed by @<login> at <time>, not handled`
(the time in UTC), while it or an issue its title or body closes (triage_state.py's keyword_closes)
holds a veto triage_state.py would read as VETOED (its unhandled_veto): after the first comment
whose first line is `<!-- shipmill:decided ... -->` by the --bot-login or an OWNER, MEMBER, or
COLLABORATOR, a comment by an OWNER, MEMBER, or COLLABORATOR other than the --bot-login, without the
agent marker, whose first word is `veto`, or the --bot-login's relay of the maintainer's veto
(D-103, #1482: its first line `Decision by @<login>` naming the maintainer as the answer's relay
does, in the relay grammar, its answer line `own: veto [<text>]` or starting with `veto`; the line
names that login), with no newer `<!-- shipmill:veto-handled ... -->` by such an author. It reads
the newest 100 comments of each, in one GraphQL read of the PR's thread and those of the issues it
closes or names as Part of #N, which the answer above reads too. A thread with older comments
unread fails closed (#1330): when those 100 hold no veto it reads as VETOED but do hold such a
veto with no newer veto-handled marker after it, its decided marker may be older than them, and
the PR is BLOCKED, `  decided: the thread of #N is cut off at 100 comments: a veto in it can't be
ruled out handled or not, so a person looks`. A vetoed PR reads BLOCKED whatever else holds it, a
draft or a closed one aside.

A spec pull request (spec 053), one that adds a file docs/specs/NNN-<slug>.md (the files API's
`status: added`; an edit, a rename, or a copy is not checked), names its feature issue: a line
of its body, outside a code fence, starting `Spec for #N` (after an optional list bullet;
`owner/repo#N` of the same repo reads the same) whose N is an open issue of the repo, not a pull
request. Without one it is REFUSED, `  spec: names no feature issue: ...`, whoever opened it,
and the maintainer's answer doesn't lift it. The check reads the files API, and GitHub's GraphQL
once for the issues the lines name; a PR that gh pr view lists whole, with no spec path, reads
neither.

An approved spec changed (D-81, #1311): in a checkout, for every spec file a PR modifies (the files
API's `status: modified`, from the read above) whose text on origin/<base> says `status: approved`
or `status: built`, the gate runs `specs.py same-approval --base origin/<base> <spec> <merge-base>
<head>`, the PR's own change to the spec against none. Format only, the `status:` line, or a change
to Issues or Verification alone (what the split's docs PR and a build PR fill in) keeps the
verdict; any other change reads NEEDS_DECISION, `  spec: <file> changes approved Behaviour`,
whoever opened the PR, a spec PR too, until the maintainer's answer accepts it; so does an approved
or built spec the PR renames, named by its old path. Outside a checkout it isn't read.

The files its issues allow (spec 085): an agent's open PR, not a draft, is checked against the
allowed files of each issue it closes or names as `Part of #N`, read from the issue threads the veto
reads (no new read). An issue's allowance is its newest comment whose first line starts `Triage:
**implement**` or `Proposed plan:`, by the --bot-login or an OWNER, MEMBER, or COLLABORATOR, created
before the PR: the backticked paths of each of its `Files:` lines outside a fence (after an optional
list bullet) add up; without such a comment, or with one that has no `Files:` line, the issue
declares none. When an issue declares one, the files API is read: each changed path, and a renamed
file's old path, is covered when it equals an allowed path, sits under one ending in `/`, or matches
one by spec 061's grammar (metrics.py's covered), or sits directly inside the default branch config's
`[changelog] fragments` folder. A path none covers reads NEEDS_DECISION, exit 5, `  files: <path> is outside
what #A allows` (`#A, #B allow` naming every issue declaring one), 20 such lines and then `  files: and
<k> more outside the allowed files`. It fails closed, NEEDS_DECISION, with `  files: #N's allowed files
can't be read: <why>` for a counting `Files:` line naming no backticked path or an empty, absolute, or
`..` one, and `  files: the thread of #N is cut off at 100 comments: its allowed files can't be read,
so a person looks` when #N's newest 100 comments hold no counting one and older ones went unread. The
maintainer's answer above lifts the `files:` lines with the other asks, for the heads it covers; a
verdict written after the PR opened widens nothing. A person's PR, and an agent's whose issues
declare none or that names no issue, is judged as before.

A draft PR is read as DRAFT, whatever its checks, plan, or zones, and the gate reads neither its
files nor its zones (D-67). A person's draft belongs to them: it enters triage once marked ready.
A draft the --bot-login authored has no owner once its session ended (#914): its line says so, and
a gate session marks it ready once nothing it waits on is open, then runs the gate again.

The base branch (D-75): the gate reads the checks on its head commit, one read of the commit's
statuses (which names the commit) and one of its check runs, every attempt, once per base branch
and pass, and keeps the newest run per check as it does the PR's own (#962). A completed check
there that failed (not one queued or running, nor a cancelled, skipped, neutral, or stale one)
makes the verdict FAILED, `  base: red: <check> failed on <base>@<sha>`, save for the PR whose
body has a line `Repairs: <URL>` naming it (after an optional list bullet, outside a fence): a
workflow run's URL names its every job, a job's or a check run's URL that one, a commit status's
exact target URL that status. A named failure prints `  base: repairs: ...` for the reviewer to
check the claim. A failure outside the code clears by re-running the failed run on the default
branch, and landing resumes once that run is green (#1310): a check run queued or running whose
previous attempt on the head (its check suite and name) failed reads `  base: pending: <check>
rerunning on <base>@<sha7>`, and a verdict that would otherwise read READY (or a later verdict
READY gives way to: UNREVIEWED, QUEUED) reads PENDING; a first attempt still running keeps the
verdict, as before, and a green rerun keeps it too.

A revert (spec 079): a PR the --bot-login authored whose body has a `Reverts #N` line (retro.py's
REVERTS) and a `Repairs:` line, both outside a fence, and that would otherwise read READY, reads
BLOCKED, `  revert: [autonomy] revert is <level>; a person merges it`, unless the default
branch's `[autonomy] revert` (read from its .github/shipmill.toml as REVIEW.md is; no config, or
no checkout, reads observe) is act. At act one read of the open shipmill-hold issues (`gh issue
list --label shipmill-hold`) is made for it, and an open hold reads act as propose, `  revert:
[autonomy] revert is act, propose under shipmill-hold #N; a person merges it`. Otherwise it is
judged as any PR: its review record, its plan, and its zones still apply, so it reads UNREVIEWED
or NEEDS_DECISION first when one of them holds it.

An open incident (#1481): when the default branch's .github/shipmill.toml (read as REVIEW.md is)
has [environments], a PR that would otherwise read READY reads BLOCKED, `  incident: #N is open on
<environment>'s latest deploy, <tag>: only a revert or a hotfix lands`, while an open issue labelled
its [operate] incident_label (`incident` by default) is open on an environment's latest deploy: it
was opened after that deploy started, or names its tag or commit as a whole word (an incident
operate opens names the bad tag and the rollback's on its hidden line). An incident from an earlier
deploy holds nothing. A revert lands through it (the App's, as above, or a PR titled `Revert "`), and
so does a hotfix (its base a hotfix/* branch, or release/X.Y when the config has [lanes.hotfix]).
Each environment's newest deployment (`repos/<o>/<r>/deployments?environment=<name>&per_page=1`) and
the open incidents (`gh issue list --label <label>`) are read once a pass, and only for a PR it would
hold; a repo without [environments], or no checkout, reads neither.

Closing keywords (D-76, D-79): a merge never closes an issue its PR is only part of, or one whose
check has not run. A commit's (gh pr view's) closing keyword counts as GitHub closes by it (#988):
any of close, closes, closed, fix, fixes, fixed, resolve, resolves, resolved as a whole word, in any
case, an optional colon, whitespace, then #N, or owner/repo#N or an issue's URL
https://github.com/owner/repo/issues/N naming the PR's own repo (#993; a /pull/N URL names
nothing), anywhere in its message, mid-line, in backticks, and in a fence too. The title and the body are read by
triage_state.py's keyword_closes, the rule shipped.py reads too (#416): in the body, a keyword
starting a line, after an optional list bullet, outside a fence; in the title, one anywhere outside
a code span; one mid-line in the body, in backticks, or naming owner/repo#N names nothing there. The
title is the squash commit's subject (D-96), so it reads as a commit (#987). Whoever opened it, it
is REFUSED, `  refused: <the title or commit <sha7>> closes #N, which the body lists as Part of #N`,
when the title's or a commit's keyword names an issue its body lists as `Part of #N`, and `  refused:
<the title, commit <sha7>, or the body> closes #N, an open issue with a ## Check: write Part of #N
instead` when one names an open issue of the repo whose body has a `## Check` section, and `  refused:
<where> closes #N, an open pull request` when one names an open pull request of the repo other than
this one (#1321). The issues and pull requests are read in one GraphQL query, only when a keyword
names one, or a commit names owner/repo#N or a URL. Read from the text alone, a title or a commit
message that writes a Dependabot alert as #N (`Dependabot #N`, `Dependabot alert #N`, `Dependabot
alerts #N and #M`, in any case), which GitHub reads as the repo's issue or pull request #N, is
REFUSED, `  refused: <the title or commit <sha7>> writes Dependabot alert #N: write alert N or its
URL`, one line for each number.

A review of the merging head (spec 055): an agent's PR that changes code and would otherwise read
READY reads UNREVIEWED, `  unreviewed: no review of <sha7> on record; review it, then record it with
shipmill review record`, until a review record covers the judged head. A PR changes code unless
every file it touches is documentation: a name ending .md, .mdx, .rst, or .txt, or a path under
docs/, and none of them the agents' instructions (under skills/, .claude/, or .claude-plugin/, or
named CLAUDE.md, AGENTS.md, or REVIEW.md), a renamed file's old path among them, read from the
files API once every listed path is documentation; a person's PR needs no record either. The records are
read from `repos/<o>/<r>/pulls/<n>/reviews`, one paginated read, only for such a PR: the
--bot-login's review whose body's first line is `<!-- shipmill:review merge -->` or `<!--
shipmill:review refuse -->`, and an APPROVED review by an OWNER, MEMBER, or COLLABORATOR, not a
bot, whose body carries no agent marker. One covers the judged head when its commit_id is that
head or a head whose own change is the same, as for the maintainer's answer above. The
--bot-login's newest record that covers it counts: a refuse keeps the PR UNREVIEWED, `
unreviewed: the newest review of <sha7> on record refuses it on N confirmed finding(s); ...` when
the line right after its marker is exactly `<!-- shipmill:findings confirmed=N rejected=N minor=N
-->` (spec 075), else `  unreviewed: the newest review of <sha7> on record refuses it on findings
no second reviewer checked; ...`; a merge, with or without that line, or a person's approval, lets
it read READY.

The land window (spec 056): when the base's .github/shipmill.toml has [land.window], the gate
reads it with `shipmill --repo <checkout> window --json --ref <the base>`, run as `decide
classify` is, once per base branch and pass for every open PR there, and the labels of a PR
that would read READY with one `gh pr view N --json labels`; a PR into another branch than
the one the config was read from is not held (one window per repo, for PRs into the default
branch). A PR carrying one of its `labels` and none
of its `bypass_labels` that would otherwise read READY reads QUEUED: while the window is closed,
`  queued: held by the land window (<its held labels>); opens <YYYY-MM-DD HH:MM> <timezone>`,
and while it is open and `next_merge` is later than now, `  queued: spacing: the next held merge
after <HH:MM> <timezone>`. A red, pending, conflicting, refused, unreviewed, or
held-for-a-decision PR keeps that verdict: QUEUED only takes READY's place.

Exit codes: 0 every PR is ready; 1 a check failed, on the PR's head or the base's (D-75),
or gh failed; 3 a check is still pending, on the PR's head or a base check rerunning a failure
(#1310) (or --wait timed out); 4 a PR is not open, conflicts, or holds an unhandled veto
(#1309) or one a thread cut off at 100 comments can't place (#1330), or is the App's revert
below [autonomy] revert = "act" (spec 079), or an open incident on the latest deploy holds it
(#1481); 5 a PR needs the
maintainer's decision; 6 an agent's PR is refused for its plan, a spec PR names no open feature
issue, or a PR's closing keyword names a Part of issue, an open one with a ## Check (D-76), or an
open pull request, or its title or a commit writes a Dependabot alert as #N (#1321); 7 a PR only
the maintainer merges, by hand (a `never` zone); 8 a draft PR (D-67); 9 an agent's code PR no review record
covers (spec 055); 10 a held PR waits for the land window or its spacing (spec 056); 2 bad
arguments, a base branch the checkout lacks, a git failure, a REVIEW.md, docs/product.md, or
config the gate can't read, or a `shipmill decide classify` or `shipmill window` that fails or
prints what the gate can't read. With several PRs the exit code is
the worst verdict's, ranked 0, 1, 3, 10, 9, 4, 8, 5, 7, 6.

--wait polls while the worst verdict is PENDING, or is NEEDS_DECISION and a NEEDS_DECISION PR has
a check still pending on its own head (#1028): the question waits until its CI finished, and the
exit code and its ranking stay as above. A base check is pending only while it reruns a failure
(#1310), a PR with no checks has none pending, and every other verdict, UNREVIEWED and QUEUED
too, stops the wait.
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
from collections.abc import Callable, Container, Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import ModuleType

GREEN = {"SUCCESS", "NEUTRAL", "SKIPPED"}
READY, FAILED, PENDING, BLOCKED, NEEDS_DECISION, REFUSED, MAINTAINER_ONLY, DRAFT = 0, 1, 3, 4, 5, 6, 7, 8
UNREVIEWED = 9  # an agent's code PR no review record covers (spec 055)
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
    UNREVIEWED: "UNREVIEWED",
}
# the worst verdict last: MAINTAINER_ONLY ranks above NEEDS_DECISION and below REFUSED (spec 030); DRAFT
# ranks above BLOCKED and below the verdicts that ask something of the maintainer (D-52, kept by D-67);
# QUEUED (spec 056) and UNREVIEWED (spec 055) rank between PENDING and BLOCKED, QUEUED first: it
# only waits, an unreviewed PR waits on a review
RANK = (READY, FAILED, PENDING, QUEUED, UNREVIEWED, BLOCKED, DRAFT, NEEDS_DECISION, MAINTAINER_ONLY, REFUSED)

# github-ship-watch's watch_state.py: one reading of the config's [agents] and of the plugin's
# pinned CLI for every skill script
WATCH_STATE = Path(__file__).resolve().parents[2] / "github-ship-watch" / "scripts" / "watch_state.py"
# github-issue-triage's decisions.py: the zone table's one copy, its ZONES and LEVELS
DECISIONS = Path(__file__).resolve().parents[2] / "github-issue-triage" / "scripts" / "decisions.py"
# github-issue-triage's triage_state.py: the closing-keyword rule and the ## Check section, one
# reading for every script (#416, D-76)
TRIAGE_STATE = Path(__file__).resolve().parents[2] / "github-issue-triage" / "scripts" / "triage_state.py"
# github-ship-watch's retro.py: the needs-decision question, its trusted answers, and whether
# that answer takes the (recommended) option (S-030-18), one reading for every script (spec 055)
RETRO = Path(__file__).resolve().parents[2] / "github-ship-watch" / "scripts" / "retro.py"
# github-issue-triage's specs.py: same-approval compares a spec PR's answered and judged heads (D-81)
SPECS = Path(__file__).resolve().parents[2] / "github-issue-triage" / "scripts" / "specs.py"
# github-ship-watch's metrics.py: a plan's `Files:` line and spec 061's path grammar, one reading of
# a path a `Files:` line names for every script (spec 085)
METRICS = Path(__file__).resolve().parents[2] / "github-ship-watch" / "scripts" / "metrics.py"
# a body's "Part of #N", as triage_state.py's closes() reads a partial PR
PART_OF = re.compile(r"\bpart of:?\s+#([0-9]+)\b", re.IGNORECASE)
CONFIG = ".github/shipmill.toml"
REVERT_LEVELS = ("observe", "propose", "act")  # [autonomy] revert, observe by default (spec 079)
HOLD_LABEL = "shipmill-hold"  # shipmill's autonomy.HOLD_LABEL
INCIDENT_LABEL = "incident"  # the default of [operate] incident_label (#1481)
INCIDENT_LIMIT = 1000  # the open incidents read; as many stops the gate rather than judging a partial list
REVERT_TITLE = 'Revert "'  # GitHub's own revert pull request's title (#1481)
HOTFIX_BRANCH = re.compile(r"hotfix/.+")  # a hotfix's base branch, whatever the config (#1481)
RELEASE_BRANCH = re.compile(r"release/[0-9]+\.[0-9]+")  # the [lanes.hotfix] lane's branch, release/X.Y

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
_SERVES = re.compile(r"^  serves: \S.*$")  # a component goal's serves line (spec 071)
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
    base_pending: tuple[str, ...] = ()  # the base head's checks rerunning after a failure, not green yet (#1310)
    unreviewed: str = ""  # why an agent's code PR that reads READY otherwise has no review record (spec 055)
    queued: tuple[str, ...] = ()  # why a held PR waits for the land window or its spacing (spec 056)
    vetoes: tuple[str, ...] = ()  # the unhandled vetoes of a decision taken at notify (D-48, #1309)
    spec_asks: tuple[str, ...] = ()  # the approved specs it changes past format: the answer lifts them (#1311)
    revert: str = ""  # why the App's revert PR waits for a person below [autonomy] revert = "act" (spec 079)
    incidents: tuple[str, ...] = ()  # the open incidents on the latest deploy that hold it (#1481)
    files: tuple[str, ...] = ()  # an agent's changed files its issues don't allow, or why that can't be read (spec 085)

    @property
    def verdict(self) -> int:
        if self.state != "OPEN":
            return BLOCKED
        if self.draft:
            return DRAFT
        if self.mergeable == "CONFLICTING" or self.vetoes:
            return BLOCKED
        if self.refused or self.spec:
            return REFUSED
        if self.never:
            return MAINTAINER_ONLY
        if self.asks or self.spec_asks or self.files:
            return NEEDS_DECISION
        if self.base_red or any(c.done and c.conclusion not in GREEN for c in self.checks):
            return FAILED
        if (
            not self.checks
            or any(not c.done for c in self.checks)
            or self.mergeable != "MERGEABLE"
            or self.base_pending
        ):
            return PENDING
        if self.unreviewed:
            return UNREVIEWED
        if self.revert or self.incidents:  # only an otherwise READY PR carries them (spec 079, #1481)
            return BLOCKED
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
    revert: str = "observe"  # the config's [autonomy] revert (spec 079)
    environments: tuple[str, ...] = ()  # the config's [environments], whose latest deploys an incident holds (#1481)
    incident_label: str = INCIDENT_LABEL  # the config's [operate] incident_label
    hotfix_lane: bool = False  # the config has [lanes.hotfix]: a PR into release/X.Y is a hotfix
    config: str | None = None  # its .github/shipmill.toml, whose lanes' release workflows base_head reads (#1485)
    fragments: str | None = None  # the config's [changelog] fragments folder (spec 013), covered by any allowance

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


def key_of(entry: dict) -> tuple[str, ...]:
    """Which check an entry is a run of: a CheckRun's (workflowName, name), a StatusContext's context"""
    if "state" in entry and "status" not in entry:
        return ("status", str(entry.get("context", "?")))
    return ("run", str(entry.get("workflowName") or ""), str(entry.get("name", "?")))


def newest_entries(rollup: Iterable[dict]) -> list[dict]:
    """One check per CheckRun (workflowName, name) or StatusContext context: a head checked
    twice (a PR closed and reopened) lists both runs, and only the newest counts (#962). The
    later start wins; without both starts the later rollup entry does, except that a run
    not started and not done is never replaced by a started one, so a run in flight is
    never hidden behind an older pass wherever the rollup lists it"""
    newest: dict[tuple[str, ...], tuple[datetime | None, dict]] = {}
    for entry in rollup:
        key = key_of(entry)
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
    goal's `  measure: ...` line right under its item line (spec 027), and its `  serves: ...`
    line right under that or its item line (spec 071), are skipped. `shipmill product check`
    holds the full grammar"""
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
        # the lines the next may be: a goal's measure line, then its serves line, read no more from
        follows: tuple[re.Pattern[str], ...] = ()
        for number, raw in listed:
            line = raw.rstrip()
            if not line.strip():
                follows = ()
                continue
            tail = next((i for i, form in enumerate(follows) if form.match(line)), None)
            if tail is not None:  # specs 027 and 071
                follows = follows[tail + 1 :]
                continue
            item = _ITEM.match(line)
            if item is None or item.group(1) != prefix:
                raise GateError(f"{file}:{number}: not a `- {prefix}-<n>: <text>` item; run `shipmill product check`")
            ids.add(f"{prefix}-{item.group(2)}")
            follows = (_MEASURE, _SERVES) if prefix == "G" else ()
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


def direction_edits(files: Iterable[str]) -> list[str]:
    """The files that edit the product's direction, docs/product.md or one under docs/product/,
    which only the maintainer changes (D-34); fleet.py queue reads a spec PR's by it too"""
    return [f for f in files if f == DIRECTION or f.startswith(DIRECTION_DIR)]


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
    revert = REVERT_LEVELS[0] if config is None else revert_level(config, where)
    environments, label, hotfix = ((), INCIDENT_LABEL, False) if config is None else operations(config, where)
    fragments = None if config is None else fragments_folder(config, where)
    return Base(ids, reviews, agents, ref, maintainers, window, revert, environments, label, hotfix, config, fragments)


def fragments_folder(text: str, where: str) -> str | None:
    """The config's [changelog] fragments folder (spec 013), whose files every pull request may add
    (spec 085); None when it sets none, or names no folder relative to the repo's root as
    changelog_guard.py reads one, so no file is covered by it: the safe side. On Python 3.10, without
    tomllib, a plain string key of a plain [changelog] table is read"""
    ws = watch_state()
    if ws.tomllib is None:
        folder: object = ws.toml_string(ws.toml_tables(text).get("changelog", ""), "fragments")
    else:
        try:
            raw = ws.tomllib.loads(text)
        except ws.tomllib.TOMLDecodeError as exc:
            raise GateError(f"{where}: {exc}") from None
        table = raw.get("changelog")
        folder = table.get("fragments") if isinstance(table, dict) else None
    if not isinstance(folder, str) or not folder or folder == ".":
        return None
    posix = PurePosixPath(folder)
    if posix.is_absolute() or ".." in posix.parts or posix.as_posix() != folder:
        return None
    return folder


def operations(text: str, where: str) -> tuple[tuple[str, ...], str, bool]:
    """The config's [environments] names, its [operate] incident_label (read only when it has
    environments), and whether it has [lanes.hotfix] (#1481), read as watch_state.py reads them:
    a form it can't read stops the gate"""
    ws = watch_state()
    policy = Path(where)
    try:
        if ws.tomllib is None:
            envs = ws.environments_310(text, policy)
            label = ws.incident_label_310(text, policy) if envs else INCIDENT_LABEL
            hotfix = "lanes.hotfix" in ws.toml_tables(text)
        else:
            try:
                raw = ws.tomllib.loads(text)
            except ws.tomllib.TOMLDecodeError as exc:
                raise GateError(f"{where}: {exc}") from None
            envs = ws.environments_toml(raw, policy)
            label = ws.incident_label_toml(raw, policy) if envs else INCIDENT_LABEL
            lanes = raw.get("lanes")
            hotfix = isinstance(lanes, dict) and "hotfix" in lanes
    except ws.Refused as refused:
        raise GateError(str(refused).removeprefix("error: ")) from None
    return tuple(str(e.name) for e in envs), str(label), hotfix


def revert_level(text: str, where: str) -> str:
    """The config's [autonomy] revert (spec 079), observe when it doesn't set it; any other
    value than the three levels stops the gate, as shipmill's own reading refuses it. On Python
    3.10, without tomllib, a plain string key of a plain [autonomy] table is read, and any other
    form stops the gate rather than being misread"""
    ws = watch_state()
    if ws.tomllib is None:
        try:
            value: object = ws.autonomy_string_310(text, Path(where), "revert")
        except ws.Refused as refused:
            raise GateError(str(refused).removeprefix("error: ")) from None
    else:
        try:
            raw = ws.tomllib.loads(text)
        except ws.tomllib.TOMLDecodeError as exc:
            raise GateError(f"{where}: {exc}") from None
        table = raw.get("autonomy", {})
        if not isinstance(table, dict):
            raise GateError(f"{where}: autonomy is not a table")
        value = table.get("revert")
    if value is None:
        return REVERT_LEVELS[0]
    if not isinstance(value, str) or value not in REVERT_LEVELS:
        raise GateError(f"{where}: [autonomy] revert must be one of {list(REVERT_LEVELS)}, got {value!r}")
    return value


def is_revert(body: str) -> bool:
    """Whether the body has a `Reverts #N` line, as retro.py reads one (spec 058), and a
    `Repairs:` line, both outside a fence: the revert `shipmill revert open` opens (spec 079)"""
    reverts = retro().REVERTS
    return bool(repairs_of(body)) and any(reverts.match(line) for line in unfenced(body))


def revert_hold(level: str, number: int, repo: str | None) -> str:
    """Why the App's otherwise READY revert waits for a person (spec 079), or "" at act: below
    act a person merges it, and an open shipmill-hold issue reads act as propose (D-15), read
    only at act"""
    if level != "act":
        return f"[autonomy] revert is {level}; a person merges it"
    holds = open_holds(number, repo)
    if not holds:
        return ""
    named = ", ".join(f"#{n}" for n in holds)
    return f"[autonomy] revert is act, propose under {HOLD_LABEL} {named}; a person merges it"


def open_holds(number: int, repo: str | None) -> list[int]:
    """The open shipmill-hold issues' numbers, oldest first"""
    cmd = ["gh", "issue", "list", "--label", HOLD_LABEL, "--state", "open", "--json", "number", "--limit", "100"]
    if repo:
        cmd += ["-R", repo]
    data = json.loads(gh(cmd, number))
    if not isinstance(data, list) or not all(isinstance(e, dict) and isinstance(e.get("number"), int) for e in data):
        raise GateError(f"gh issue list --label {HOLD_LABEL} printed no list of issues: {str(data)[:200]}")
    return sorted(e["number"] for e in data)


def lands_through_incident(data: dict, own: bool, base: Base) -> bool:
    """Whether the PR lands while an incident is open (#1481): a revert (the App's, as `shipmill
    revert open` opens it, or one titled as GitHub's own revert titles it) or a hotfix (into a
    hotfix/* branch, or into release/X.Y when the config has [lanes.hotfix])"""
    if (own and is_revert(str(data.get("body") or ""))) or str(data.get("title") or "").startswith(REVERT_TITLE):
        return True
    branch = str(data["baseRefName"])
    return HOTFIX_BRANCH.fullmatch(branch) is not None or (
        base.hotfix_lane and RELEASE_BRANCH.fullmatch(branch) is not None
    )


@dataclass(frozen=True)
class Deploy:
    """An environment's newest deployment, as GitHub lists it"""

    environment: str
    tag: str  # its ref, refs/tags/ left off
    sha: str
    started: datetime


@dataclass(frozen=True)
class Incident:
    number: int
    text: str  # its title and body
    opened: datetime

    def on(self, deploy: Deploy) -> bool:
        """Whether it is open on that deploy: opened after it started, or naming its tag or its
        commit (a short sha of 7 or more), a whole word (an operate incident names the bad tag
        and the rollback's in its hidden line, so one a rollback left open still names it)"""
        if self.opened >= deploy.started:
            return True
        named = r"(?<![\w.\-/]){}(?![\w\-/]|\.\w)"
        tag = deploy.tag and re.search(named.format(re.escape(deploy.tag)), self.text)
        shas = re.findall(r"(?<![\w])[0-9a-f]{7,40}(?![\w])", self.text)
        return bool(tag) or any(deploy.sha.startswith(s) for s in shas)


class Incidents:
    """Each environment's latest deploy and the open incidents, read once a pass, and only for a
    PR that would otherwise read READY in a repo whose config has [environments] (#1481)"""

    def __init__(self, repo: str | None) -> None:
        self.repo = repo
        self.deploys: dict[str, Deploy | None] = {}
        self.open: dict[str, list[Incident]] = {}

    def holds(self, base: Base, number: int) -> tuple[str, ...]:
        """One line for each open incident on an environment's latest deploy"""
        lines = []
        for environment in base.environments:
            if environment not in self.deploys:
                self.deploys[environment] = latest_deploy(environment, number, self.repo)
            deploy = self.deploys[environment]
            if deploy is None:
                continue
            if base.incident_label not in self.open:
                self.open[base.incident_label] = open_incidents(base.incident_label, number, self.repo)
            lines += [
                f"#{i.number} is open on {environment}'s latest deploy, {deploy.tag or deploy.sha[:7]}: only a"
                " revert or a hotfix lands"
                for i in self.open[base.incident_label]
                if i.on(deploy)
            ]
        return tuple(lines)


def latest_deploy(environment: str, number: int, repo: str | None) -> Deploy | None:
    """The environment's newest deployment, whatever its state: GitHub lists them newest first"""
    query = ["-f", f"environment={environment}", "-f", "per_page=1"]
    cmd, env = api(["-X", "GET", "repos/{owner}/{repo}/deployments", *query], repo)
    data = json.loads(gh(cmd, number, env))
    what = f"the deployments of {environment}"
    if not isinstance(data, list) or not all(isinstance(d, dict) for d in data):
        raise GateError(f"{what} are no list of deployments: {str(data)[:200]}")
    if not data:
        return None
    newest = data[0]
    ref, sha = newest.get("ref"), newest.get("sha")
    if not isinstance(ref, str) or not isinstance(sha, str):
        raise GateError(f"{what}: a deployment with no ref or sha: {str(newest)[:200]}")
    started = moment(newest.get("created_at"), f"{what}: a deployment's created_at")
    return Deploy(environment, ref.removeprefix("refs/tags/"), sha, started)


def open_incidents(label: str, number: int, repo: str | None) -> list[Incident]:
    """The open issues labelled label, oldest first"""
    fields = "number,title,body,createdAt"
    cmd = ["gh", "issue", "list", "--label", label, "--state", "open", "--json", fields, "--limit", str(INCIDENT_LIMIT)]
    if repo:
        cmd += ["-R", repo]
    data = json.loads(gh(cmd, number))
    if not isinstance(data, list) or not all(isinstance(e, dict) and isinstance(e.get("number"), int) for e in data):
        raise GateError(f"gh issue list --label {label} printed no list of issues: {str(data)[:200]}")
    if len(data) >= INCIDENT_LIMIT:
        raise GateError(f"{INCIDENT_LIMIT} or more open issues labelled {label}: the gate judges no partial list")
    found = [
        Incident(
            e["number"],
            f"{e.get('title') or ''}\n{e.get('body') or ''}",
            moment(e.get("createdAt"), "an incident's createdAt"),
        )
        for e in data
    ]
    return sorted(found, key=lambda i: i.number)


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
    renamed, ...); a list short of changedFiles stops the gate. A renamed file's old path is kept
    in data["previous"]: the review check reads it as a file the PR touches too (spec 055)"""
    changed = int(data.get("changedFiles") or 0)
    cmd, env = api(["--paginate", f"repos/{{owner}}/{{repo}}/pulls/{number}/files?per_page=100", "--jq", ".[]"], repo)
    entries = [json.loads(line) for line in gh(cmd, number, env).splitlines() if line.strip()]
    statuses = {str(e["filename"]): str(e["status"]) for e in entries}
    data["previous"] = tuple(str(e["previous_filename"]) for e in entries if e.get("previous_filename"))
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


def issues_read(numbers: list[int], wanted: str = "state", pull: str = "", on_pull: str = "") -> list[str]:
    """`gh api`'s arguments for the GraphQL read of the numbers, each under the alias i<N>, an issue
    with the wanted fields, and a pull request with the on_pull fields when any are named (#1321),
    after pull (a pullRequest field of the same repository, or nothing); the github-pr-triage eval
    cases record this read, so a change here re-records it there"""
    as_pull = f" ... on PullRequest {{ {on_pull} }}" if on_pull else ""
    fields = " ".join(
        f"i{n}: issueOrPullRequest(number: {n}) {{ __typename ... on Issue {{ {wanted} }}{as_pull} }}" for n in numbers
    )
    query = (
        "query($owner: String!, $repo: String!) { repository(owner: $owner, name: $repo) { nameWithOwner "
        f"{pull + ' ' if pull else ''}{fields} }} }}"
    )
    return ["graphql", "-F", "owner={owner}", "-F", "repo={repo}", "-f", f"query={query}"]


def issues_of(
    numbers: list[int], number: int, repo: str | None, wanted: str = "state", on_pull: str = ""
) -> tuple[str, dict[int, dict | None]]:
    """The repo's owner/name and, for each number, its issue or pull request ({__typename} and, for
    an issue, the wanted fields, for a pull request the on_pull ones), or None for a number the repo
    lacks: one GraphQL read. A NOT_FOUND error for one of the numbers is an answer; any other
    failure exits 1, as gh's always has"""
    found, nodes = repository_of(numbers, number, repo, wanted, on_pull=on_pull)
    return found["nameWithOwner"], nodes


def repository_of(
    numbers: list[int], number: int, repo: str | None, wanted: str = "state", pull: str = "", on_pull: str = ""
) -> tuple[dict, dict[int, dict | None]]:
    """issues_of's read, with pull's field too: the repository object GraphQL answers and the
    numbers' nodes"""
    aliases = {f"i{n}": n for n in numbers}
    cmd, env = api(issues_read(numbers, wanted, pull, on_pull), repo)
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
    return found, {n: found.get(alias) for alias, n in aliases.items()}


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


def base_head(branch: str, number: int, repo: str | None, config: str | None = None) -> tuple[str, list[dict]]:
    """The base branch's head commit and its checks, the newest run of each as newest_checks reads
    the PR's (#962): one read of the commit's statuses, which names the commit, then one of its
    check runs, every page, every attempt (filter=all; the default lists only the latest). Each
    check is rollup-shaped, with the URLs a Repairs: line may name, and marked rerunning when it
    is not done and its previous attempt on the head failed (#1310). A failed job of a release
    workflow the default branch's config dispatches is left out (#1485, not_released)"""

    def read(args: list[str]) -> str:
        cmd, env = api(args, repo)
        return gh(cmd, number, env)

    sha, entries = head_checks(branch, read)
    return sha, not_released(entries, config, read)


RELEASE_KEYS = ("dispatch", "after_publish")  # a lane's workflows shipmill dispatches for a tag


def not_released(entries: list[dict], config: str | None, read: Callable[[list[str]], str]) -> list[dict]:
    """The head's checks but each failed job of a lane's release workflow dispatched (#1485):
    shipmill dispatches it on the branch for a tag, so GitHub records its run on the head though
    the run tests the tag; github-ship-watch's release rows report its failure. A failed job's
    workflow run is read, once, only when the config's lanes name a release workflow"""
    failed = {run for e in entries if is_red(e) and (run := run_of(e)) is not None}
    workflows = release_workflows(config, CONFIG) if config is not None and failed else frozenset()
    if not workflows:
        return entries
    runs = {r for r in sorted(failed) if dispatched_release(read_run(r, read), workflows)}
    return [e for e in entries if not (is_red(e) and run_of(e) in runs)]


def read_run(run: int, read: Callable[[list[str]], str]) -> dict:
    data = json.loads(read([f"repos/{{owner}}/{{repo}}/actions/runs/{run}"]))
    if not isinstance(data, dict):
        raise GateError(f"workflow run {run} is not an object: {str(data)[:200]}")
    return data


def is_red(entry: dict) -> bool:
    """A check that completed failed, as base_failures reads red"""
    check = check_of(entry)
    return check.done and check.conclusion not in NOT_RED


def run_of(entry: dict) -> int | None:
    """The workflow run an Actions job's check run belongs to, from its URLs"""
    for url in entry.get("urls") or ():
        found = _ACTIONS_URL.fullmatch(url)
        if found is not None:
            return int(found.group(1))
    return None


def dispatched_release(run: dict, workflows: frozenset[str]) -> bool:
    """Whether a workflow run is one of the lanes' release workflows, started by workflow_dispatch:
    its path is .github/workflows/<the file a lane names>. The same workflow on a push, a pull
    request, or a schedule tests the head, and so does a dispatched workflow no lane names"""
    path = run.get("path")
    if run.get("event") != "workflow_dispatch" or not isinstance(path, str):
        return False
    return path.split("@", 1)[0] in {f".github/workflows/{w}" for w in workflows}


def release_workflows(text: str, where: str) -> frozenset[str]:
    """The workflow files the config's lanes name in dispatch or after_publish (#1485). Read with
    tomllib on 3.11+; on 3.10, plain [lanes.<name>] tables with each key one array of strings,
    and any other form stops the gate rather than being misread"""
    ws = watch_state()
    if ws.tomllib is None:
        return release_workflows_310(text, where, ws)
    try:
        raw = ws.tomllib.loads(text)
    except ws.tomllib.TOMLDecodeError as exc:
        raise GateError(f"{where}: {exc}") from None
    lanes = raw.get("lanes", {})
    if not isinstance(lanes, dict):
        raise GateError(f"{where}: lanes is not a table")
    found: set[str] = set()
    for name, table in lanes.items():
        if not isinstance(table, dict):
            raise GateError(f"{where}: lanes.{name} is not a table")
        for key in RELEASE_KEYS:
            value = table.get(key, [])
            if not isinstance(value, list) or not all(isinstance(w, str) for w in value):
                raise GateError(f"{where}: lanes.{name} {key} is not an array of workflow files: {value!r}")
            found.update(value)
    return frozenset(found)


def release_workflows_310(text: str, where: str, ws: ModuleType) -> frozenset[str]:
    """release_workflows on Python 3.10, without tomllib"""
    unreadable = GateError(f"{where}: can't read [lanes] on Python 3.10: use 3.11+ or plain [lanes.<name>] tables")
    tables = ws.toml_tables(text)
    if re.search(r"^\s*[\"']?lanes[\"']?\s*[.=]", tables.get("", ""), re.MULTILINE) or not ws.blank(
        tables.get("lanes", "")
    ):
        raise unreadable
    found: set[str] = set()
    for name, body in tables.items():
        parts = name.split(".")
        if parts[0] != "lanes" or len(parts) == 1:
            continue
        if len(parts) != 2:
            raise unreadable
        for key in RELEASE_KEYS:
            opened = re.search(rf"^\s*[\"']?{key}[\"']?\s*=\s*\[", body, re.MULTILINE)
            if opened is None:
                if re.search(rf"^\s*[\"']?{key}[\"']?\s*=", body, re.MULTILINE):
                    raise unreadable
                continue
            found.update(array_strings(body[opened.end() :], unreadable))
    return frozenset(found)


_ARRAY_TOKEN = re.compile(r"\"([^\"\\\n]*)\"|'([^'\n]*)'|(\])|#[^\n]*|[\s,]+|.")


def array_strings(rest: str, unreadable: GateError) -> list[str]:
    """The strings of a TOML array of plain strings, read from just past its [ to its ]: a
    comment is skipped, quotes or a ] in it included, and anything else stops the gate"""
    strings: list[str] = []
    for token in _ARRAY_TOKEN.finditer(rest):
        double, single, close = token.groups()
        if close is not None:
            return strings
        if double is not None or single is not None:
            strings.append(double if double is not None else single)
        elif not token.group().startswith("#") and token.group().strip(" \t\r\n,"):
            raise unreadable
    raise unreadable


def head_checks(branch: str, read: Callable[[list[str]], str]) -> tuple[str, list[dict]]:
    """base_head's reading of a branch's head and its checks, through read, which runs `gh api`
    with the arguments given and returns its output; base_red.py reads a red default branch by
    it (spec 079), so the two never disagree on which check is red or rerunning"""
    ref = urllib.parse.quote(branch, safe="")
    combined = json.loads(read([f"repos/{{owner}}/{{repo}}/commits/{ref}/status?per_page=100"]))
    sha = combined.get("sha") if isinstance(combined, dict) else None
    statuses = combined.get("statuses") if isinstance(combined, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{7,64}", sha) or not isinstance(statuses, list):
        raise GateError(f"the status of {branch}'s head is not a combined status: {combined!r}")
    if len(statuses) < int(combined.get("total_count") or 0):
        raise GateError(f"{branch}@{sha[:7]} has more than 100 commit statuses; the gate judges no partial list")
    entries = [status_entry(s, branch) for s in statuses]
    path = f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs?per_page=100&filter=all"
    lines = read(["--paginate", path, "--jq", ".check_runs[]"]).splitlines()
    entries += [run_entry(json.loads(line), branch) for line in lines if line.strip()]
    return sha, [{**entry, "rerunning": rerunning(entry, entries)} for entry in newest_entries(entries)]


def rerunning(entry: dict, entries: list[dict]) -> bool:
    """Whether a check not done is a rerun of a failure (#1310): the newest earlier attempt of the
    same check (its check suite and name) that completed failed, as base_failures reads red. A
    commit status lists its newest state alone, so it is never a rerun here"""
    if check_of(entry).done:
        return False
    earlier = [e for e in entries if e is not entry and key_of(e) == key_of(entry) and check_of(e).done]
    if not earlier:
        return False
    oldest = datetime.min.replace(tzinfo=timezone.utc)  # noqa: UP017 (3.10)
    previous = max(earlier, key=lambda e: started_of(e) or oldest)
    return check_of(previous).conclusion not in NOT_RED


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
        "app": app.get("id") if isinstance(app := run_.get("app"), dict) else None,  # base_red.py's (spec 079)
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


def base_failures(
    branch: str, sha: str, entries: list[dict], body: str
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """The base head's failed checks no Repairs: line of the body names, those one does, and the
    checks rerunning after a failure there, which are not green yet (D-75, #1310)"""
    named = repairs_of(body)
    red: list[str] = []
    repairs: list[str] = []
    pending: list[str] = []
    for entry in entries:
        check = check_of(entry)
        if check.done and check.conclusion not in NOT_RED:
            (repairs if repaired(entry, named) else red).append(f"{check.name} failed on {branch}@{sha[:7]}")
        elif entry.get("rerunning"):
            pending.append(f"{check.name} rerunning on {branch}@{sha[:7]}")
    return tuple(red), tuple(repairs), tuple(pending)


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
    owner/repo#N, it names nothing. The title is read as the squash commit it becomes (D-96, #987).
    The title's or a commit's keyword naming an issue its body lists as Part of #N, then the
    title's, a commit's, or the body's naming an open issue of the repo with a ## Check section,
    read once in GraphQL for every number the keywords name; a commit naming owner/repo#N or an
    issue's URL takes that read even when nothing else is named, since it names the PR's repo. In
    the same read, a keyword naming an open pull request other than this one (#1321). And, read
    from the text alone, a title or a commit writing a Dependabot alert as #N (dependabot_alerts)"""
    ts = triage_state()
    body = str(data.get("body") or "")
    title_text = str(data.get("title") or "")
    messages = commit_messages(data, number)
    alerts = [("the title", n) for n in dependabot_alerts(title_text)]
    alerts += [(f"commit {sha}", n) for sha, text in messages for n in dependabot_alerts(text)]
    parts = {int(n) for n in PART_OF.findall(body)}
    title = [("the title", n) for n in sorted(ts.keyword_closes(title_text, ""))]
    commits = [(f"commit {sha}", ref) for sha, text in messages for ref in commit_closes(ts, text)]
    in_body = [("the body", n) for n in closed_by(ts, body)]
    read: tuple[str, dict[int, dict | None]] | None = None
    if any(owner is not None for _, (owner, _) in commits):
        every = {n for _, n in title + in_body} | {n for _, (_, n) in commits}
        wanted = sorted(n for n in every if 0 < n <= GRAPHQL_INT)
        read = issues_of(wanted, number, repo, "state body", "state") if wanted else ("", {})
    own = read[0].lower() if read is not None else ""
    # the title and the commits: what lands as commits under a squash merge
    landed = title + [(where, n) for where, (owner, n) in commits if owner is None or owner.lower() == own]
    parted = [(where, n) for where, n in landed if n in parts]
    problems = [f"{where} closes #{n}, which the body lists as Part of #{n}" for where, n in parted]
    problems += [f"{where} writes Dependabot alert #{n}: write alert {n} or its URL" for where, n in alerts]
    named = [pair for pair in landed if pair not in parted] + in_body
    numbers = sorted({n for _, n in named if 0 < n <= GRAPHQL_INT})
    if not numbers:
        return problems
    _, nodes = read if read is not None else issues_of(numbers, number, repo, "state body", "state")
    for where, n in named:
        node = nodes.get(n)
        if not isinstance(node, dict) or node.get("state") != "OPEN":
            continue
        if node.get("__typename") == "PullRequest" and n != number:
            problems.append(f"{where} closes #{n}, an open pull request")
        elif node.get("__typename") == "Issue" and ts.CHECK.search(str(node.get("body") or "")) is not None:
            problems.append(f"{where} closes #{n}, an open issue with a ## Check: write Part of #{n} instead")
    return problems


# a Dependabot alert written as #N (#1321): `Dependabot #N`, `Dependabot alert #N`, `Dependabot
# alerts #N and #M`, `#N, #M` and `#N, and #M` too, in any case; each #N of it is an alert's number,
# which GitHub reads as the repo's issue or pull request of that number
DEPENDABOT = re.compile(
    r"\bdependabot(?:\s+alerts?)?:?\s+#[0-9]+\b(?:\s*(?:,\s*(?:and\s+)?|and\s+|&\s*)#[0-9]+\b)*", re.IGNORECASE
)


def dependabot_alerts(text: str) -> list[int]:
    """The alert numbers a text writes as #N after Dependabot, in order, each once"""
    found: list[int] = []
    for match in DEPENDABOT.finditer(text):
        found += [n for n in map(int, re.findall(r"#([0-9]+)", match.group(0))) if n not in found]
    return found


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


def beside(name: str, path: Path) -> ModuleType:
    """A sibling skill's script that imports from its own folder, loaded as when it runs from there"""
    if name not in _MODULES:
        folder = str(path.parent)
        sys.path.insert(0, folder)
        try:
            _MODULES[name] = load(name, path)
        finally:
            sys.path.remove(folder)
    return _MODULES[name]


def retro() -> ModuleType:
    """retro.py, which imports metrics from its own folder"""
    return beside("shipmill_retro", RETRO)


def specs_script() -> ModuleType:
    """specs.py, which imports decisions from its own folder"""
    return beside("shipmill_specs", SPECS)


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
OPENED_BY = "author { __typename login } authorAssociation"  # who opened the pull request (S-055-7)
FULL_SHA = re.compile(r"[0-9a-f]{40}")
# the head a question on a pull request was asked at, in full: its hidden line under `CI on <sha7>: ...`
# (needs-decision.md); a 7-hex prefix is no name, since a commit sharing it can be made to order
ASKED_AT = re.compile(r"<!-- shipmill:head ([0-9a-f]{40}) -->")
DIFFERS = "answered at {sha7}, and the change differs since"
NOT_RECOMMENDED = "the answer doesn't take the recommended option"
RELAY_NOT_COUNTED = "relay not counted: {reason}"  # a relay out of its grammar (D-93)
NO_HEAD = "the question names no head: ask again with its `<!-- shipmill:head <sha> -->` line"


def pull_field(number: int) -> str:
    """The GraphQL field of pull request number's thread"""
    return f"pullRequest(number: {number}) {{ {OPENED_BY} {THREAD} {FORCE_PUSHES} }}"


def thread_read(number: int) -> list[str]:
    """`gh api`'s arguments for the GraphQL read of pull request number's thread"""
    query = (
        "query($owner: String!, $repo: String!) { repository(owner: $owner, name: $repo) { "
        f"{pull_field(number)} }} }}"
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


def named_issues(data: dict, number: int) -> list[int]:
    """The issues the pull request closes (triage_state.py's keyword_closes) or names as Part of #N"""
    body = str(data.get("body") or "")
    refs = triage_state().keyword_closes(str(data.get("title") or ""), body) | {int(n) for n in PART_OF.findall(body)}
    return sorted(n for n in refs if 0 < n <= GRAPHQL_INT and n != number)


Issues = dict[int, dict | None]  # the named issues' threads, by number (None: no such issue)


def threads_of(data: dict, number: int, repo: str | None) -> tuple[dict, Issues]:
    """The pull request's thread and, in the same GraphQL read, the threads of the issues it closes
    or names as Part of #N (named_issues), which the veto (#1309) and the answer (spec 055) read;
    without such an issue, pr_thread's read alone"""
    numbers = named_issues(data, number)
    if not numbers:
        return pr_thread(number, repo), {}
    found, nodes = repository_of(numbers, number, repo, THREAD, pull_field(number))
    node = found.get("pullRequest")
    if not isinstance(node, dict):
        raise GateError(f"GitHub's GraphQL gave no thread for #{number}: {found!r}")
    return node, nodes


# a trusted veto of a decision taken at notify, not handled (D-48, #1309)
VETOED = "vetoed by @{login} at {at}, not handled"
# a thread cut off at the newest 100 comments, holding a veto its read can't place (#1330)
VETO_CUT_OFF = (
    "the thread of {where} is cut off at 100 comments: a veto in it can't be ruled out handled or not, "
    "so a person looks"
)


def open_veto_in(
    ts: ModuleType, read: list[tuple[str, str, str]], bot_login: str | None, maintainers: Container[str]
) -> bool:
    """Whether a window of a thread's comments holds a veto (triage_state.py's vetoes_or_relays) that
    no newer veto-handled marker by the --bot-login or an OWNER, MEMBER, or COLLABORATOR in it
    answers: the decided marker may be older than the window, so such a veto may count (#1330)"""
    veto, handled = -1, -1
    for i, (author, association, body) in enumerate(read):
        if ts.VETO_HANDLED_MARKER.match(ts.first_line(body)) and ts.trusted(author, association, bot_login):
            handled = i
        elif ts.vetoes_or_relays(read[i], bot_login, maintainers):
            veto = i
    return veto > handled


def vetoes_of(
    data: dict, number: int, thread: dict, issues: Issues, bot_login: str | None, maintainers: Container[str]
) -> tuple[str, ...]:
    """Each unhandled veto of a decision taken at notify on the pull request or on an issue it closes
    (triage_state.py's keyword_closes), read as triage_state.py reads VETOED (unhandled_veto): after
    the first decided marker by the --bot-login or an OWNER, MEMBER, or COLLABORATOR, a comment by an
    OWNER, MEMBER, or COLLABORATOR other than the --bot-login, without the agent marker, whose first
    word is `veto`, or the --bot-login's relay of a veto naming a login in maintainers, as the
    relayed answer names one (spec 055; D-103, #1482), with no newer veto-handled marker by such an
    author; a relayed veto's line names the maintainer. The newest 100 comments of each are read, as
    for the answer; a thread with older ones unread, where unhandled_veto finds none but the window
    holds such a veto with no newer veto-handled marker, fails closed with VETO_CUT_OFF, since its
    decided marker may be older than the window (#1330)"""
    ts = triage_state()
    closes = ts.keyword_closes(str(data.get("title") or ""), str(data.get("body") or ""))
    nodes = [(f"#{number}", thread)]
    for n in sorted(closes):
        issue = issues.get(n)
        if isinstance(issue, dict) and issue.get("__typename") == "Issue":
            nodes.append((f"#{n}", issue))
    found: list[str] = []
    for where, node in nodes:
        comments, whole = comments_of(node, where)
        read = ts.comment_tuples(node)
        at = ts.unhandled_veto(read, bot_login, maintainers)
        if at is not None:
            when = moment(comments[at]["createdAt"], f"a comment of {where}'s createdAt")
            stamp = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: UP017 (3.10)
            who = ts.relayed_veto(read[at], bot_login, maintainers) or read[at][0]
            found.append(VETOED.format(login=who, at=stamp))
        elif not whole and open_veto_in(ts, read, bot_login, maintainers):
            found.append(VETO_CUT_OFF.format(where=where))
    return tuple(found)


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


def metrics() -> ModuleType:
    return module("shipmill_metrics", METRICS)


# spec 085: the comments whose first line gives an issue's allowed files, and the gate's lines for them
ALLOWING = ("Triage: **implement**", "Proposed plan:")
FILES_SHOWN = 20  # the outside paths printed one a line; the rest are counted
OUTSIDE = "{path} is outside what {issues} {verb}"
OUTSIDE_MORE = "and {more} more outside the allowed files"
FILES_UNREAD = "#{issue}'s allowed files can't be read: {why}"
FILES_CUT_OFF = "the thread of #{issue} is cut off at 100 comments: its allowed files can't be read, so a person looks"


@dataclass(frozen=True)
class Allowance:
    """What an issue lets an agent's pull request change (spec 085): the paths of its counting
    comment's `Files:` lines, None when it declares no allowance, or the line saying why they can't
    be read, which holds the pull request (fail closed)"""

    issue: int
    paths: tuple[str, ...] | None = None
    unread: str = ""


def allowance(node: object, issue: int, opened: datetime, bot_login: str | None) -> Allowance:
    """Issue's allowed files, read from its thread as GraphQL gives it (THREAD): the newest comment
    whose first line starts `Triage: **implement**` or `Proposed plan:`, by the --bot-login or an
    OWNER, MEMBER, or COLLABORATOR (retro.py's trusted), created before the pull request opened
    (opened). Each of its lines outside a fence that starts `Files:`, after an optional list bullet,
    adds its backticked paths (metrics.py's FILES_LINE and BACKTICKED, the plan's reading); such a
    line naming no path, or an empty, absolute, or `..` one, can't be read. A counting comment with
    no `Files:` line, no counting comment, or a number that is no issue declares none, save a thread
    cut off at its newest 100 comments with no counting comment among them, which can't be read"""
    if not isinstance(node, dict) or node.get("__typename") != "Issue":
        return Allowance(issue)
    rt, mt = retro(), metrics()
    bots = frozenset({bot_login}) if bot_login else frozenset()
    comments, whole = comments_of(node, f"#{issue}")
    counting = [
        c
        for c in comments
        if rt.first_line(c["body"]).startswith(ALLOWING)
        and rt.trusted(c, bots)
        and moment(c["createdAt"], f"a comment of #{issue}'s createdAt") < opened
    ]
    if not counting:
        return Allowance(issue) if whole else Allowance(issue, unread=FILES_CUT_OFF.format(issue=issue))
    paths: list[str] = []
    files_lines = 0
    for line in unfenced(counting[-1]["body"]):
        found = mt.FILES_LINE.match(line)
        if found is None:
            continue
        files_lines += 1
        named = mt.BACKTICKED.findall(found.group("paths"))
        why = files_problem(named)
        if why:
            return Allowance(issue, unread=FILES_UNREAD.format(issue=issue, why=why))
        paths += named
    return Allowance(issue, tuple(paths) if files_lines else None)


def files_problem(named: list[str]) -> str:
    """Why a `Files:` line's backticked paths can't be read, or "" when they can"""
    if not named:
        return "`Files:` names no path in backticks"
    for path in named:
        if not path.strip():
            return "`Files:` names an empty path"
        if path.startswith("/"):
            return f"`Files:` names an absolute path, `{path}`"
        if ".." in path:
            return f"`Files:` names a path holding `..`, `{path}`"
    return ""


def files_hold(
    data: dict, number: int, repo: str | None, thread: dict, issues: Issues, bot_login: str | None, base: Base
) -> tuple[str, ...]:
    """The files: lines of an agent's open pull request (spec 085), from the threads threads_of read:
    each named issue's allowance that can't be read, else the changed paths outside the declared
    allowances (files_outside); none when no named issue declares one, and then the files aren't read"""
    opened = moment(thread.get("createdAt"), f"#{number}'s createdAt")
    found = [allowance(issues.get(n), n, opened, bot_login) for n in named_issues(data, number)]
    unread = tuple(a.unread for a in found if a.unread)
    if unread:
        return unread
    if all(a.paths is None for a in found):
        return ()
    return files_outside(found, changed_paths(data, number, repo), base.fragments)


def files_outside(allowances: Iterable[Allowance], changed: Iterable[str], fragments: str | None) -> tuple[str, ...]:
    """Each changed path no declared allowance covers (metrics.py's covered: equal, under a path
    ending in `/`, or a match by spec 061's grammar), naming every issue that declares one, a file
    directly inside the fragments folder always covered; FILES_SHOWN of them, then how many more"""
    declared = [a for a in allowances if a.paths is not None]
    if not declared:
        return ()
    union = [p for a in declared for p in a.paths or ()]
    covered = metrics().covered

    def fragment(path: str) -> bool:
        return fragments is not None and PurePosixPath(path).parent.as_posix() == fragments

    outside = [path for path in dict.fromkeys(changed) if not covered(path, union) and not fragment(path)]
    names = ", ".join(f"#{a.issue}" for a in sorted(declared, key=lambda a: a.issue))
    verb = "allows" if len(declared) == 1 else "allow"
    lines = [OUTSIDE.format(path=path, issues=names, verb=verb) for path in outside[:FILES_SHOWN]]
    if len(outside) > FILES_SHOWN:
        lines.append(OUTSIDE_MORE.format(more=len(outside) - FILES_SHOWN))
    return tuple(lines)


def changed_paths(data: dict, number: int, repo: str | None) -> tuple[str, ...]:
    """Every path the pull request changes, past gh pr view's first hundred too, and each renamed
    file's old path, from the files API (spec 085)"""
    data["files"] = all_files(data, number, repo)
    if "previous" not in data:
        data["statuses"] = files_api(data, number, repo)
    return (*data["files"], *data["previous"])


def newest_question(comments: list[dict], bots: frozenset[str]) -> int | None:
    """The index of the newest needs-decision question, as retro.py reads one: its first line is
    the marker, by an OWNER, MEMBER, or COLLABORATOR or the --bot-login"""
    rt = retro()
    for i in range(len(comments) - 1, -1, -1):
        if rt.first_line(comments[i]["body"]) == rt.NEEDS_DECISION_MARK and rt.trusted(comments[i], bots):
            return i
    return None


def issue_question(
    data: dict, number: int, repo: str | None, bots: frozenset[str], issues: Issues | None = None
) -> tuple[list[dict], int] | None:
    """The newest question on an issue the pull request closes (triage_state.py's keyword_closes) or
    names as Part of #N, with that issue's comments: one GraphQL read, or none when issues holds
    threads_of's read of them; None without one"""
    numbers = named_issues(data, number)
    if not numbers:
        return None
    nodes = issues_of(numbers, number, repo, THREAD)[1] if issues is None else issues
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


def asked_at(question: str) -> str | None:
    """The full head a question names on its line `<!-- shipmill:head <sha> -->`; None without
    one (S-055-5): a commit's date is its author's to set, a force-push's beforeCommit may be a
    head pushed after the answer, and a 7-hex prefix can be matched by a commit made to order,
    so none of them names what was answered"""
    for line in question.splitlines():
        found = ASKED_AT.fullmatch(line.strip())
        if found is not None:
            return found.group(1)
    return None


def by_bots(comment: dict, bots: frozenset[str]) -> bool:
    """Whether the --bot-login wrote the comment: an answer of its is a relay"""
    return bool(retro().login_names(comment.get("author")) & {b.lower() for b in bots})


def whole_reply(comment: dict, bots: frozenset[str]) -> str | None:
    """The answer as its whole reply reads (S-055-8): every non-blank line of a person's reply,
    leaving out the agent marker; one line is the answer, none or more than one is None, so a
    line past the option is the person's own words and takes no option. A relay is read by its
    grammar, retro.py's parse_relay (D-93): its answer line, None for `own:`, for a relay it
    refuses, and for one with no answer line"""
    rt = retro()
    if by_bots(comment, bots):  # the App's relay
        return rt.parse_relay(str(comment["body"])).option or None
    lines = [line.strip() for line in str(comment["body"]).splitlines()]
    lines = [line for line in lines if line and not rt.AGENT_MARKER.fullmatch(line)]
    return lines[0] if len(lines) == 1 else None


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


APPROVED_STATUSES = ("approved", "built")  # a spec whose Behaviour a change asks about (D-81, #1311)
CHANGES_APPROVED = "{spec} changes approved Behaviour"
# the sections filled in on an approved spec after its approval, which same-approval reads as a
# change but which ask nothing here: Issues, by the split's docs PR (spec-gate.md, Split it, step 5),
# and Verification, by the build PR beside its status: line (spec-gate.md, Verify the whole spec)
FILLED_AFTER_APPROVAL = frozenset({"Issues", "Verification"})


def modified_specs(data: dict, number: int, repo: str | None) -> tuple[str, ...]:
    """The spec files the PR modifies (the files API's `status: modified`), read as added_specs
    reads the ones it adds, and from the same read"""
    added_specs(data, number, repo)
    statuses: dict[str, str] = data.get("statuses") or {}
    return tuple(f for f, status in statuses.items() if status == "modified" and SPEC_FILE.fullmatch(f))


def spec_status(text: str) -> str | None:
    """A spec's status, its first `status: <word>` line, as specs.py reads it; None without one"""
    for line in text.splitlines():
        found = specs_script().STATUS.match(line)
        if found is not None:
            return found.group(1)
    return None


def approved_edits(data: dict, number: int, repo: str | None, checkout: str) -> list[str]:
    """Each approved or built spec the PR changes past its format (D-81, #1311): for every spec file
    it modifies whose text on origin/<base> says `status: approved` or `status: built`, specs.py
    same-approval --base origin/<base> compares the PR's own change to it, base against head (the
    merge-base as the answered head, whose own change is none). Exit 0, only format or the status:
    line, keeps the verdict, and so does exit 1 when every section it names is Issues or
    Verification, which the split's docs PR and the build PR fill in; any other section asks. An
    approved spec the PR renames (the files API's previous_filename) asks by its old path, unread:
    same-approval reads one path at both commits. A spec PR's added spec is spec_problems'"""
    candidates = modified_specs(data, number, repo)
    moved = tuple(p for p in data.get("previous") or () if SPEC_FILE.fullmatch(p))
    if not candidates and not moved:
        return []
    base_ref = base_of(data, checkout)
    read = file_in(checkout)
    approved = [s for s in candidates if spec_status(read(base_ref, s) or "") in APPROVED_STATUSES]
    found = [
        CHANGES_APPROVED.format(spec=s) for s in moved if spec_status(read(base_ref, s) or "") in APPROVED_STATUSES
    ]
    if not approved:
        return found
    head = str(data["headRefOid"])
    if not has_commit(checkout, head):
        raise GateError(f"#{number}'s head {head[:7]} is not in {checkout}: run `git -C {checkout} fetch origin`")
    merge_base = git(checkout, "merge-base", base_ref, head).strip()
    for spec in approved:
        cmd = [sys.executable, str(SPECS), "same-approval", "--base", base_ref, spec, merge_base, head]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=checkout)
        if proc.returncode not in (0, 1):
            raise GateError(f"specs.py same-approval {spec} failed for #{number}: {proc.stderr.strip()}")
        sections = {line[3:].strip() for line in proc.stdout.splitlines() if line.startswith("## ")}
        if proc.returncode == 1 and not sections <= FILLED_AFTER_APPROVAL:
            found.append(CHANGES_APPROVED.format(spec=spec))
    return found


def file_in(checkout: str) -> Callable[[str, str], str | None]:
    """A reader of a file's text at a commit of the checkout, None when the commit hasn't it"""

    def read(commit: str, path: str) -> str | None:
        if quiet(checkout, "cat-file", "-e", f"{commit}:{path}") is None:
            return None
        return git(checkout, "show", f"{commit}:{path}")

    return read


def log_entries(text: str) -> dict[str, str]:
    """A decisions log by entry: each `## D-n: <title>` heading's D-n to its lines, the heading's
    included, and "" to the lines before the first; blank lines at either end of one dropped"""
    found: dict[str, list[str]] = {"": []}
    key = ""
    for line in text.splitlines():
        heading = specs_script().DECISION_HEADING.match(line)
        if heading is not None:
            key = f"D-{int(heading.group(1))}"
            found.setdefault(key, [])  # an id twice reads as one entry of both: a change all the same
        found[key].append(line.rstrip())
    return {k: "\n".join(lines).strip("\n") for k, lines in found.items()}


def renumbered(text: str, moved: dict[int, int]) -> str:
    """text with each D-n moved names written as the D-n it moved to, in one pass; any other id
    stays as written (a zero-padded D-01 too)"""
    ids = specs_script().DECISION_ID
    return ids.sub(lambda m: f"D-{moved[int(m.group(1))]}" if int(m.group(1)) in moved else m.group(0), text)


def log_change(
    read: Callable[[str, str], str | None], merge_base: str, sha: str, log: str, moved: dict[int, int]
) -> dict[str, tuple[str | None, str | None]]:
    """The pull request's own change to a decisions log at a head, by entry: each entry it adds,
    edits, or removes, before and after, its text at the head with the D-n ids moved renumbered"""
    before = log_entries(read(merge_base, log) or "")
    after = log_entries(renumbered(read(sha, log) or "", moved))
    return {k: (before.get(k), after.get(k)) for k in before.keys() | after.keys() if before.get(k) != after.get(k)}


def file_patches(patch: str) -> list[str]:
    """A patch split by file, each piece from its `diff --git` line"""
    return [piece for piece in re.split(r"(?m)^(?=diff --git )", patch) if piece]


def without_index(piece: str) -> str:
    """A file's patch without its `index <blob>..<blob>` line, which names the blobs' hashes"""
    return re.sub(r"(?m)^index [0-9a-f]+\.\.[0-9a-f]+.*\n", "", piece, count=1)


def same_patches(answered: str, head: str, moved: dict[int, int]) -> bool:
    """Whether two own changes' patches are the same, file by file: byte for byte, or, for a text
    file whose lines cite a D-n moved, the same once the answered side's ids are renumbered, the
    index line aside (the renumbering changes the blob)"""
    then, now = file_patches(answered), file_patches(head)
    if len(then) != len(now):
        return False
    for before, after in zip(then, now, strict=True):
        mapped = renumbered(before, moved)
        if mapped == before or "\n@@ " not in mapped:  # nothing moved, or binary: byte for byte
            if before != after:
                return False
        elif without_index(mapped) != without_index(after):
            return False
    return True


def same_change(checkout: str, base_ref: str, answered: str, head: str, specs: tuple[str, ...]) -> bool:
    """Whether the answered head's own change is the judged head's, each against its own merge-base:
    a spec PR's spec files by same-approval (D-81), the decisions log by entry, every other file's
    patch byte for byte. A D-n the PR claims (a heading its change to the log adds) renumbered by a
    rebase (D-49) is format, matched by its title as same-approval matches it: the one id mapping
    old to new is applied to the answered side's log and other files, so an entry that differs
    only in its id, and the lines citing it, read the same, while a changed entry, a second new
    one, or a line citing another decision differs. A head the checkout can't read isn't"""
    if not has_commit(checkout, answered) or not has_commit(checkout, head):
        return False
    if not all(same_approval(checkout, base_ref, spec, answered, head) for spec in specs):
        return False
    sp, read = specs_script(), file_in(checkout)
    answered_base = git(checkout, "merge-base", base_ref, answered).strip()
    head_base = git(checkout, "merge-base", base_ref, head).strip()
    moved = sp.renumbering(sp.claimed(answered_base, answered, read), sp.claimed(head_base, head, read))
    logs = tuple(log.as_posix() for log in sp.DECISION_LOGS)
    for log in logs:
        if log_change(read, answered_base, answered, log, moved) != log_change(read, head_base, head, log, {}):
            return False
    leaving = (*specs, *logs)
    return same_patches(
        own_change(checkout, base_ref, answered, leaving), own_change(checkout, base_ref, head, leaving), moved
    )


def acceptance(
    data: dict,
    number: int,
    repo: str | None,
    bot_login: str | None,
    checkout: str,
    maintainers: Maintainers,
    thread: dict | None = None,
    issues: Issues | None = None,
) -> tuple[bool, str | None]:
    """Whether the maintainer's answer covers the judged head (spec 055), and, when it doesn't,
    the needs-decision line that says why (None for no line): the newest question on the pull
    request, else, for a pull request the --bot-login or an OWNER, MEMBER, or COLLABORATOR
    opened, on an issue it closes or names as Part of #N; its newest trusted answer, by
    retro.py's newest_answer_at (a relay by the --bot-login counts when it names one of
    maintainers; D-89), so a bare number after words takes the option and words after a bare
    number hold it again; a relay out of its grammar not counted, `relay not counted: format`
    (retro.py's relay_refusal, D-93); its whole reply taking the (recommended) option, by
    retro.py's takes_recommended; given on an issue before the pull request opened, or at the
    head the question names in full (its `<!-- shipmill:head <sha> -->` line) or one whose own
    change is the judged head's. Anything else leaves the question open. thread is the pull
    request's, and issues the threads of the issues it names, when this pass already read them"""
    rt = retro()
    bots = frozenset({bot_login}) if bot_login else frozenset()
    thread = pr_thread(number, repo) if thread is None else thread
    comments, whole = comments_of(thread, f"#{number}")
    asked = newest_question(comments, bots)
    on_issue = False
    if asked is None:
        if not whole:
            return False, None  # its own question may be older than the comments read
        if not rt.trusted(thread, bots):
            return False, None  # anyone may write `Fixes #N` in a body: an outsider's PR asks its own
        found = issue_question(data, number, repo, bots, issues)
        if found is None:
            return False, None
        (comments, asked), on_issue = found, True
    later = comments[asked + 1 :]
    answer = rt.newest_answer_at(later, bots, maintainers)
    if answer is None:
        return False, None
    index = answer[0]
    if by_bots(later[index], bots):
        refused = rt.relay_refusal(comments[asked]["body"], rt.parse_relay(str(later[index]["body"])))
        if refused is not None:
            return False, RELAY_NOT_COUNTED.format(reason=refused)
    said = whole_reply(later[index], bots)
    if said is None or not rt.takes_recommended(comments[asked]["body"], said):
        return False, NOT_RECOMMENDED
    at = moment(later[index]["createdAt"], f"the answer on #{number}'s createdAt")
    if on_issue and at < moment(thread.get("createdAt"), f"#{number}'s createdAt"):
        return True, None  # given before the pull request opened: it covers every head
    head = str(data["headRefOid"])
    answered = asked_at(comments[asked]["body"])
    if answered is None:
        return False, NO_HEAD
    if answered == head:
        return True, None
    specs = added_specs(data, number, repo)
    if same_change(checkout, base_of(data, checkout), answered, head, specs):
        return True, None
    return False, DIFFERS.format(sha7=answered[:7])


# The spec of accepted work at notify (spec 067): the --bot-login's decided comment covers its head
ACCEPTED_SPEC = "accepted-spec"
# a decided comment's first line (needs-decision.md, A decided comment), as retro.py's DECIDED_MARK
DECIDED_FIRST = re.compile(r"<!-- shipmill:decided zone=([a-z][a-z-]*) until=\S+ -->")
NO_BOT = "no --bot-login names who posts the decided comment, so none counts"
NOT_DECIDED = (
    "no decided comment of {bot} on record; post one naming the head with its `<!-- shipmill:head <sha> -->` line"
)
OTHER_ZONE = "the newest decided comment of {bot} is for the zone {zone}; post one for accepted-spec naming the head"
DECIDED_NO_HEAD = "the decided comment names no head: post it again with its `<!-- shipmill:head <sha> -->` line"
DECIDED_DIFFERS = "decided at {sha7}, and the change differs since; post a new decided comment naming the head"


def notify_zone(zones: tuple[Zone, ...] | None, zone: str) -> bool:
    """Whether classify reports the zone at notify, the level it read from the base"""
    return any(z.zone == zone and z.level == "notify" for z in zones or ())


def decided(
    data: dict, number: int, repo: str | None, bot_login: str | None, checkout: str, thread: dict
) -> str | None:
    """Why the spec of accepted work at notify isn't decided at the judged head (spec 067), or None
    when it is: the --bot-login's newest decided comment on the pull request, its zone accepted-spec,
    naming in full on its `<!-- shipmill:head <sha> -->` line the judged head or a head whose own
    change is the judged head's (same_change: the spec files by specs.py same-approval, D-81, the
    decisions log by entry, a claimed D-n renumbered read the same, every other file byte for
    byte). A decided comment by anyone else never counts, the maintainer's too:
    the maintainer approves by an answer (D-49)"""
    if not bot_login:
        return NO_BOT
    rt = retro()
    comments, _ = comments_of(thread, f"#{number}")
    bot = bot_login.lower()
    mine = [
        c
        for c in comments
        if DECIDED_FIRST.fullmatch(rt.first_line(c["body"])) and bot in rt.login_names(c.get("author"))
    ]
    if not mine:
        return NOT_DECIDED.format(bot=bot_login)
    newest = mine[-1]["body"]
    found = DECIDED_FIRST.fullmatch(rt.first_line(newest))
    assert found is not None  # mine holds only decided comments
    if found.group(1) != ACCEPTED_SPEC:
        return OTHER_ZONE.format(bot=bot_login, zone=found.group(1))
    named = asked_at(newest)
    if named is None:
        return DECIDED_NO_HEAD
    head = str(data["headRefOid"])
    if named == head:
        return None
    if same_change(checkout, base_of(data, checkout), named, head, added_specs(data, number, repo)):
        return None
    return DECIDED_DIFFERS.format(sha7=named[:7])


# a review of the merging head (spec 055): the records the App writes with `shipmill review record`
REVIEW_MERGE = "<!-- shipmill:review merge -->"
REVIEW_REFUSE = "<!-- shipmill:review refuse -->"
TRUSTED = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})  # D-16, D-29: whose approval is a record
DOC_SUFFIXES = (".md", ".mdx", ".rst", ".txt")
INSTRUCTION_DIRS = ("skills/", ".claude/", ".claude-plugin/")  # the agents' instructions: code to review
INSTRUCTION_NAMES = frozenset({"CLAUDE.md", "AGENTS.md", "REVIEW.md"})
NO_REVIEW = "no review of {sha7} on record; review it, then record it with shipmill review record"
# S-075-7: the line `shipmill review record --findings` writes right after the verdict's marker
FINDINGS_LINE = re.compile(
    r"<!-- shipmill:findings confirmed=(0|[1-9][0-9]*) rejected=(?:0|[1-9][0-9]*) minor=(?:0|[1-9][0-9]*) -->"
)
REVIEW_REFUSED = (
    "the newest review of {sha7} on record refuses it on {confirmed} confirmed finding(s); fix them, review it "
    "again, then record it with shipmill review record"
)
REVIEW_UNVERIFIED = (
    "the newest review of {sha7} on record refuses it on findings no second reviewer checked; verify them "
    "(reviewer-brief.md, Verify a refusal), then record it again"
)


def documentation(path: str) -> bool:
    """Whether a changed file is documentation (spec 055): a name ending .md, .mdx, .rst, or .txt,
    or a path under docs/, and not the agents' instructions"""
    name = path.rsplit("/", 1)[-1]
    if path.startswith(INSTRUCTION_DIRS) or name in INSTRUCTION_NAMES:
        return False
    return path.startswith("docs/") or name.endswith(DOC_SUFFIXES)


def docs_only(data: dict, number: int, repo: str | None) -> bool:
    """Whether every file the PR touches is documentation: each path gh pr view lists, past its
    first hundred too, and, read from the files API once they all are, each renamed file's old
    path, so a rename out of code reads as touching code"""
    data["files"] = all_files(data, number, repo)
    if not all(documentation(path) for path in data["files"]):
        return False
    if "previous" not in data:
        data["statuses"] = files_api(data, number, repo)
    return all(documentation(path) for path in data["previous"])


def reviews_of(number: int, repo: str | None) -> list[dict]:
    """The pull request's reviews, oldest first, every page: one read; a gh failure exits 1, a
    review the gate can't read stops it"""
    path = f"repos/{{owner}}/{{repo}}/pulls/{number}/reviews?per_page=100"
    cmd, env = api(["--paginate", path, "--jq", ".[]"], repo)
    found = []
    for line in gh(cmd, number, env).splitlines():
        if not line.strip():
            continue
        review = json.loads(line)
        user = review.get("user") if isinstance(review, dict) else None
        if (
            not isinstance(review, dict)
            or not isinstance(review.get("state"), str)
            or not isinstance(review.get("body") or "", str)
            or not (user is None or isinstance(user, dict))
        ):
            raise GateError(f"a review of #{number} is not {{state, body, user, commit_id}}: {review!r}")
        found.append(review)
    return found


def record_of(review: dict, bot: str | None, ts: ModuleType) -> str | None:
    """What a review records (spec 055): `merge` or `refuse` for the --bot-login's marked review,
    `approved` for a trusted person's APPROVED review without the agent marker, else None"""
    user = review.get("user") or {}
    login = str(user.get("login") or "").lower()
    body = str(review.get("body") or "")
    state = review["state"]
    if bot is not None and login == bot:
        if state in ("PENDING", "DISMISSED"):
            return None
        first = body.lstrip().split("\n", 1)[0].strip()
        return {REVIEW_MERGE: "merge", REVIEW_REFUSE: "refuse"}.get(first)
    if state != "APPROVED" or user.get("type") == "Bot" or str(review.get("author_association")) not in TRUSTED:
        return None
    return None if ts.by_agent(body) else "approved"


def confirmed_of(review: dict) -> int | None:
    """S-075-7: the confirmed count of a record's findings line, the line right after its marker,
    or None when that line isn't exactly `<!-- shipmill:findings confirmed=N rejected=N minor=N -->`"""
    lines = str(review.get("body") or "").lstrip().split("\n")
    found = FINDINGS_LINE.fullmatch(lines[1].strip()) if len(lines) > 1 else None
    return None if found is None else int(found.group(1))


def unreviewed(data: dict, number: int, repo: str | None, bot_login: str | None, checkout: str, inside: bool) -> str:
    """Why an agent's code pull request has no review record covering its judged head (spec 055),
    or "" when one does: the --bot-login's newest record covering it, else a trusted person's
    approval covering it. A record covers the head at its commit_id, or, in a checkout of the repo,
    at a head whose own change is the same, as same_change reads it for the maintainer's answer"""
    ts = triage_state()
    bot = bot_login.lower() if bot_login else None
    head = str(data["headRefOid"])
    records = []
    for review in reviews_of(number, repo):
        kind = record_of(review, bot, ts)
        commit = review.get("commit_id")
        if kind is not None and isinstance(commit, str) and FULL_SHA.fullmatch(commit):
            records.append((commit, kind, review))
    known: dict[str, bool] = {head: True}

    def covers(commit: str) -> bool:
        if commit not in known:
            known[commit] = inside and same_change(checkout, base_of(data, checkout), commit, head, specs())
        return known[commit]

    def specs() -> tuple[str, ...]:
        return added_specs(data, number, repo)

    for commit, kind, review in reversed(records):
        if kind != "approved" and covers(commit):
            if kind == "refuse":
                confirmed = confirmed_of(review)
                if confirmed is None:
                    return REVIEW_UNVERIFIED.format(sha7=head[:7])
                return REVIEW_REFUSED.format(sha7=head[:7], confirmed=confirmed)
            return ""
    if any(kind == "approved" and covers(commit) for commit, kind, _ in records):
        return ""
    return NO_REVIEW.format(sha7=head[:7])


def base_of(data: dict, checkout: str) -> str:
    """origin/<the PR's base>, which a head's own change is read against; one the checkout lacks
    stops the gate"""
    base_ref = f"origin/{data['baseRefName']}"
    if quiet(checkout, "rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}") is None:
        raise GateError(f"{base_ref} is not in {checkout}: run `git -C {checkout} fetch origin`")
    return base_ref


def judge(
    data: dict,
    number: int,
    base: Base,
    agent: bool,
    zones: tuple[Zone, ...] | None = None,
    spec: tuple[str, ...] = (),
) -> Gate:
    """zones, classify's for the PR, are given when the base's config has [agents] (spec 030);
    they replace the direction and Protected areas checks. spec is spec_problems' answer, which
    the maintainer's answer doesn't lift (spec 053); the asks are lifted only by acceptance, read
    after this (spec 055). A draft is judged for nothing else (D-67); agent, for a draft, says the
    --bot-login authored it, so its line says to mark it ready"""
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
        never = [z.line() for z in zones if z.level == "never"]  # no answer lifts it (D-48)
        asks = [z.line() for z in zones if z.level == "ask"]
        notices = [z.line() for z in zones if z.level == "notify"]
    elif base.ids is not None or base.reviews:
        edited = direction_edits(files)
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
    lines += [f"  base: pending: {line}" for line in gate.base_pending]
    lines += [f"  refused: {reason}" for reason in gate.refused]
    lines += [f"  spec: {reason}" for reason in (*gate.spec, *gate.spec_asks)]
    lines += [f"  maintainer-only: {reason}" for reason in gate.never]
    lines += [f"  needs-decision: {reason}" for reason in gate.asks]
    lines += [f"  files: {line}" for line in gate.files]
    lines += [f"  notify: {reason}" for reason in gate.notices]
    lines += [f"  decided: {veto}" for veto in gate.vetoes]
    lines += [f"  unreviewed: {gate.unreviewed}"] if gate.verdict == UNREVIEWED else []
    lines += [f"  revert: {gate.revert}"] if gate.revert else []
    lines += [f"  incident: {line}" for line in gate.incidents]
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
    (#1028); a base check rerunning a failure makes its PR PENDING (#1310), and every other
    verdict stops the wait"""
    worst = max((g.verdict for g in gates), key=RANK.index)
    if worst == PENDING:
        return True
    return worst == NEEDS_DECISION and any(
        g.verdict == NEEDS_DECISION and any(not c.done for c in g.checks) for g in gates
    )


MAINTAINER_ACCEPTED_GONE = (
    "--maintainer-accepted is gone (spec 055): the maintainer's acceptance is read from their answer on GitHub, "
    "the newest trusted reply to the newest needs-decision question taking its (recommended) option at the head "
    "its `<!-- shipmill:head <sha> -->` line names; ask that question and run the gate again"
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
    # gone (spec 055): parsed only to refuse it by name, before any read
    parser.add_argument("--maintainer-accepted", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--tool",
        help="with [agents] on the base: where uvx gets shipmill for `decide classify` (default: "
        "shipmill==<the plugin.json version>)",
    )
    args = parser.parse_args()
    if args.maintainer_accepted:
        parser.error(MAINTAINER_ACCEPTED_GONE)
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
        edits: dict[tuple[int, str], tuple[str, ...]] = {}  # the approved specs each head changes (#1311)
        maintainers: dict[frozenset[str], Maintainers] = {}  # who a relayed answer may name (spec 055)
        while True:
            gates = []
            heads: dict[str, tuple[str, list[dict]]] = {}  # each base branch's head, read once a pass (D-75)
            windows = Windows(bases.checkout, args.tool)  # each base's land window, read once a pass (spec 056)
            incidents = Incidents(args.repo)  # the latest deploys and open incidents, read once a pass (#1481)
            for number in args.prs:
                data = fetch(number, args.repo)
                base = bases.base(str(data["baseRefName"]))
                own = args.bot_login is not None and author_of(data.get("author") or {}) == args.bot_login
                if data["isDraft"]:  # neither its files nor its zones are read (D-67)
                    gates.append(judge(data, number, base, own))
                    continue
                if base.ids is not None or base.reviews:
                    data["files"] = all_files(data, number, args.repo)
                # the agent marker on a line of its own makes it an agent's, whoever opened it (spec 055, D-62)
                agent = args.agent or own or triage_state().by_agent(str(data.get("body") or ""))
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
                judged = judge(data, number, base, agent, zones, spec)
                if data["state"] == "OPEN" and bases.inside:  # D-81, #1311
                    edit = (number, str(data["headRefOid"]))
                    if edit not in edits:
                        edits[edit] = tuple(approved_edits(data, number, args.repo, bases.checkout))
                    judged = replace(judged, spec_asks=edits[edit])
                # the PR's thread and its issues', read once a pass for the checks below
                thread: dict | None = None
                issues: Issues | None = None
                if base.maintainers not in maintainers:  # one per base read: its permission reads too
                    maintainers[base.maintainers] = Maintainers(base.maintainers, args.repo)
                who = maintainers[base.maintainers]
                if data["state"] == "OPEN":  # an unhandled veto of a notify decision blocks it (D-48, #1309)
                    thread, issues = threads_of(data, number, args.repo)
                    # a maintainer's veto relayed by the --bot-login counts too (D-103, #1482)
                    judged = replace(judged, vetoes=vetoes_of(data, number, thread, issues, args.bot_login, who))
                if thread is not None and issues is not None and agent:  # the files its issues allow (spec 085)
                    files = files_hold(data, number, args.repo, thread, issues, args.bot_login, base)
                    judged = replace(judged, files=files)
                if thread is not None and notify_zone(zones, ACCEPTED_SPEC):  # spec 067
                    why = decided(data, number, args.repo, args.bot_login, bases.checkout, thread)
                    if why is not None:
                        judged = replace(judged, asks=(*judged.asks, f"{ACCEPTED_SPEC}: {why}"))
                if judged.verdict == NEEDS_DECISION:  # the answer on GitHub lifts the asks (spec 055)
                    covered, why = acceptance(
                        data, number, args.repo, args.bot_login, bases.checkout, who, thread, issues
                    )
                    if covered:
                        judged = replace(judged, asks=(), spec_asks=(), files=())
                    else:
                        judged = replace(judged, asks=(*judged.asks, *([why] if why else [])))
                if data["state"] == "OPEN":
                    branch = str(data["baseRefName"])
                    if branch not in heads:
                        heads[branch] = base_head(branch, number, args.repo, base.config)
                    red, repairs, rerun = base_failures(branch, *heads[branch], str(data.get("body") or ""))
                    judged = replace(judged, base_red=red, base_repairs=repairs, base_pending=rerun)
                # a review of the merging head (spec 055), before the window: QUEUED only takes READY's place
                if judged.verdict == READY and agent and not docs_only(data, number, args.repo):
                    why = unreviewed(data, number, args.repo, args.bot_login, bases.checkout, bases.inside)
                    judged = replace(judged, unreviewed=why)
                # the App's revert waits for a person below [autonomy] revert = "act" (spec 079)
                if judged.verdict == READY and own and is_revert(str(data.get("body") or "")):
                    judged = replace(judged, revert=revert_hold(base.revert, number, args.repo))
                # an open incident on the latest deploy holds all but a revert or a hotfix (#1481)
                if judged.verdict == READY and base.environments and not lands_through_incident(data, own, base):
                    judged = replace(judged, incidents=incidents.holds(base, number))
                # one window per repo, for PRs into the branch its config was read from (spec 056)
                if data["state"] == "OPEN" and base.window and base.ref == f"origin/{data['baseRefName']}":
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
