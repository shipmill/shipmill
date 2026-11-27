#!/usr/bin/env python3
"""Where a repo's product feedback stands: which requests no opportunity groups yet, and
where each opportunity issue is in the maintainer's accept or decline.

Usage: intake_state.py <owner/repo> [--config PATH] [--label opportunity]
                       [--accepted-label planned] [--marker "Triage:"] [--skip-label L]...
                       [--category C]... [--json] [--bot-login LOGIN]
                       [--plans [--wip N] [--tool SPEC] [--role NAME=FILLER[,FILLER...]]...
                                [--stable-tag-regex REGEX]]

Feedback is an open issue, or an open discussion when the repo enables Discussions, that:
  - carries none of SKIP_LABELS (bug, roadmap, and shipmill's own labels, goal-plan and
    project among them, so a plan issue, a request for one, or a project head is never
    feedback), no --skip-label (repeatable, added to SKIP_LABELS), and not --label
  - is not a filed plan item: its body's first line the plan-item marker
    (<!-- shipmill:plan-item #P W-n -->) by an OWNER, MEMBER, or COLLABORATOR or the
    --bot-login (D-16; an outsider's copy of the marker changes nothing)
  - is not triage's by its labels, as triage_state.py reads them: not labelled human or
    role:<name> (a person's item; compared case-insensitively), whatever its comments say,
    nor postponed with a triage comment by an OWNER, MEMBER, or COLLABORATOR or the
    --bot-login (it reads POSTPONED there; with none it reads NEW, #1766)
  - has no triage verdict of implement, feature, duplicate, won't fix, or postponed: the
    verdict is the first bold word of the newest comment starting with --marker
    ("Triage: **implement**") by an OWNER, MEMBER, or COLLABORATOR or the --bot-login (D-16;
    anyone else's reads as absent), so a bug, a contract change, or postponed work stays with
    triage; a newer verdict, such as triage's opportunity hand-off, makes it feedback again
  - for a discussion, sits in a --category (default: any category but Announcements)

An opportunity is an issue labelled --label, open or closed. Its members are the issues
and discussions its "## Evidence" section links: #N, owner/repo#N of this repo, or a
github.com link to an issue or a discussion. A member stays a member after it closes.

For each opportunity:
  OPPORTUNITY_OPEN  open: waiting for the maintainer to accept or decline it
  ACCEPTED          open and labelled --accepted-label, and its newest trusted triage
                    comment (as feedback reads it, D-16) is intake's own
                    (Triage: **opportunity**) or there is none: hand it to
                    github-issue-triage's spec gate as a feature
  HANDED_OFF        accepted, and triage gave it a newer trusted verdict (feature, with its
                    spec PR on a hold line): triage owns it now
  DECLINED          closed as not planned. The note is the reason: the first line of the
                    oldest comment from an hour before the close on that isn't a trusted
                    triage comment (anyone else's `Triage:` comment is an ordinary one), so
                    a later comment on the closed issue doesn't replace it. Its members
                    read as declined and are never proposed again
  NO_REASON         closed as not planned with no such comment: the reason isn't recorded
  DONE              closed as completed
  MERGED            closed as a duplicate of another opportunity; it groups nothing, so its
                    members read NEW_FEEDBACK until the surviving opportunity lists them

For feedback and members:
  NEW_FEEDBACK      feedback that no opportunity lists (a MERGED one aside)
  OVERLAP           listed by more than one opportunity that is open or declined

Each opportunity's evidence: its members, and the thumbs-up reactions on them and on the
opportunity itself. The first line (text) or the first JSON line is the [autonomy] intake
level from the shipmill config (.github/shipmill.toml in the current directory; none
means the default, propose).

With [agents] outcomes = N (spec 101), the product's outcomes in flight are counted: every
open --label issue of the product's repos, whatever it reads (OPPORTUNITY_OPEN, ACCEPTED,
HANDED_OFF), each once. The product is the repo alone without [product] (or with standalone);
in its home ([product] repos), the home and every listed repo; in a component ([product]
home), the home and every repo the home lists, the limit read from the home's config on its
default branch (a component that sets the key itself is refused). Other repos are read with
`shipmill gh --product <repo> api graphql`, one call per owner, and a count that fails exits 2
naming the step and the repo. The text output's second line is then `outcomes in flight: K
of N (product <owner/home>)`, and --json's first line gains "outcomes": {"limit": N,
"in_flight": K, "room": R}, R being N - K and never below 0. Without the key nothing is
counted and both outputs are as before (a component still reads its home's config to know).
With the key, a request issue is held when its newest comment whose first line is
<!-- shipmill:intake-held --> carries the agent marker (D-62), is by the --bot-login or an
OWNER, MEMBER, or COLLABORATOR (D-16), and is newer than its newest trusted triage comment:
  HELD              a held request while the room is 0, noted `held since <date>` (the held
                    comment's, UTC); no action, so it never sets exit 1
A held request reads NEW_FEEDBACK noted `held since <date>` once the room is above 0, and
NEW_FEEDBACK noted `asked by name`, whatever the room, when a reply newer than the held
comment has the first line `propose` (any case, an optional final period), by an OWNER,
MEMBER, or COLLABORATOR other than the --bot-login, with no agent marker. NEW_FEEDBACK and
HELD rows print held requests first, oldest held comment first, then the rest as before. A
discussion is never held: its comments aren't read.
A component whose home's config can't be read (no read token, a home that doesn't list it, no
config on its default branch) has no limit either: output and exit code are as before, with
one `note:` line on stderr naming the failed read and the home.

With --projects (spec 106), a row per project head after the plan rows: an issue labelled
project, opened by an OWNER, MEMBER, or COLLABORATOR or the --bot-login, or labelled project by
someone other than its opener; one per open head and per head closed within 30 days.
PROJECT_HELD (labelled held, or no check issue), PROJECT_ACTIVE (its check issue, the sub-issue
titled `Check: ` with a `## Check` section, open, and a part open or none filed), PROJECT_FOCUS
(active and labelled focus), PROJECT_CLOSING (its check issue open and every part, the head's
other sub-issues and the check issue's, closed; the note its unchecked `## Cleanup` lines or
`no cleanup listed`), PROJECT_CLOSED (closed as completed), PROJECT_STOPPED (closed as not
planned with the --bot-login's `<!-- shipmill:project-stopped -->` comment, its note the
reason on the record's next line). Over an open head's state, two actions (exit 1):
PROJECT_STOP_DUE when the newest trusted reply's first line is `stop: <reason>`, or `stop`
answering the --bot-login's question with the reason on its next line (a relay naming a
maintainer counts, with --role); PROJECT_IDLE for an active, in-focus, or closing head whose
tree (its comments, check issue, parts, and the pull requests closing them) has had no update
for 14 days and no needs-decision question by the --bot-login since.
With --json each has kind "project", state, holder, check, and parts {"open", "closed"}. With
[agents] projects = N, the product's heads reading active or in focus are counted, the product
read as for [agents] outcomes; the text output then prints `projects active: K of N (product
<owner/home>)` after the outcomes line, and --json's first line gains "projects": {"limit": N,
"active": K, "room": R}. While a plan of the product reads PLAN_OVERDUE, --json's first line
also carries "overdue": ["<owner/repo>#P", ...], so a held head can name what it waits for.

With --goals (spec 106), a row per goal after those: GOAL_PROPOSED for an open goal-proposal
issue by a trusted author or the --bot-login, then per goal of kind goal GOAL_MET, GOAL_DROPPED,
GOAL_PLANNED (an accepted plan open, or a project head of one of its plans), or GOAL_WRITTEN;
GOAL_OVERDUE, an action, for a written or planned goal past its date or with its release
tagged, until the --bot-login's goal-review issue names that goal and horizon. With --json each
has kind "goal-state", goal, number, state, holder, and by.

With --json, each NEW_FEEDBACK and ACCEPTED line, and each ACCEPTED_INTO, GOAL_PROPOSAL_DUE,
GOAL_PROPOSED, and NEEDS_GOAL line (spec 106), also has (spec 074): author, the opener's
login (a Bot's ending [bot], as --bot-login spells it) or null when GitHub returns none;
association, the opener's author association, null for a discussion; and handed, the
createdAt of the issue's newest trusted triage comment, as feedback reads it, when its
verdict is opportunity (triage's hand-off), else null, and null for an ACCEPTED
opportunity. The text output has none of them.

With --plans (spec 028), the goals of the direction come next, read with
`uvx shipmill==<version> product show --section goals --json --local` in the current
directory (--local: the repo's own goals, never a component's product home's, spec 071)
(the version in the plugin's .claude-plugin/plugin.json, spec 031, run once more with
`--refresh-package shipmill` when uv finds no such version, #597; --tool runs `uvx --from
<tool> shipmill` instead), and a goal with no open plan issue (an issue labelled goal-plan whose body's
first line is the plan marker <!-- shipmill:plan goal=G-n rev=k -->) reads:
  PLAN_DUE          a trigger holds; the note is the trigger:
                    requested in #N  an open issue labelled goal-plan without the plan
                                     marker, opened by an OWNER, MEMBER, or COLLABORATOR,
                                     whose title names one goal id, a listed one; an
                                     issue opened by anyone else is never a request
                    no-work          nothing open serves the goal: no spec in docs/specs/
                                     at the default branch's head with status draft or
                                     approved whose serves: line names it, no open issue
                                     whose newest trusted triage comment names it in
                                     `Serves:`,
                                     no open pull request whose `## Plan` names it in
                                     `Serves:`, no open opportunity whose body names it in
                                     `Serves:`, and no open plan item (an issue whose
                                     body's first line is <!-- shipmill:plan-item #P W-n -->,
                                     opened by an OWNER, MEMBER, or COLLABORATOR or the
                                     --bot-login, under plan #P of the goal); never for a
                                     goal whose newest plan was closed as not planned or
                                     reads PLAN_DONE (spec 097: the outcome comes first)
                    stalled          spec 027's report says the goal is stalled; spec 027
                                     isn't built yet, so this trigger never fires
  PLAN_WAITS        with --wip N, a no-work or stalled trigger holds while
                    `triage_state.py --wip N` reports no room left; the note is the
                    trigger and "waits for room". A request never waits
A goal the direction records as met or dropped (its `state`, spec 106) reads no trigger, not
even a request's. A goal whose `kind` is measure (spec 105, a standing measure) is planned only on request:
it reads `requested in #N` alone, never a no-work or stalled PLAN_DUE or PLAN_WAITS. A goal
of kind goal, or with no kind (null, or absent from an older shipmill), reads every trigger.
A goal with an open plan issue reads nothing, whatever its trigger; nor does a goal no
trigger holds for. When the goal's newest plan was closed as completed with a trusted outcome
after its last close (spec 097), its PLAN_DUE and PLAN_WAITS notes end `; follows #P`, and
with --json the row has follows (P) and missing: the outcome's `Still missing:` list items
in order, empty for `- nothing`.

Then one row per plan issue: an issue labelled goal-plan whose first line opens the plan
marker, well-formed or not, or that the --bot-login opened. Its answer is the newest
comment newer than its newest revision (the opening body, or the newest comment whose
first line is <!-- shipmill:plan-revised rev=<k> -->, by the --bot-login, with a rev
higher than the revision before it) from an OWNER,
MEMBER, or COLLABORATOR other than the --bot-login; a triage comment (--marker) and a
comment whose first line is a shipmill marker are the sessions' own and never an answer,
and no other comment, reaction, or label is read, save one: a comment by the --bot-login
whose first line is the needs-decision relay, `Decision by @<login>` with the login bare or
in a code span, naming a maintainer the --role flags give (--role maintainer=<login>, as
`shipmill roles --flags` prints them; without them no relay counts) is that maintainer's
answer, read from its first non-blank line after the relay line (D-68):
  PLAN_OPEN         open, with no answer; or its answer is an accept older than the
                    body's last edit, noted "edited after accept"; or its answer is an
                    unclear accept and a comment by the --bot-login whose first line is
                    <!-- shipmill:needs-decision --> is newer, noted "unclear accept asked";
                    or (spec 098) its answer is a hold whose condition was met and a
                    comment by the --bot-login whose first line is
                    <!-- shipmill:plan-recheck --> is newer than the hold and its met_at,
                    noted "hold met: <what>"; or a hold whose rest is not one condition,
                    noted "hold not read: <the first line>", or names an item GitHub answers
                    null for, noted "hold not read: <ref> can't be read"
  PLAN_HELD         (spec 098) open, the answer's first line is `hold until <condition>`
                    (any case, an optional final period), the condition exactly one of
                    YYYY-MM-DD (met at 00:00 UTC that day), #N or owner/repo#N (met once
                    that issue or pull request closed, one read per held plan), or
                    `release` (met once a tag matching --stable-tag-regex, default vX.Y.Z,
                    was created after the hold), and it isn't met; noted "until <condition>"
                    as written. A hold is never an edit, and a body edit leaves it as it is
  PLAN_HOLD_MET     (spec 098) a hold whose condition was met and no re-check is newer;
                    noted "hold met: <date | ref closed | tag>; re-check due"
  PLAN_ANSWERED     open, and the answer's first line starts with `decline` (any case;
                    noted "decline"), starts with the word `accept` but is none of the
                    accept forms (noted "unclear accept: <rule>", spec 096), or is anything
                    else (noted "edit"; `accepted` and `acceptable` start no accept)
  PLAN_ACCEPTED     open, the answer's first line is an accept (spec 096): `accept`,
                    `accept W-1, W-3` (keeps those), or `accept except W-2` (drops those),
                    any case, ids separated by commas, spaces, or both, an optional final
                    period, the ids those of the body's Work section; and a kept feature or
                    fix item has no issue carrying its plan-item marker (as `plans.py items`
                    reads it), or the Milestone names a title and a kept filed item or a
                    kept existing item of this repo isn't in it, or a kept existing item of
                    this repo, open or closed, has no parent, so it isn't yet the plan's
                    sub-issue (D-114, "not linked: #n"); the note names them, then
                    "another parent: #n" for a kept existing item whose parent is another
                    issue (named, never holding the plan), then `dropped: <ids>` after a
                    partial accept
  PLAN_FILED        accepted, and none holds, and a kept item's issue of this repo (a
                    filed item's, or an existing item here) is still open; the note names
                    "another parent: #n" and the dropped ids too
  PLAN_DONE         (spec 097) accepted, none holds, and every such issue is closed,
                    noted "work closed: W-1 #a completed, W-2 #b not planned, ..." (an
                    existing item of another repo is not read, and a dropped item never
                    counts; the note names the dropped ids too); or the goal's newest plan
                    is closed as completed with no outcome comment at or after its last
                    close, noted "closed without an outcome". An outcome comment's first
                    line is <!-- shipmill:plan-outcome -->, by the --bot-login or an OWNER,
                    MEMBER, or COLLABORATOR, and never a trusted author's other than the
                    --bot-login carrying the agent marker
  PLAN_MALFORMED    open, and `plans.py check` refuses the body; the note names the first
                    line and rule
  PLAN_DECLINED     closed as not planned; the note is the reason: the rest of the newest
                    answer starting with `decline`, else the first comment from an hour
                    before the close on, as for an opportunity
Any other plan closed as completed, or as a duplicate, reads nothing. With --json, each plan row has
goal, kind (goal for a goal's row, plan for a plan issue's), number, state, title, note, and
author: the plan issue's opener, a Bot's login ending [bot] as --bot-login spells it, or
null on a goal's row (watch_state.py's trust filter reads it, D-16); and association: the
opener's author association, null on a goal's row (#1680). A PLAN_ACCEPTED or PLAN_FILED row
also has kept and dropped, the ids in Work order (dropped empty for a full accept), and a
PLAN_DUE row has dropped: each item an earlier plan of the goal, open or closed as completed,
dropped by its newest answer, as {"plan": P, "id": "W-n", "text": ...} (spec 096); the
comments of a plan closed as completed are paged back to its first for it. A PLAN_HELD row,
a PLAN_HOLD_MET row, and a PLAN_OPEN row whose hold was met have hold: {"until": the
condition as written, "met_at": ISO 8601 UTC, the date's 00:00, the item's closedAt, or the
tag's time, null while not met} (spec 098); no other row has it.

Exit 0 when nothing needs action, 1 when any row is NEW_FEEDBACK, ACCEPTED, NO_REASON,
OVERLAP, PLAN_DUE, PLAN_ANSWERED, PLAN_ACCEPTED, PLAN_DONE, PLAN_HOLD_MET, or PLAN_MALFORMED
(PLAN_HELD and HELD are no action), 2 on bad input (an
issue with more than 100 labels, a malformed config or goals, an existing item naming no
issue) or a gh failure. Needs the gh CLI, authenticated, and with --plans uvx.
Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: the config is read with regexes instead
    tomllib = None  # type: ignore[assignment]

CONFIG = Path(".github/shipmill.toml")
INTAKE_LEVELS = ("observe", "propose")  # shipmill's autonomy: intake never acts
OUTCOMES_CEILING = 100  # spec 101: [agents] outcomes' ceiling, wip's (src/shipmill/agents.py's _MAX_WIP)
PLAIN_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
ARRAY_KEYS = ("repos",)  # the keys the 3.10 reader reads as a one-line array of strings: [product] repos
# The product home's config on its default branch (HEAD), read in a component (spec 101)
HOME_CONFIG = (
    "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) "
    '{ object(expression: "HEAD:.github/shipmill.toml") { ... on Blob { text } } } }'
)
# Labels whose issues are never feedback: bugs, tracking issues, and shipmill's own. Extend
# the list here for every repo, or per run with --skip-label
SKIP_LABELS = (
    "bug",
    "roadmap",
    "shipmill-proposal",
    "shipmill-hold",
    "incident",
    "release-blocker",
    "milestone-proposal",
    "goal-plan",  # a goal's plan, or the maintainer's request for one (spec 028): never a request for a feature
    "project",  # a project head or a filed plan item: the maintainer's accepted work (spec 106, #1774)
)
# Triage's own (#1628), as triage_state.py reads them: an issue labelled postponed (its
# --postponed-label default) with a trusted triage comment reads POSTPONED (#1766), and one labelled human
# or role:<name>, compared case-insensitively, is a person's item (spec 017, spec 036)
POSTPONED_LABEL = "postponed"
HUMAN_LABEL = "human"
ROLE_PREFIX = "role:"
SKIP_CATEGORIES = ("Announcements",)
# A postponed issue is triage's too (spec 074): an unattended pass must not group it
CLOSING_VERDICTS = ("implement", "feature", "duplicate", "won't fix", "won’t fix", "wont fix", "postpone")
OWN_VERDICT = "opportunity"  # intake's triage comment on an opportunity it opens
REASON_WINDOW = dt.timedelta(hours=1)  # "close with comment" posts the comment just before the close
ACTION = {"NEW_FEEDBACK", "ACCEPTED", "NO_REASON", "OVERLAP"}  # HELD is no action (spec 101)
# spec 106: an accepted opportunity's goal; GOAL_PROPOSAL_DUE is an action, ACCEPTED_INTO (its
# goal's plan takes it), GOAL_PROPOSED, and NEEDS_GOAL (the maintainer's answer) are none
ACTION |= {"GOAL_PROPOSAL_DUE"}
HELD_MARKER = "<!-- shipmill:intake-held -->"  # spec 101: the first line of intake's held comment
PROPOSE = re.compile(r"^propose\.?$", re.IGNORECASE)  # spec 101: the maintainer asks for a held outcome by name
ORDER = (
    "OVERLAP",
    "NO_REASON",
    "ACCEPTED",
    "NEW_FEEDBACK",
    "HELD",
    "OPPORTUNITY_OPEN",
    "HANDED_OFF",
    "DECLINED",
    "DONE",
    "MERGED",
)
LIVE = {"OPPORTUNITY_OPEN", "ACCEPTED", "HANDED_OFF", "DECLINED", "NO_REASON"}  # an OVERLAP counts these

# #1459: GitHub charges a query its worst-case requests over 100, rounded, at least 1 point: one
# request per connection, times the nodes of the connections it sits in, whatever its own first
# or last. A page of issues with labels and comments nested costs 1 + 2 x ISSUE_PAGE requests, so
# 70 (141) is 1 point where 75 (151) is 2; the nested connections' sizes cost no request, and a
# connection with none nested is 1 request at any size, so those read 100 a page, GitHub's most
ISSUE_PAGE = 70
PAGE = 100
# A comment with its author, so a triage verdict counts only from a trusted one (D-16, #1374)
COMMENT_FIELDS = "body createdAt author { __typename login } authorAssociation"
COMMENTS = f"comments(last: {PAGE}) {{ pageInfo {{ hasPreviousPage startCursor }} nodes {{ {COMMENT_FIELDS} }} }}"
OLDER = f"comments(last: {PAGE}, before: $cursor) {{ pageInfo {{ hasPreviousPage startCursor }} nodes {{ "
ISSUE_FIELDS = (
    """
        number title url state stateReason closedAt body milestone { title }
        author { __typename login } authorAssociation
        labels(first: 100) { pageInfo { hasNextPage } nodes { name } }
        reactions(content: THUMBS_UP) { totalCount }
        """
    + COMMENTS
    + """
"""
)
OPEN_ISSUES = (
    """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    hasDiscussionsEnabled
    issues(states: OPEN, first: """
    + str(ISSUE_PAGE)
    + """, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {"""
    + ISSUE_FIELDS
    + """      }
    }
  }
}
"""
)
OPPORTUNITIES = (
    """
query($owner: String!, $name: String!, $label: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(labels: [$label], first: """
    + str(ISSUE_PAGE)
    + """, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {"""
    + ISSUE_FIELDS
    + """      }
    }
  }
}
"""
)
DISCUSSIONS = (
    """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    discussions(first: """
    + str(PAGE)
    + """, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title url closed category { name } reactions(content: THUMBS_UP) { totalCount }
        author { __typename login }
      }
    }
  }
}
"""
)
OLDER_COMMENTS = (
    """
query($owner: String!, $name: String!, $number: Int!, $cursor: String!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      """
    + OLDER
    + COMMENT_FIELDS
    + """ } }
    }
  }
}
"""
)
REF = re.compile(
    r"https?://github\.com/(?P<o1>[\w.-]+)/(?P<n1>[\w.-]+)/(?:issues|discussions|pull)/(?P<k1>\d+)"
    r"|(?<![\w/#])(?:(?P<o2>[\w.-]+)/(?P<n2>[\w.-]+))?#(?P<k2>\d+)\b"
)
MEMBER_THUMBS = "... on Issue { reactions(content: THUMBS_UP) { totalCount } }"
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$")
Variables = dict[str, Any]
# Runs one GraphQL query with its variables and returns the parsed JSON response
Runner = Callable[[str, Variables], dict[str, Any]]

# -- goal plans (spec 028)
PLAN_LABEL = "goal-plan"
WATCH_STATE = Path(__file__).resolve().parents[2] / "github-ship-watch" / "scripts" / "watch_state.py"
TRIAGE_STATE = Path(__file__).resolve().parents[2] / "github-issue-triage" / "scripts" / "triage_state.py"
PLAN_ITEM = re.compile(r"^<!-- shipmill:plan-item #([1-9][0-9]*) W-[1-9][0-9]* -->$")
GOAL_ID = re.compile(r"(?<![\w-])G-[1-9][0-9]*(?![\w-])")
SERVES = re.compile(r"(?<![\w-])Serves:[ \t]*(G-[1-9][0-9]*(?:[ \t]*,[ \t]*G-[1-9][0-9]*)*)")
PLAN_FIELD_SERVES = re.compile(r"^\s*(?:[-*]\s+)?Serves:(.*)$")  # as pr_gate.py reads a plan's line
SPEC_STATUS = re.compile(r"^status:[ \t]*(\S+)[ \t]*$")
SPEC_SERVES = re.compile(r"^serves:(.*)$")
NOT_SPECS = ("TEMPLATE.md", "README.md")  # as specs.py skips them
SERVING_STATUSES = ("draft", "approved")
AUTOMATIC = ("no-work", "stalled")  # the triggers that wait for room under --wip
# PLAN_REPLACED (spec 106): an older open plan of a goal, to be closed for the newer one
PLAN_ACTION = {"PLAN_DUE", "PLAN_MALFORMED", "PLAN_ANSWERED", "PLAN_ACCEPTED", "PLAN_DONE", "PLAN_HOLD_MET"}
PLAN_ACTION |= {"PLAN_REPLACED"}
# PLAN_OVERDUE (spec 106): an open plan past its answer date, no action
PLAN_ORDER = (
    "PLAN_DUE",
    "PLAN_MALFORMED",
    "PLAN_ANSWERED",
    "PLAN_ACCEPTED",
    "PLAN_DONE",
    "PLAN_HOLD_MET",
    "PLAN_REPLACED",
    "PLAN_WAITS",
    "PLAN_OPEN",
    "PLAN_OVERDUE",
    "PLAN_HELD",
    "PLAN_FILED",
    "PLAN_DECLINED",
)
READ_CLOSED = ("NOT_PLANNED", "COMPLETED")  # the closed plans whose comments are paged back to their first
PLAN_OPENER = "<!-- shipmill:plan "  # a first line that means to be the plan marker, well-formed or not
SHIPMILL_MARKER = "<!-- shipmill:"  # a session's own marked comment, never an answer
REVISED = re.compile(r"^<!-- shipmill:plan-revised rev=([1-9][0-9]*) -->$")
# spec 106: a trusted reply whose first line sets the plan's answer date; it answers nothing
ANSWER_BY = re.compile(r"^answer by ([0-9]{4}-[0-9]{2}-[0-9]{2})\.?$", re.IGNORECASE)
ANSWER_DAYS = 7  # a plan's answer is due this many days after its newest revision (or re-check)
# spec 096: a first line starting with the word `accept` (not `accepted` or `acceptable`) is
# an accept, `accept`, `accept W-1, W-3`, or `accept except W-2`, or an unclear one
ACCEPT_WORD = re.compile(r"^accept(?!\w)", re.IGNORECASE)
EXCEPT_WORD = "except"
ID_SHAPE = re.compile(r"^w-[0-9]+$", re.IGNORECASE)
ID_SEPARATORS = re.compile(r"[\s,]+")
DECISION_MARKER = "<!-- shipmill:needs-decision -->"  # triage_state.py's: the first line of a session's question
OUTCOME_MARKER = "<!-- shipmill:plan-outcome -->"  # spec 097: the first line of a finished plan's outcome
STILL_MISSING = "Still missing:"  # the outcome's list of what the plan's end state still lacks
NOTHING = "nothing"  # `- nothing`: a list with no part
# How a closed item closed, as a plan's PLAN_DONE note names it (spec 097)
CLOSED_AS = {"COMPLETED": "completed", "NOT_PLANNED": "not planned", "DUPLICATE": "duplicate"}
DECLINE = re.compile(r"^decline", re.IGNORECASE)
# spec 098: a first line starting `hold until` is a hold, never an edit; its rest is one condition
HOLD = re.compile(r"^hold\s+until(?![\w-])", re.IGNORECASE)
HOLD_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
HOLD_RELEASE = "release"
RECHECK_MARKER = "<!-- shipmill:plan-recheck -->"  # spec 098: the first line of a held plan's re-check
UTC = dt.timezone.utc  # noqa: UP017 (dt.UTC needs 3.11)
# triage_state.py's STABLE and how it reads a tag's time (spec 061): a test checks they agree
STABLE = re.compile(r"^v?\d+\.\d+\.\d+$")
TAG_NODES = "nodes { name target { ... on Tag { tagger { date } } ... on Commit { committedDate } } }"
TAGS = (
    """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    tags: refs(refPrefix: "refs/tags/", last: 50, orderBy: {field: TAG_COMMIT_DATE, direction: ASC}) {
      """
    + TAG_NODES
    + """
    }
  }
}
"""
)
HELD_ITEM = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issueOrPullRequest(number: $number) { ... on Issue { state closedAt } ... on PullRequest { state closedAt } }
  }
}
"""
UNREADABLE = frozenset({"NOT_FOUND", "FORBIDDEN"})  # chains.py's: no such repo or item, or no access
# An answer given in a session and relayed by the --bot-login (D-68): the first line is the
# needs-decision relay, the login bare or in a code span (D-61). Copied from triage_state.py's
# LOGIN_PATTERN and DECISION_BY, which the skill scripts can't import from each other; a test
# checks the two agree
LOGIN_PATTERN = r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}"
DECISION_BY = re.compile(
    r"Decision by (?:@(" + LOGIN_PATTERN + r")(?=$|\s|[,;:)]|[.!?](?:\s|$))|`@(" + LOGIN_PATTERN + r")`(?![\w`-]))"
)
AGENT_MARKER = re.compile(r"<!-- shipmill:agent(?:\s[^>]*)?-->")  # triage_state.py's, which shipmill gh appends
NOTE_START = "note:"  # retro.py's: a relay's line starting `Note:` ends what is read (D-93); a test checks they agree
# The --role flags, as triage_state.py takes them (spec 036): only the maintainer's logins are read here
MAINTAINER = "maintainer"
ROLE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,44}")
USER = re.compile(LOGIN_PATTERN)
TEAM = re.compile(r"@" + LOGIN_PATTERN + r"/[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
FILED_KINDS = ("feature", "fix")
EXISTING_REF = re.compile(r"^(?:([\w.-]+)/([\w.-]+))?#([1-9][0-9]*)$")
PLAN_COMMENT = COMMENT_FIELDS
PLAN_ISSUES = (
    """
query($owner: String!, $name: String!, $label: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(labels: [$label], first: """
    + str(ISSUE_PAGE)
    + """, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title url state stateReason closedAt createdAt lastEditedAt body
        author { __typename login } authorAssociation
        labels(first: 100) { pageInfo { hasNextPage } nodes { name } }
        """
    + COMMENTS
    + """
      }
    }
  }
}
"""
)
OLDER_PLAN_COMMENTS = (
    """
query($owner: String!, $name: String!, $number: Int!, $cursor: String!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      """
    + OLDER
    + PLAN_COMMENT
    + """ } }
    }
  }
}
"""
)
PULLS = (
    """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    specs: object(expression: "HEAD:docs/specs") { ... on Tree { entries { name object { ... on Blob { text } } } } }
    pullRequests(states: OPEN, first: """
    + str(PAGE)
    + """, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number body }
    }
  }
}
"""
)


def fail(message: str) -> NoReturn:
    sys.stderr.write(f"error: {message}\n")
    raise SystemExit(2)


def load_plans() -> ModuleType:
    """plans.py beside this script: the plan marker, the body's sections, and D-29's trust"""
    path = Path(__file__).resolve().parent / "plans.py"
    spec = importlib.util.spec_from_file_location("shipmill_plans", path)
    if spec is None or spec.loader is None:
        fail(f"can't load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


PLANS = load_plans()


def gh_graphql(query: str, variables: Variables) -> dict[str, Any]:
    """The default runner: one ``gh api graphql`` call"""
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        # -F sends an int as a number; -f keeps a string a string (a cursor, a numeric repo name)
        cmd += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(2)
    response: dict[str, Any] = json.loads(proc.stdout)
    return response


def gh_graphql_unreadable(query: str, variables: Variables) -> dict[str, Any]:
    """gh_graphql for a held plan's item (spec 098): a failed call whose answer is data with only
    NOT_FOUND or FORBIDDEN errors, as GitHub gives for an item or repository the token can't
    read, is that answer; every other failure still exits 2"""
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        cmd += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        try:
            answer = json.loads(proc.stdout)
        except ValueError:
            answer = None
        errors = answer.get("errors") if isinstance(answer, dict) else None
        if isinstance(answer, dict) and isinstance(errors, list) and errors and unreadable(errors):
            return answer
        sys.stderr.write(proc.stderr)
        raise SystemExit(2)
    response: dict[str, Any] = json.loads(proc.stdout)
    return response


def unreadable(errors: list[Any]) -> bool:
    return all(isinstance(e, dict) and e.get("type") in UNREADABLE for e in errors)


def split_repo(repo: str) -> tuple[str, str]:
    owner, _, name = repo.partition("/")
    if not owner or not name or "/" in name:
        fail(f"repo must be owner/name, got {repo!r}")
    return owner, name


def repository(run: Runner, query: str, variables: Variables) -> dict[str, Any]:
    response = run(query, variables)
    if response.get("errors"):
        fail(f"GitHub GraphQL errors: {json.dumps(response['errors'])}")
    data = (response.get("data") or {}).get("repository")
    if data is None:
        fail(f"no repository {variables['owner']}/{variables['name']} in the GraphQL response")
    result: dict[str, Any] = data
    return result


def paged(run: Runner, query: str, variables: Variables, key: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every node of one connection, oldest first, and the first page's repository fields"""
    first: dict[str, Any] | None = None
    nodes: list[dict[str, Any]] = []
    cursor: str | None = None
    seen: set[str] = set()
    while True:
        data = repository(run, query, {**variables, **({"cursor": cursor} if cursor else {})})
        first = first if first is not None else data
        nodes += data[key]["nodes"]
        info = data[key]["pageInfo"]
        if not info["hasNextPage"]:
            return nodes, first
        cursor = info["endCursor"]
        if not cursor or cursor in seen:
            fail(f"GitHub reported more {key}, but the page cursor did not advance ({cursor!r})")
        seen.add(cursor)


def labels(issue: dict[str, Any]) -> set[str]:
    if issue["labels"]["pageInfo"]["hasNextPage"]:
        fail(f"bad input: issue #{issue['number']} has more than 100 labels, which intake_state.py does not page")
    return {n["name"] for n in issue["labels"]["nodes"]}


def verdict(body: str, marker: str) -> str | None:
    """A triage comment's verdict, lowercased: its first bold phrase, else its first word;
    None for a comment that isn't a triage comment"""
    text = body.lstrip()
    if not text.startswith(marker):
        return None
    rest = text[len(marker) :].strip()
    bold = re.match(r"\*\*([^*]+)\*\*", rest)
    if bold:
        return bold.group(1).strip().lower()
    return rest.split(maxsplit=1)[0].lower() if rest else ""


def trusted_triage(issue: dict[str, Any], marker: str, bot_login: str | None) -> dict[str, Any] | None:
    """The issue's newest triage comment by an OWNER, MEMBER, or COLLABORATOR or the
    --bot-login (D-16), None without one: anyone else's `Triage:` comment is read as absent,
    so a stranger can neither hide a request from intake nor hand one over (#1374)"""
    for comment in reversed(issue["comments"]["nodes"]):
        if verdict(comment["body"], marker) is not None and PLANS.trusted(comment, bot_login):
            found: dict[str, Any] = comment
            return found
    return None


def trusted_verdict(issue: dict[str, Any], marker: str, bot_login: str | None) -> str | None:
    comment = trusted_triage(issue, marker, bot_login)
    return None if comment is None else verdict(comment["body"], marker)


def handed_at(issue: dict[str, Any], marker: str, bot_login: str | None = None) -> str | None:
    """The createdAt of the issue's newest trusted triage comment when its verdict is triage's
    opportunity hand-off (spec 074), None otherwise"""
    comment = trusted_triage(issue, marker, bot_login)
    if comment is None or not (verdict(comment["body"], marker) or "").startswith(OWN_VERDICT):
        return None
    return str(comment["createdAt"])


def opener(node: dict[str, Any]) -> str | None:
    """The opener's login as --bot-login spells it (a Bot's ending [bot]), None when GitHub returns none"""
    author = node.get("author")
    return PLANS.login(author) if author else None


def complete_comments(
    run: Runner, owner: str, name: str, issue: dict[str, Any], marker: str, bot_login: str | None = None
) -> None:
    """Page an issue's comments back, oldest first, only while none of them is a trusted
    triage comment: the newest triage comment, and the newest trusted one, is all intake reads
    from an issue's history"""
    comments = issue["comments"]
    seen: set[str] = set()
    while comments["pageInfo"]["hasPreviousPage"] and trusted_triage(issue, marker, bot_login) is None:
        cursor = comments["pageInfo"]["startCursor"]
        if not cursor or cursor in seen:
            fail(f"GitHub reported more comments on #{issue['number']}, but the page cursor did not advance")
        seen.add(cursor)
        variables: Variables = {"owner": owner, "name": name, "number": issue["number"], "cursor": cursor}
        page = (repository(run, OLDER_COMMENTS, variables).get("issue") or {}).get("comments")
        if page is None:
            fail(f"issue #{issue['number']} vanished while paging its comments")
        comments["nodes"] = page["nodes"] + comments["nodes"]
        comments["pageInfo"] = page["pageInfo"]


def evidence(body: str, owner: str, name: str, section: str = "evidence") -> set[int]:
    """The issue and discussion numbers the body's "Evidence" section (or another, by its
    lowercased heading) links in this repo"""
    found: set[int] = set()
    inside = False
    for line in (body or "").splitlines():
        heading = HEADING.match(line)
        if heading:
            inside = heading.group(1).lower() == section
            continue
        if not inside:
            continue
        for m in REF.finditer(line):
            ref_owner, ref_name = (m["o1"], m["n1"]) if m["k1"] else (m["o2"], m["n2"])
            same = ref_owner is None or (ref_owner.lower(), ref_name.lower()) == (owner.lower(), name.lower())
            if same:
                found.add(int(m["k1"] or m["k2"]))
    return found


def timestamp(text: str) -> dt.datetime:
    """A GitHub ISO 8601 time; "Z", which fromisoformat rejects before Python 3.11, made an offset"""
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        fail(f"gh returned a time that isn't ISO 8601: {text!r}")
    if moment.tzinfo is None:
        fail(f"gh returned a time without a timezone: {text!r}")
    return moment


def decline_reason(issue: dict[str, Any], marker: str, bot_login: str | None = None) -> str | None:
    """The first line of the oldest comment that isn't a trusted triage comment, from an hour
    before the close on: the maintainer's reason, not a later reply on the closed issue; None
    when there is none. Anyone else's `Triage:` comment is an ordinary comment here (#1384)"""
    closed = timestamp(issue["closedAt"]) - REASON_WINDOW
    for comment in issue["comments"]["nodes"]:
        triage = verdict(comment["body"], marker) is not None and PLANS.trusted(comment, bot_login)
        if not triage and timestamp(comment["createdAt"]) >= closed:
            lines = [line.strip() for line in comment["body"].splitlines() if line.strip()]
            if lines:
                return lines[0]
    return None


def opportunity_state(
    issue: dict[str, Any], accepted: str, marker: str, bot_login: str | None = None
) -> tuple[str, str]:
    if issue["state"] == "CLOSED":
        if issue["stateReason"] == "NOT_PLANNED":
            reason = decline_reason(issue, marker, bot_login)
            return ("DECLINED", reason) if reason else ("NO_REASON", "closed as not planned with no comment")
        if issue["stateReason"] == "DUPLICATE":
            return "MERGED", "closed as a duplicate"
        return "DONE", ""
    if accepted not in labels(issue):
        return "OPPORTUNITY_OPEN", ""
    found = trusted_verdict(issue, marker, bot_login)
    if found is None or found.startswith(OWN_VERDICT):
        return "ACCEPTED", "hand it to triage's spec gate"
    return "HANDED_OFF", f"triage: {found}"


def skip_labels(extra: list[str]) -> set[str]:
    """SKIP_LABELS and the run's --skip-label additions"""
    return {*SKIP_LABELS, *extra}


def triage_owns(issue: dict[str, Any], marker: str, bot_login: str | None) -> bool:
    """Labelled postponed with a trusted triage comment (#1766: without one, triage reads it
    NEW), or a person's item (human or role:<name>, any case) (#1628)"""
    folded = {n.lower() for n in labels(issue)}
    if HUMAN_LABEL in folded or any(n.startswith(ROLE_PREFIX) for n in folded):
        return True
    return POSTPONED_LABEL in labels(issue) and trusted_triage(issue, marker, bot_login) is not None


def plan_item(issue: dict[str, Any], bot_login: str | None) -> bool:
    """An accepted plan's filed item (#1774): its body's first line the plan-item marker, by
    the --bot-login or an OWNER, MEMBER, or COLLABORATOR (D-16); an outsider's copy is none"""
    return PLAN_ITEM.match(PLANS.first_line(issue.get("body") or "")) is not None and PLANS.trusted(issue, bot_login)


def is_feedback(issue: dict[str, Any], skip: set[str], marker: str, bot_login: str | None = None) -> bool:
    names = labels(issue)
    if names & skip or triage_owns(issue, marker, bot_login) or plan_item(issue, bot_login):
        return False
    found = trusted_verdict(issue, marker, bot_login)
    return found is None or not found.startswith(CLOSING_VERDICTS)


@dataclass
class Item:
    """An issue or a discussion, as intake counts it"""

    number: int
    kind: str  # issue, discussion, or opportunity
    title: str
    thumbs: int
    feedback: bool = False
    state: str = ""
    note: str = ""
    members: list[int] = field(default_factory=list)
    # spec 074: the opener, their author association (None for a discussion), and when
    # triage handed the issue over (its opportunity verdict's createdAt), None otherwise
    author: str | None = None
    association: str | None = None
    handed: str | None = None
    # spec 101: the createdAt of the request's newest held comment newer than its newest
    # trusted triage comment, None without one; and whether a trusted `propose` reply is newer
    held: str | None = None
    asked: bool = False


def held_comment(issue: dict[str, Any], marker: str, bot_login: str | None) -> dict[str, Any] | None:
    """The request's newest held comment (spec 101): first line the held marker, the agent
    marker in its body (D-62), by the --bot-login or an OWNER, MEMBER, or COLLABORATOR (D-16),
    and newer than the newest trusted triage comment; None without one"""
    triage = trusted_triage(issue, marker, bot_login)
    since = None if triage is None else timestamp(triage["createdAt"])
    for comment in reversed(issue["comments"]["nodes"]):
        body = comment.get("body")
        if not isinstance(body, str) or PLANS.first_line(body) != HELD_MARKER:
            continue
        if not AGENT_MARKER.search(body) or not PLANS.trusted(comment, bot_login):
            continue
        if since is not None and timestamp(comment["createdAt"]) <= since:
            return None
        found: dict[str, Any] = comment
        return found
    return None


def asked_by_name(issue: dict[str, Any], held: dict[str, Any], bot_login: str | None) -> bool:
    """A reply newer than the held comment whose first line is `propose` (any case, an optional
    final period), from an OWNER, MEMBER, or COLLABORATOR other than the --bot-login, with no
    agent marker (spec 101). A reply whose author or body can't be read is an agent's (D-62)"""
    since = timestamp(held["createdAt"])
    for comment in issue["comments"]["nodes"]:
        body, author = comment.get("body"), comment.get("author")
        if not isinstance(body, str) or not author or timestamp(comment["createdAt"]) <= since:
            continue
        if str(comment.get("authorAssociation") or "NONE") not in PLANS.TRUSTED or AGENT_MARKER.search(body):
            continue
        if bot_login is not None and PLANS.login(author).lower() == bot_login.lower():
            continue
        if PROPOSE.match(PLANS.first_line(body)):
            return True
    return False


def held_date(created: str) -> str:
    """A held comment's date, YYYY-MM-DD in UTC"""
    return timestamp(created).astimezone(UTC).date().isoformat()


@dataclass
class Intake:
    autonomy: str
    opportunities: list[Item]
    feedback: list[Item]
    thumbs: dict[int, int]  # every issue and discussion number with a known thumbs-up count
    # as GitHub returned them, comments paged back to the newest triage comment: the open
    # issues but opportunities, and every opportunity; --plans reads them again
    open_issues: list[dict[str, Any]] = field(default_factory=list)
    opportunity_issues: list[dict[str, Any]] = field(default_factory=list)


def fetch(
    repo: str,
    *,
    label: str,
    accepted: str,
    marker: str,
    skip: set[str],
    categories: set[str] | None,
    autonomy: str,
    bot_login: str | None = None,
    run: Runner = gh_graphql,
) -> Intake:
    owner, name = split_repo(repo)
    base: Variables = {"owner": owner, "name": name}
    opened, first = paged(run, OPEN_ISSUES, base, "issues")
    opened = [i for i in opened if label not in labels(i)]  # an open opportunity comes with the rest
    opps, _ = paged(run, OPPORTUNITIES, {**base, "label": label}, "issues")
    for issue in opened + opps:
        complete_comments(run, owner, name, issue, marker, bot_login)
    thumbs = {i["number"]: i["reactions"]["totalCount"] for i in opened + opps}
    feedback = []
    for i in opened:
        if not is_feedback(i, skip, marker, bot_login):
            continue
        held = held_comment(i, marker, bot_login)
        feedback.append(
            Item(
                i["number"],
                "issue",
                i["title"],
                i["reactions"]["totalCount"],
                feedback=True,
                author=opener(i),
                association=i.get("authorAssociation"),
                handed=handed_at(i, marker, bot_login),
                held=None if held is None else str(held["createdAt"]),
                asked=held is not None and asked_by_name(i, held, bot_login),
            )
        )
    if first["hasDiscussionsEnabled"]:
        discussions, _ = paged(run, DISCUSSIONS, base, "discussions")
        for d in discussions:
            thumbs[d["number"]] = d["reactions"]["totalCount"]
            category = (d.get("category") or {}).get("name", "")
            counted = category in categories if categories is not None else category not in SKIP_CATEGORIES
            if not d["closed"] and counted:
                thumbs_up = d["reactions"]["totalCount"]
                feedback.append(Item(d["number"], "discussion", d["title"], thumbs_up, True, author=opener(d)))
    opportunities = []
    for issue in opps:
        state, note = opportunity_state(issue, accepted, marker, bot_login)
        members = sorted(evidence(issue["body"], owner, name) - {issue["number"]})
        item = Item(issue["number"], "opportunity", issue["title"], issue["reactions"]["totalCount"])
        item.state, item.note, item.members = state, note, members
        item.author, item.association = opener(issue), issue.get("authorAssociation")
        opportunities.append(item)
    missing = sorted({m for o in opportunities for m in o.members} - set(thumbs))
    thumbs.update(member_thumbs(run, owner, name, missing))
    return Intake(autonomy, opportunities, feedback, thumbs, opened, opps)


def member_thumbs(run: Runner, owner: str, name: str, numbers: list[int]) -> dict[int, int]:
    """Thumbs-up counts of members fetch didn't see (closed issues), 50 to a query; a number
    that is a pull request or doesn't exist counts 0"""
    found: dict[int, int] = {}
    for start in range(0, len(numbers), 50):
        chunk = numbers[start : start + 50]
        parts = " ".join(f"m{n}: issueOrPullRequest(number: {n}) {{ {MEMBER_THUMBS} }}" for n in chunk)
        query = f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {parts} }} }}"
        data = repository(run, query, {"owner": owner, "name": name})
        for n in chunk:
            node = data.get(f"m{n}") or {}
            found[n] = (node.get("reactions") or {}).get("totalCount", 0)
    return found


def feedback_state(item: Item, room: int | None) -> tuple[str, str]:
    """A request no opportunity lists (spec 101): with a limit, a held request reads HELD at
    room 0 and NEW_FEEDBACK above it, noted `held since <date>`, or NEW_FEEDBACK noted `asked
    by name` whatever the room; without a limit (room None) every one reads NEW_FEEDBACK as before"""
    if room is None or item.held is None:
        return "NEW_FEEDBACK", item.kind
    if item.asked:
        return "NEW_FEEDBACK", "asked by name"
    return ("HELD" if room == 0 else "NEW_FEEDBACK"), f"held since {held_date(item.held)}"


EARLIEST = dt.datetime.min.replace(tzinfo=UTC)


def row_order(row: Item, room: int | None) -> tuple[int, int, dt.datetime, int]:
    """The rows' order: by state, then, with a limit, held requests first, oldest held comment
    first (spec 101), then newest number first as before"""
    if room is None or row.held is None or row.state not in ("NEW_FEEDBACK", "HELD"):
        return ORDER.index(row.state), 1, EARLIEST, -row.number
    return ORDER.index(row.state), 0, timestamp(row.held), -row.number


def rows(intake: Intake, room: int | None = None) -> list[Item]:
    """The opportunities with their evidence, then NEW_FEEDBACK, HELD (with a limit's room,
    spec 101), and OVERLAP"""
    listed: dict[int, list[int]] = {}
    found = [
        replace(o, thumbs=o.thumbs + sum(intake.thumbs.get(m, 0) for m in o.members)) for o in intake.opportunities
    ]
    for o in intake.opportunities:
        if o.state != "MERGED":
            for m in o.members:
                listed.setdefault(m, []).append(o.number)
    for item in intake.feedback:
        if item.number not in listed:
            item.state, item.note = feedback_state(item, room)
            found.append(item)
    states = {o.number: o.state for o in intake.opportunities}
    titles = {i.number: (i.kind, i.title) for i in intake.feedback}
    for number, owners in sorted(listed.items()):
        live = [o for o in owners if states[o] in LIVE]
        if len(live) > 1:
            kind, title = titles.get(number, ("member", ""))
            shown = ", ".join(f"#{o}:{states[o].lower()}" for o in live)
            found.append(Item(number, kind, title, intake.thumbs.get(number, 0), state="OVERLAP", note=shown))
    found.sort(key=lambda r: row_order(r, room))
    return found


# -- goal plans (spec 028): which goals a plan is due for


GOAL_KINDS = ("goal", "measure")  # spec 105: a goal's kind in `product show --json`, or null
GOAL_ENDS = ("met", "dropped")  # spec 106: a goal's state in `product show --json`, or null


@dataclass(frozen=True)
class Goal:
    id: str  # G-<n>
    text: str
    kind: str | None = None  # spec 105: goal, measure, or None for neither form (or a shipmill before it)
    state: str | None = None  # spec 106: met, dropped, or None while open (or a shipmill before it)
    by: str | None = None  # spec 105: a goal's horizon as written, a date or a release; None otherwise
    past: bool | None = None  # spec 105: a date horizon has ended; None for a release or no horizon


@dataclass
class PlanRow:
    goal: str | None  # None for a plan whose marker names no goal
    state: str
    title: str  # the goal's text, or the plan issue's title
    note: str
    number: int | None = None  # the request issue for a requested plan, the plan issue for a plan's row
    kind: str = "goal"  # goal: a row per goal (PLAN_DUE, PLAN_WAITS); plan: a row per plan issue
    author: str | None = None  # a plan issue's opener, as --bot-login spells a login; None for a goal's row
    association: str | None = None  # the opener's author association (#1680); None for a goal's row
    # spec 096: an accepted plan's kept and dropped ids, in Work order, None on any other row;
    # on a PLAN_DUE row, dropped holds each item an earlier plan of the goal dropped instead
    kept: tuple[str, ...] | None = None
    dropped: tuple[Any, ...] | None = None
    # spec 097: on a goal's row after a finished plan with a trusted outcome, that plan's
    # number and the outcome's `Still missing:` items; None otherwise
    follows: int | None = None
    missing: tuple[str, ...] | None = None
    # spec 098: on a PLAN_HELD, PLAN_HOLD_MET, or a re-checked PLAN_OPEN row, the hold's
    # condition as written and when it was met (ISO 8601 UTC, None while not met); None otherwise
    hold: tuple[str, str | None] | None = None
    answer_by: str | None = None  # spec 106: a PLAN_OPEN or PLAN_OVERDUE row's answer date, YYYY-MM-DD


# Reads the direction's goals, in the direction's order
GoalsReader = Callable[[], list[Goal]]
# The room `triage_state.py --wip N` reports under the limit N
RoomReader = Callable[[int], int]


def parse_goals(text: str) -> list[Goal]:
    """`shipmill product show --section goals --json`'s output, strictly; a goal's `kind`
    (spec 105) is `goal`, `measure`, or null, and its `state` (spec 106) `met`, `dropped`, or
    null; either absent reads as null, as a pinned shipmill before those specs prints it"""
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        fail(f"shipmill product show printed no JSON: {exc}")
    listed = record.get("goals") if isinstance(record, dict) else None
    if not isinstance(listed, list):
        fail("shipmill product show --json printed no `goals` list")
    goals: list[Goal] = []
    for entry in listed:
        ident = entry.get("id") if isinstance(entry, dict) else None
        text_ = entry.get("text") if isinstance(entry, dict) else None
        if not isinstance(ident, str) or not GOAL_ID.fullmatch(ident) or not isinstance(text_, str):
            fail(f"shipmill product show --json listed a goal that isn't an id and a text: {entry!r}")
        kind = entry.get("kind")
        if kind is not None and kind not in GOAL_KINDS:
            fail(f"shipmill product show --json listed a goal whose kind isn't goal, measure, or null: {entry!r}")
        state = entry.get("state")
        if state is not None and state not in GOAL_ENDS:
            fail(f"shipmill product show --json listed a goal whose state isn't met, dropped, or null: {entry!r}")
        by, past = entry.get("by"), entry.get("past")
        horizon = None
        if by is not None:
            values = list(by.values()) if isinstance(by, dict) and set(by) in ({"date"}, {"release"}) else []
            if len(values) != 1 or not isinstance(values[0], str) or not values[0]:
                fail(f"shipmill product show --json listed a goal whose by isn't a date or a release: {entry!r}")
            horizon = values[0]
        if past is not None and not isinstance(past, bool):
            fail(f"shipmill product show --json listed a goal whose past isn't true, false, or null: {entry!r}")
        goals.append(Goal(ident, text_, kind, state, horizon, past))
    return goals


def shipmill_command(tool: str | None, plugin: Path | None = None) -> list[str]:
    """How the CLI runs: `uvx shipmill==<version>`, the version in the plugin's own
    .claude-plugin/plugin.json (spec 031), or `uvx --from <tool> shipmill` with --tool. It is
    github-ship-watch's watch_state.py's shipmill_cli; a broken plugin.json exits 2 naming it"""
    ws = watch_module()
    try:
        found: list[str] = ws.shipmill_cli(tool, plugin or ws.PLUGIN_JSON)
    except ws.Refused as refused:
        fail(str(refused).removeprefix("error: "))
    return found


def watch_module() -> ModuleType:
    """github-ship-watch's watch_state.py, loaded once"""
    loaded = sys.modules.get("shipmill_watch_state")
    if loaded is not None:
        return loaded
    spec = importlib.util.spec_from_file_location("shipmill_watch_state", WATCH_STATE)
    if spec is None or spec.loader is None:
        fail(f"can't load {WATCH_STATE}")
    ws = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ws  # its dataclasses look their module up by name
    spec.loader.exec_module(ws)
    return ws


def run_uvx(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def uvx_goals(
    tool: str | None, execute: Callable[[list[str]], subprocess.CompletedProcess[str]] = run_uvx
) -> GoalsReader:
    """The default goals reader: the direction of the checkout in the current directory, with
    --local: parse_goals reads only its own goals, so a component never reads its product
    home's here, and a home it can't read doesn't stop it (spec 071, #1417). A pinned shipmill
    uv finds no version of runs once more with its index refreshed, as watch_state.py's
    pinned does (#597)"""

    def read() -> list[Goal]:
        cmd = [*shipmill_command(tool), "product", "show", "--section", "goals", "--json", "--local"]
        try:
            proc: subprocess.CompletedProcess[str] = watch_module().pinned(cmd, execute)
        except FileNotFoundError:
            fail("uvx is not on PATH: --plans reads the goals with `shipmill product show`")
        if proc.returncode != 0:
            fail(f"shipmill product show failed with exit {proc.returncode}: {proc.stderr.strip()}")
        return parse_goals(proc.stdout)

    return read


def triage_room(repo: str, bot_login: str | None, script: Path = TRIAGE_STATE) -> RoomReader:
    """The default room reader: `triage_state.py <repo> --wip N --json`'s last line"""

    def read(wip: int) -> int:
        cmd = [sys.executable, str(script), repo, "--wip", str(wip), "--json"]
        cmd += ["--bot-login", bot_login] if bot_login else []
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode not in (0, 1):  # 1 is "an issue needs action", not a failure
            fail(f"triage_state.py --wip failed with exit {proc.returncode}: {proc.stderr.strip()}")
        lines = proc.stdout.strip().splitlines()
        try:
            room = json.loads(lines[-1])["room"] if lines else None
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            fail(f"triage_state.py --wip --json printed no room line: {exc}")
        if not isinstance(room, int):
            fail(f"triage_state.py --wip --json printed no room line: {lines[-1:]!r}")
        return room

    return read


def goal_ids(text: str) -> set[str]:
    return set(GOAL_ID.findall(text))


def serves(text: str) -> set[str]:
    """The goal ids every `Serves: G-n[, G-m]` in the text names"""
    return {g for m in SERVES.finditer(text) for g in goal_ids(m.group(1))}


def spec_serves(text: str) -> set[str]:
    """The goals a spec serves while its status is draft or approved: its serves: line, read
    from its header (the lines before the first `## ` heading)"""
    status: str | None = None
    named: set[str] = set()
    for line in text.splitlines():
        if line.startswith("## "):
            break
        found = SPEC_STATUS.match(line)
        if found and status is None:
            status = found.group(1)
            continue
        listed = SPEC_SERVES.match(line)
        if listed:
            named |= goal_ids(listed.group(1))
    return named if status in SERVING_STATUSES else set()


def plan_serves(body: str) -> set[str]:
    """The goals a pull request's `## Plan` names in its `Serves:` line"""
    named: set[str] = set()
    for _, level, heading, lines in PLANS.sections(body or ""):
        if level == 2 and heading == "Plan":
            for _, line in lines:
                field_ = PLAN_FIELD_SERVES.match(line)
                if field_:
                    named |= goal_ids(field_.group(1))
    return named


def plan_goal(issue: dict[str, Any]) -> str | None:
    """The goal a plan issue's first-line marker names, None without the marker"""
    found = PLANS.MARKER.match(PLANS.first_line(issue.get("body") or ""))
    return found.group(1) if found else None


def plan_rows(
    goals: list[Goal],
    *,
    open_issues: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
    plan_issues: list[dict[str, Any]],
    pulls: list[dict[str, Any]],
    specs: list[str],
    marker: str,
    bot_login: str | None,
    wip: int | None,
    room: RoomReader,
    maintainers: frozenset[str] = frozenset(),
    checked: set[str] | None = None,
    into: dict[str, tuple[int, dt.datetime]] | None = None,
) -> list[PlanRow]:
    """One PLAN_DUE or PLAN_WAITS row per goal a trigger holds for and no open plan has; a
    PLAN_DUE row's dropped lists the items the goal's earlier plans dropped (spec 096). After
    the goal's newest plan closed as completed with a trusted outcome, the row follows it (its
    note ends `; follows #P`, with the outcome's `Still missing:` items); without an outcome,
    that plan reads PLAN_DONE and no `no-work` row is read for its goal (spec 097)"""
    listed = {g.id for g in goals}
    cut = dropped_items(plan_issues, frozenset(listed), marker, bot_login, maintainers)
    plans_of: dict[int, str] = {}  # each plan issue's goal
    newest = newest_plans(plan_issues)  # each goal's newest plan issue
    planned: set[str] = set()  # goals with an open plan issue
    opened: dict[str, dt.datetime] = {}  # spec 106: when each goal's newest open plan was opened
    for issue in plan_issues:
        goal = plan_goal(issue)
        if goal is None:
            continue
        plans_of[issue["number"]] = goal
        if issue["state"] == "OPEN":
            planned.add(goal)
            at = timestamp(issue["createdAt"])
            opened[goal] = max(opened.get(goal, at), at)
    # a replaced plan (spec 106) is neither declined nor answered: its goal's no-work trigger reads on
    declined = {
        g
        for g, i in newest.items()
        if i["state"] == "CLOSED" and i["stateReason"] == "NOT_PLANNED" and not replaced(i, bot_login)
    }
    finished: set[str] = set()  # goals whose newest plan reads PLAN_DONE `closed without an outcome`
    follows: dict[str, tuple[int, tuple[str, ...]]] = {}  # the plan a goal's next one follows, and what it left missing
    for goal, issue in newest.items():
        if issue["state"] != "CLOSED" or issue["stateReason"] != "COMPLETED":
            continue
        found = plan_outcome(issue, bot_login)
        if found is None:
            finished.add(goal)
        elif goal_check_holds(found.get("body") or ""):  # spec 106: the Met pull request waits
            finished.add(goal)
            if checked is not None:
                checked.add(goal)
        else:
            follows[goal] = (issue["number"], still_missing(found.get("body") or ""))

    def row(goal: Goal, state: str, note: str, number: int | None = None) -> PlanRow:
        dropped = cut.get(goal.id, ()) if state == "PLAN_DUE" else None  # spec 096: a PLAN_DUE row's alone
        if goal.id not in follows:
            return PlanRow(goal.id, state, goal.text, note, number, dropped=dropped)
        plan, missing = follows[goal.id]
        note = f"{note}; follows #{plan}"
        return PlanRow(goal.id, state, goal.text, note, number, dropped=dropped, follows=plan, missing=missing)

    served: set[str] = set()
    for text in specs:
        served |= spec_serves(text)
    for pull in pulls:
        served |= plan_serves(pull.get("body") or "")
    for opp in opportunities:
        if opp["state"] == "OPEN":
            served |= serves(opp.get("body") or "")
    requests: dict[str, int] = {}
    for issue in open_issues:
        triage = trusted_triage(issue, marker, bot_login)  # D-16: a stranger's `Serves:` serves nothing (#1384)
        served |= serves(triage["body"] if triage else "")
        first = PLANS.first_line(issue.get("body") or "")
        item = PLAN_ITEM.match(first)
        if item and PLANS.trusted(issue, bot_login) and int(item.group(1)) in plans_of:
            served.add(plans_of[int(item.group(1))])
        if PLAN_LABEL not in labels(issue) or is_plan(issue, bot_login):
            continue
        if str(issue.get("authorAssociation") or "NONE") not in PLANS.TRUSTED:
            continue  # D-16: only the maintainer's side requests a plan
        named = goal_ids(issue.get("title") or "")
        if len(named) == 1 and named <= listed:
            (goal,) = named
            asked_at = timestamp(issue["createdAt"]) if issue.get("createdAt") else None
            if goal in opened and (asked_at is None or asked_at <= opened[goal]):
                continue  # S-106-10: a plan opened since the request answers it
            requests[goal] = min(requests.get(goal, issue["number"]), issue["number"])

    found: list[PlanRow] = []
    left: int | None = None  # the room under --wip, read once and only when a goal waits on it
    for goal in goals:
        if goal.state is not None:  # S-106-3: a met or dropped goal reads no trigger, a request's either
            continue
        if goal.id in requests:  # S-106-10: with or without an open plan, which the new one replaces
            number = requests[goal.id]
            found.append(row(goal, "PLAN_DUE", f"requested in #{number}", number))
            continue
        accepted = (into or {}).get(goal.id)
        latest = newest.get(goal.id)  # its newest plan in any state: a declined one answered it too
        if accepted is not None and (latest is None or accepted[1] > timestamp(latest["createdAt"])):
            found.append(row(goal, "PLAN_DUE", f"opportunity #{accepted[0]} accepted", accepted[0]))  # S-106-22
            continue
        if goal.id in planned:
            continue
        if goal.kind == "measure":  # spec 105: a standing measure is planned only on request
            continue
        # `stalled` reads spec 027's report, which isn't built: until it is, it never fires
        if goal.id in served or goal.id in declined or goal.id in finished:  # the outcome comes first
            continue
        trigger = "no-work"
        if wip is not None:
            left = room(wip) if left is None else left
            if left <= 0:
                found.append(row(goal, "PLAN_WAITS", f"{trigger}; waits for room"))
                continue
        found.append(row(goal, "PLAN_DUE", trigger))
    found.sort(key=lambda r: PLAN_ORDER.index(r.state))
    return found


def dropped_items(
    plan_issues: list[dict[str, Any]],
    goals: frozenset[str],
    marker: str,
    bot_login: str | None,
    maintainers: frozenset[str],
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Each goal's items its plans dropped (spec 096): from every plan issue of the goal, open or
    closed as completed, whose newest answer is a partial accept, each as {plan, id, text}, the
    text from that plan's body, by plan number and then in Work order. A plan closed as not
    planned adds none: its decline already holds"""
    found: dict[str, list[dict[str, Any]]] = {}
    for issue in sorted(plan_issues, key=lambda i: int(i["number"])):
        if not is_plan(issue, bot_login) or (issue["state"] == "CLOSED" and issue["stateReason"] != "COMPLETED"):
            continue
        plan, _ = PLANS.parse(issue.get("body") or "", goals)
        if plan is None:
            continue
        answer = plan_answer(issue, bot_login, marker, maintainers)
        if answer is None or answer.kind != "accept" or edited_after(issue, answer):
            continue
        reading = read_accept(PLANS.first_line(answer.body), tuple(i.id for i in plan.items))
        if isinstance(reading, str):
            continue
        for item in plan.items:
            if item.id in reading.dropped:
                found.setdefault(plan.goal, []).append({"plan": issue["number"], "id": item.id, "text": item.text})
    return {goal: tuple(items) for goal, items in found.items()}


def newest_plans(plan_issues: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Each goal's newest plan issue: the highest number whose first-line marker names it"""
    newest: dict[str, dict[str, Any]] = {}
    for issue in plan_issues:
        goal = plan_goal(issue)
        if goal is not None and (goal not in newest or issue["number"] > newest[goal]["number"]):
            newest[goal] = issue
    return newest


def plan_outcome(issue: dict[str, Any], bot_login: str | None) -> dict[str, Any] | None:
    """A closed plan's newest outcome comment (spec 097): its first line is the plan-outcome
    marker, by the --bot-login or an OWNER, MEMBER, or COLLABORATOR (D-29), never a trusted
    author's other than the --bot-login carrying the agent marker (D-62), and posted at or
    after the plan's last close; None without one"""
    if not issue.get("closedAt"):
        return None
    closed = timestamp(issue["closedAt"])
    found: dict[str, Any] | None = None
    for comment in issue["comments"]["nodes"]:
        body = comment.get("body") or ""
        if PLANS.first_line(body) != OUTCOME_MARKER or not PLANS.trusted(comment, bot_login):
            continue
        by_bot = bot_login is not None and PLANS.login(comment.get("author")).lower() == bot_login.lower()
        if not by_bot and AGENT_MARKER.search(body):
            continue
        at = timestamp(comment["createdAt"])
        if at >= closed and (found is None or at >= timestamp(found["createdAt"])):
            found = comment
    return found


GOAL_CHECK = re.compile(r"^Goal check:[ \t]*holds\b", re.IGNORECASE | re.MULTILINE)


REPLACED_MARKER = re.compile(r"^<!-- shipmill:plan-replaced #([1-9][0-9]*) -->$")


def replaced(issue: dict[str, Any], bot_login: str | None) -> bool:
    """spec 106: a plan the App closed for a newer one: its comment whose first line is
    `<!-- shipmill:plan-replaced #<new> -->`, by the --bot-login alone"""
    return bot_login is not None and any(
        PLANS.login(c.get("author")).lower() == bot_login.lower()
        and REPLACED_MARKER.match(PLANS.first_line(c.get("body") or "")) is not None
        for c in (issue.get("comments") or {}).get("nodes") or []
    )


def goal_check_holds(body: str) -> bool:
    """spec 106: a finished plan's trusted outcome says its goal's check holds; the goal reads
    planned, and no plan is proposed for it, until the maintainer merges the goal met"""
    return GOAL_CHECK.search(body) is not None


def still_missing(body: str) -> tuple[str, ...]:
    """The list items under an outcome's `Still missing:` line, in order; none for `- nothing`"""
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != STILL_MISSING:
            continue
        items: list[str] = []
        for rest in lines[index + 1 :]:
            text = rest.strip()
            if text.startswith("- "):
                items.append(text[2:].strip())
            elif text or items:
                break
        return () if [i.casefold() for i in items] == [NOTHING] else tuple(items)
    return ()


# -- goal plans (spec 028): where each plan issue stands


def is_plan(issue: dict[str, Any], bot_login: str | None) -> bool:
    """A goal-plan issue meant as a plan: its first line opens the plan marker, well-formed
    or not, or the --bot-login opened it. Any other goal-plan issue is a request"""
    if PLAN_LABEL not in labels(issue):
        return False
    if PLANS.first_line(issue.get("body") or "").startswith(PLAN_OPENER):
        return True
    return bot_login is not None and PLANS.login(issue.get("author")).lower() == bot_login.lower()


@dataclass(frozen=True)
class Answer:
    # accept (a first line starting with the word, clear or not: read_accept reads it), decline,
    # hold (a first line starting `hold until`, well-formed or not: read_hold reads it, spec 098), or edit
    kind: str
    at: dt.datetime
    body: str


def answerer(comment: dict[str, Any], bot_login: str | None, marker: str) -> bool:
    """D-16: an OWNER, MEMBER, or COLLABORATOR other than the --bot-login; a triage comment
    or a shipmill-marked comment is a session's own, never an answer"""
    if str(comment.get("authorAssociation") or "NONE") not in PLANS.TRUSTED:
        return False
    if bot_login is not None and PLANS.login(comment.get("author")).lower() == bot_login.lower():
        return False
    body = comment.get("body") or ""
    return own_text(body, marker)


def own_text(body: str, marker: str) -> bool:
    """Not a session's own text: no triage comment, and no first line opening a shipmill marker"""
    return verdict(body, marker) is None and not PLANS.first_line(body).startswith(SHIPMILL_MARKER)


def maintainer_logins(values: list[str]) -> frozenset[str]:
    """The maintainer's logins, lowercased, from --role NAME=FILLER[,FILLER...] flags checked
    as triage_state.py's parse_roles checks them (one per role, maintainer among them); a
    team is no login and names nobody here. Empty without flags; ValueError names what is wrong"""
    if not values:
        return frozenset()
    roles: dict[str, list[str]] = {}
    for value in values:
        name, sep, fillers = value.partition("=")
        if not sep or not ROLE_NAME.fullmatch(name):
            raise ValueError(
                f"--role wants NAME=FILLER[,FILLER...] with NAME matching {ROLE_NAME.pattern}, got {value!r}"
            )
        if name in roles:
            raise ValueError(f"--role {name} is given twice")
        if not fillers:
            raise ValueError(f"--role {name} has no fillers")
        roles[name] = []
        for filler in fillers.split(","):
            if USER.fullmatch(filler):
                roles[name].append(filler.lower())
            elif not TEAM.fullmatch(filler):
                raise ValueError(f"--role {name}: {filler!r} is neither a GitHub login nor @org/team")
    if MAINTAINER not in roles:
        raise ValueError(f"--role flags must include {MAINTAINER}=FILLER[,FILLER...]")
    return frozenset(roles[MAINTAINER])


def relayed_answer(
    comment: dict[str, Any], bot_login: str | None, marker: str, maintainers: frozenset[str]
) -> str | None:
    """D-68: the answer a maintainer gave in a session, from a comment by the --bot-login whose
    first line is the relay `Decision by @<login>` naming a maintainer: the text from its next
    non-blank line on, up to a line starting `Note:`, which ends what is read (D-93), the agent
    marker left out. None for any other comment, for a relay naming anyone else, and for one
    with no answer line or a session's own text there"""
    if bot_login is None or PLANS.login(comment.get("author")).lower() != bot_login.lower():
        return None
    head, _, rest = (comment.get("body") or "").strip().partition("\n")
    found = DECISION_BY.match(head.strip())
    if found is None or (found[1] or found[2]).lower() not in maintainers:
        return None
    read: list[str] = []
    for line in rest.splitlines():
        if line.strip().casefold().startswith(NOTE_START):
            break
        if not AGENT_MARKER.fullmatch(line.strip()):
            read.append(line)
    answer = "\n".join(read).strip()
    return answer if answer and own_text(answer, marker) else None


def plan_answer(
    issue: dict[str, Any], bot_login: str | None, marker: str, maintainers: frozenset[str] = frozenset()
) -> Answer | None:
    """The newest trusted answer newer than the plan's newest revision: the opening body, or
    the newest `plan-revised` comment by the --bot-login whose rev is higher than the
    revision before it. Anyone else's `plan-revised` comment revises nothing, and, starting
    with a shipmill marker, is no answer either. A relay by the --bot-login naming one of
    maintainers is the answer it carries (D-68). None while there is none"""
    since = timestamp(issue["createdAt"])
    rev = 0
    found: Answer | None = None
    for comment in sorted(issue["comments"]["nodes"], key=lambda c: timestamp(c["createdAt"])):
        body = comment.get("body") or ""
        at = timestamp(comment["createdAt"])
        revised = REVISED.match(PLANS.first_line(body))
        if revised is not None:
            by_bot = bot_login is not None and PLANS.login(comment.get("author")).lower() == bot_login.lower()
            if by_bot and int(revised.group(1)) > rev and at >= since:
                rev, since, found = int(revised.group(1)), at, None
            continue
        if at <= since:
            continue
        answer = relayed_answer(comment, bot_login, marker, maintainers)
        if answer is None:
            if not answerer(comment, bot_login, marker):
                continue
            answer = body
        if ANSWER_BY.match(PLANS.first_line(answer)):  # spec 106: it sets the answer date, no answer
            continue
        if found is None or at >= found.at:
            first = PLANS.first_line(answer)
            found = Answer(answer_kind(first), at, answer)
    return found


def answer_kind(first: str) -> str:
    """An answer's kind from its first line: accept, decline, hold (spec 098), or edit"""
    if ACCEPT_WORD.match(first):
        return "accept"
    if DECLINE.match(first):
        return "decline"
    return "hold" if HOLD.match(first) else "edit"


@dataclass(frozen=True)
class Hold:
    """A well-formed hold (spec 098): its condition as written, the comment's time, and the
    one condition it names: a date, an item (owner, name, number; owner and name empty for
    `#N`, this repository), or a release"""

    until: str
    at: dt.datetime
    date: dt.date | None = None
    item: tuple[str, str, int] | None = None


def read_hold(answer: Answer) -> Hold | None:
    """A hold answer's condition: `hold until <YYYY-MM-DD | #N | owner/repo#N | release>`, any
    case, an optional final period; None when its rest is not exactly one of them"""
    first = PLANS.first_line(answer.body)
    rest = HOLD.sub("", first, count=1).strip()
    if rest.endswith("."):
        rest = rest[:-1].rstrip()
    if rest.lower() == HOLD_RELEASE:
        return Hold(rest, answer.at)
    if HOLD_DATE.match(rest):
        try:
            day = dt.date.fromisoformat(rest)
        except ValueError:
            return None
        return Hold(rest, answer.at, date=day)
    ref = EXISTING_REF.match(rest)
    if ref is not None:
        return Hold(rest, answer.at, item=(ref.group(1) or "", ref.group(2) or "", int(ref.group(3))))
    return None


@dataclass(frozen=True)
class HoldMet:
    """How a hold's condition reads: met at a time (None while not), what met it as a note
    names it, or unreadable (an item GitHub answers null for)"""

    at: dt.datetime | None
    what: str = ""
    unreadable: bool = False


# Reads whether a hold's condition is met
HoldReader = Callable[[Hold], HoldMet]


def utc(moment: dt.datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def gh_holds(repo: str, run: Runner, now: dt.datetime, stable: re.Pattern[str] = STABLE) -> HoldReader:
    """The default hold reader (spec 098): a date from now; an item with one GraphQL read, an
    item or repository GitHub answers null for unreadable; a release from the newest tags, read
    once a run, as triage_state.py reads a stable tag's time"""
    owner, name = split_repo(repo)
    tags: list[tuple[dt.datetime, str]] = []
    read_tags = False

    def read(hold: Hold) -> HoldMet:
        nonlocal read_tags
        if hold.date is not None:
            midnight = dt.datetime(hold.date.year, hold.date.month, hold.date.day, tzinfo=UTC)
            return HoldMet(midnight if now >= midnight else None, hold.until)
        if hold.item is not None:
            item_owner, item_name, number = hold.item
            item_owner, item_name = (item_owner, item_name) if item_owner else (owner, name)
            response = run(HELD_ITEM, {"owner": item_owner, "name": item_name, "number": number})
            errors = response.get("errors") or []
            if errors and not unreadable(errors):
                fail(f"GitHub GraphQL errors: {json.dumps(errors)}")
            node = ((response.get("data") or {}).get("repository") or {}).get("issueOrPullRequest")
            if node is None:
                return HoldMet(None, hold.until, unreadable=True)
            if node.get("state") == "OPEN":
                return HoldMet(None, f"{hold.until} closed")
            closed = node.get("closedAt")
            if not closed:
                fail(f"{item_owner}/{item_name}#{number} is {node.get('state')!r} with no closedAt")
            return HoldMet(timestamp(str(closed)), f"{hold.until} closed")
        if not read_tags:
            data = repository(run, TAGS, {"owner": owner, "name": name})
            for tag in data["tags"]["nodes"]:
                target = tag.get("target") or {}
                date = (target.get("tagger") or {}).get("date") or target.get("committedDate")
                if date and stable.match(tag["name"]):
                    tags.append((timestamp(date), tag["name"]))
            read_tags = True
        after = sorted(t for t in tags if t[0] > hold.at)
        return HoldMet(after[0][0], after[0][1]) if after else HoldMet(None, "")

    return read


def rechecked(issue: dict[str, Any], bot_login: str | None, hold: Hold, met: dt.datetime) -> bool:
    """A comment by the --bot-login whose first line is the plan-recheck marker, newer than the
    hold's met_at and than the hold itself (spec 098); anyone else's counts for nothing"""
    if bot_login is None:
        return False
    for comment in issue["comments"]["nodes"]:
        by_bot = PLANS.login(comment.get("author")).lower() == bot_login.lower()
        first = PLANS.first_line(comment.get("body") or "")
        at = timestamp(comment["createdAt"])
        if by_bot and first == RECHECK_MARKER and at > met and at > hold.at:
            return True
    return False


def revision_at(issue: dict[str, Any], bot_login: str | None) -> dt.datetime:
    """When the plan's newest revision was written: its opening, or the newest `plan-revised`
    comment by the --bot-login whose rev is higher than the revision before it, as plan_answer
    reads it"""
    since, rev = timestamp(issue["createdAt"]), 0
    for comment in sorted(issue["comments"]["nodes"], key=lambda c: timestamp(c["createdAt"])):
        revised = REVISED.match(PLANS.first_line(comment.get("body") or ""))
        by_bot = bot_login is not None and PLANS.login(comment.get("author")).lower() == bot_login.lower()
        at = timestamp(comment["createdAt"])
        if revised is not None and by_bot and int(revised.group(1)) > rev and at >= since:
            rev, since = int(revised.group(1)), at
    return since


def recheck_at(issue: dict[str, Any], bot_login: str | None, met: dt.datetime) -> dt.datetime | None:
    """The time of the --bot-login's newest plan-recheck comment after the hold was met (spec
    098), from which a re-checked plan's answer date counts (spec 106); None without one"""
    times = [
        timestamp(c["createdAt"])
        for c in issue["comments"]["nodes"]
        if bot_login is not None
        and PLANS.login(c.get("author")).lower() == bot_login.lower()
        and PLANS.first_line(c.get("body") or "") == RECHECK_MARKER
        and timestamp(c["createdAt"]) > met
    ]
    return max(times) if times else None


def answer_date(
    issue: dict[str, Any], since: dt.datetime, bot_login: str | None, marker: str, maintainers: frozenset[str]
) -> dt.date:
    """S-106-7: a plan's answer date, ANSWER_DAYS days after since (its newest revision, or its
    re-check), unless a trusted reply newer than since whose first line is `answer by
    YYYY-MM-DD` sets another (an OWNER, MEMBER, or COLLABORATOR other than the --bot-login, or
    the --bot-login's relay naming a maintainer, D-68); the newest such reply counts, and an
    invalid date in it is no date set"""
    found: tuple[dt.datetime, dt.date] | None = None
    for comment in issue["comments"]["nodes"]:
        at = timestamp(comment["createdAt"])
        if at <= since:
            continue
        body = relayed_answer(comment, bot_login, marker, maintainers)
        if body is None and answerer(comment, bot_login, marker):
            body = comment.get("body") or ""
        written = ANSWER_BY.match(PLANS.first_line(body or ""))
        if written is None:
            continue
        try:
            day = dt.date.fromisoformat(written.group(1))
        except ValueError:
            continue
        if found is None or at >= found[0]:
            found = (at, day)
    return found[1] if found is not None else (since + dt.timedelta(days=ANSWER_DAYS)).date()


def dated(
    row: PlanRow,
    issue: dict[str, Any],
    now: dt.datetime,
    bot_login: str | None,
    marker: str,
    maintainers: frozenset[str],
) -> PlanRow:
    """S-106-7, S-106-8: a PLAN_OPEN row with its answer date, its note ending `answer by
    <date>`, and PLAN_OVERDUE in its place once that date has ended in UTC. A re-checked plan's
    seven days count from its re-check; a held plan (PLAN_HELD, PLAN_HOLD_MET) has none"""
    if row.state != "PLAN_OPEN":
        return row
    since = revision_at(issue, bot_login)
    if row.hold is not None and row.hold[1] is not None:  # spec 098: re-checked after its hold was met
        since = recheck_at(issue, bot_login, timestamp(row.hold[1])) or since
    day = answer_date(issue, since, bot_login, marker, maintainers)
    note = "; ".join(part for part in (row.note, f"answer by {day.isoformat()}") if part)
    state = "PLAN_OVERDUE" if now.astimezone(UTC).date() > day else "PLAN_OPEN"
    return replace(row, state=state, note=note, answer_by=day.isoformat())


def held_row(
    issue: dict[str, Any], answer: Answer, bot_login: str | None, holds: HoldReader
) -> tuple[str, str, tuple[str, str | None] | None]:
    """A plan whose answer is a hold (spec 098): (state, note, the --json hold)"""
    hold = read_hold(answer)
    if hold is None:
        return "PLAN_OPEN", f"hold not read: {PLANS.first_line(answer.body)}", None
    met = holds(hold)
    if met.unreadable:
        return "PLAN_OPEN", f"hold not read: {hold.until} can't be read", None
    if met.at is None:
        return "PLAN_HELD", f"until {hold.until}", (hold.until, None)
    if rechecked(issue, bot_login, hold, met.at):
        return "PLAN_OPEN", f"hold met: {met.what}", (hold.until, utc(met.at))
    return "PLAN_HOLD_MET", f"hold met: {met.what}; re-check due", (hold.until, utc(met.at))


def decline_text(answer: Answer) -> str:
    """A decline's reason: the rest of the comment after `decline`, its first line with text"""
    rest = DECLINE.sub("", answer.body.strip(), count=1).lstrip(" \t:.,;-—–")
    lines = [line.strip() for line in rest.splitlines() if line.strip()]
    return lines[0] if lines else ""


@dataclass(frozen=True)
class Accept:
    """What an accept keeps and drops, each in Work order (spec 096)"""

    kept: tuple[str, ...]
    dropped: tuple[str, ...]


def read_accept(first: str, ids: tuple[str, ...]) -> Accept | str:
    """An accept's first line read against the Work ids of the body it was given on: `accept`,
    `accept W-1, W-3`, or `accept except W-2` (any case, ids separated by commas, spaces, or
    both, an optional final period); for an unclear accept, the rule it breaks"""
    rest = ACCEPT_WORD.sub("", first.strip(), count=1).strip()
    if rest.endswith("."):
        rest = rest[:-1].rstrip()
    if not rest:
        return Accept(ids, ())
    tokens = [t for t in ID_SEPARATORS.split(rest) if t]
    excepting = bool(tokens) and tokens[0].lower() == EXCEPT_WORD
    named: list[str] = []
    for token in tokens[1:] if excepting else tokens:
        if token.lower() == EXCEPT_WORD:
            return "words past the ids" if excepting else "both a kept and a dropped list"
        if not ID_SHAPE.match(token):
            return "words past the ids"
        ident = "W-" + token[2:]
        if ident not in ids:
            return f"{ident} is not in the plan"
        if ident in named:
            return f"{ident} is named twice"
        named.append(ident)
    if not named:
        return "no item named"
    kept = tuple(i for i in ids if (i in named) != excepting)
    if not kept:
        return "drops every item"
    return Accept(kept, tuple(i for i in ids if i not in kept))


def edited_after(issue: dict[str, Any], answer: Answer) -> bool:
    """The body was edited after the answer: an accept read against it reads nothing (spec 028)"""
    edited = issue.get("lastEditedAt")
    return bool(edited) and timestamp(edited) > answer.at


def unclear_asked(issue: dict[str, Any], bot_login: str | None, answer: Answer) -> bool:
    """A comment by the --bot-login whose first line is the needs-decision marker, newer than
    the unclear accept: the session asked, and the plan waits again (spec 096)"""
    if bot_login is None:
        return False
    for comment in issue["comments"]["nodes"]:
        by_bot = PLANS.login(comment.get("author")).lower() == bot_login.lower()
        first = PLANS.first_line(comment.get("body") or "")
        if by_bot and first == DECISION_MARKER and timestamp(comment["createdAt"]) > answer.at:
            return True
    return False


def complete_plan_comments(run: Runner, owner: str, name: str, issue: dict[str, Any]) -> None:
    """Page a plan issue's comments back to its first: an answer is read against every revision"""
    comments = issue["comments"]
    seen: set[str] = set()
    while comments["pageInfo"]["hasPreviousPage"]:
        cursor = comments["pageInfo"]["startCursor"]
        if not cursor or cursor in seen:
            fail(f"GitHub reported more comments on #{issue['number']}, but the page cursor did not advance")
        seen.add(cursor)
        variables: Variables = {"owner": owner, "name": name, "number": issue["number"], "cursor": cursor}
        page = (repository(run, OLDER_PLAN_COMMENTS, variables).get("issue") or {}).get("comments")
        if page is None:
            fail(f"issue #{issue['number']} vanished while paging its comments")
        comments["nodes"] = page["nodes"] + comments["nodes"]
        comments["pageInfo"] = page["pageInfo"]


# Where an accepted plan's filing stands: (PLAN_ACCEPTED, PLAN_FILED, or PLAN_DONE, the note)
FilingReader = Callable[[dict[str, Any], Any], tuple[str, str]]


def plan_state(
    issue: dict[str, Any],
    *,
    goals: frozenset[str],
    marker: str,
    bot_login: str | None,
    filing: FilingReader,
    maintainers: frozenset[str] = frozenset(),
    newest: bool = False,
    holds: HoldReader | None = None,
) -> PlanRow | None:
    """A plan issue's row; None for a plan closed but not as not planned, save its goal's
    newest plan closed as completed with no trusted outcome after its last close, which reads
    PLAN_DONE (spec 097). A hold answer reads by holds (spec 098)"""
    goal = plan_goal(issue)
    title = issue.get("title") or ""
    number = issue["number"]
    if issue["state"] == "CLOSED":
        if issue["stateReason"] == "COMPLETED" and newest and plan_outcome(issue, bot_login) is None:
            return PlanRow(goal, "PLAN_DONE", title, "closed without an outcome", number, "plan")
        if issue["stateReason"] != "NOT_PLANNED" or replaced(issue, bot_login):
            return None  # a replaced plan is no decline (spec 106)
        answer = plan_answer(issue, bot_login, marker, maintainers)
        reason = decline_text(answer) if answer is not None and answer.kind == "decline" else ""
        reason = reason or decline_reason(issue, marker, bot_login) or "closed as not planned with no reason"
        return PlanRow(goal, "PLAN_DECLINED", title, reason, number, "plan")
    plan, problems = PLANS.parse(issue.get("body") or "", goals)
    if plan is None:
        line, rule = problems[0]
        more = f" (and {len(problems) - 1} more)" if len(problems) > 1 else ""
        return PlanRow(goal, "PLAN_MALFORMED", title, f"line {line}: {rule}{more}", number, "plan")
    answer = plan_answer(issue, bot_login, marker, maintainers)
    if answer is None:
        return PlanRow(goal, "PLAN_OPEN", title, "", number, "plan")
    if answer.kind == "hold":
        if holds is None:
            fail(f"plan #{number} is held, and no hold reader was given")
        state, note, hold = held_row(issue, answer, bot_login, holds)
        return PlanRow(goal, state, title, note, number, "plan", hold=hold)
    if answer.kind != "accept":
        return PlanRow(goal, "PLAN_ANSWERED", title, answer.kind, number, "plan")
    if edited_after(issue, answer):
        return PlanRow(goal, "PLAN_OPEN", title, "edited after accept", number, "plan")
    reading = read_accept(PLANS.first_line(answer.body), tuple(i.id for i in plan.items))
    if isinstance(reading, str):
        if unclear_asked(issue, bot_login, answer):
            return PlanRow(goal, "PLAN_OPEN", title, "unclear accept asked", number, "plan")
        return PlanRow(goal, "PLAN_ANSWERED", title, f"unclear accept: {reading}", number, "plan")
    if not reading.dropped:
        state, note = filing(issue, plan)
    else:  # the filing reader looks at the kept items alone
        kept = tuple(i for i in plan.items if i.id in reading.kept)
        state, note = filing(issue, replace(plan, items=kept))
        note = "; ".join(part for part in (note, f"dropped: {', '.join(reading.dropped)}") if part)
    return PlanRow(goal, state, title, note, number, "plan", kept=reading.kept, dropped=reading.dropped)


def plan_issue_rows(
    plan_issues: list[dict[str, Any]],
    *,
    goals: frozenset[str],
    marker: str,
    bot_login: str | None,
    filing: FilingReader,
    maintainers: frozenset[str] = frozenset(),
    holds: HoldReader | None = None,
    now: dt.datetime | None = None,
) -> list[PlanRow]:
    found: list[PlanRow] = []
    now = now or dt.datetime.now(UTC)
    newest = {issue["number"] for issue in newest_plans(plan_issues).values()}
    # S-106-10: of a goal's open plans, all but the newest read PLAN_REPLACED by it
    open_of: dict[str, list[dict[str, Any]]] = {}
    for issue in plan_issues:
        goal = plan_goal(issue)
        if goal is not None and issue["state"] == "OPEN" and is_plan(issue, bot_login):
            open_of.setdefault(goal, []).append(issue)
    newer: dict[int, int] = {}
    for issues in open_of.values():
        ordered = sorted(issues, key=lambda i: (timestamp(i["createdAt"]), int(i["number"])))
        newer |= {int(i["number"]): int(ordered[-1]["number"]) for i in ordered[:-1]}
    for issue in plan_issues:
        if is_plan(issue, bot_login):
            row = plan_state(
                issue,
                goals=goals,
                marker=marker,
                bot_login=bot_login,
                filing=filing,
                maintainers=maintainers,
                newest=issue["number"] in newest,
                holds=holds,
            )
            if row is None:
                continue
            if int(issue["number"]) in newer:  # S-106-10: the newer plan of its goal replaces it
                row = replace(row, state="PLAN_REPLACED", note=f"by #{newer[int(issue['number'])]}")
            else:
                row = dated(row, issue, now, bot_login, marker, maintainers)
            opener = PLANS.login(issue.get("author"))
            found.append(replace(row, author=opener, association=str(issue.get("authorAssociation") or "NONE")))
    return found


def existing_milestones(run: Runner, owner: str, name: str, numbers: list[int]) -> dict[int, str | None]:
    """The milestone title of each issue of this repo, 50 to a query"""
    found: dict[int, str | None] = {}
    for start in range(0, len(numbers), 50):
        chunk = numbers[start : start + 50]
        parts = " ".join(f"e{n}: issue(number: {n}) {{ milestone {{ title }} }}" for n in chunk)
        query = f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {parts} }} }}"
        data = repository(run, query, {"owner": owner, "name": name})
        for n in chunk:
            node = data.get(f"e{n}")
            if node is None:
                fail(f"no issue #{n} in {owner}/{name}, which a plan names as an existing item")
            title = (node.get("milestone") or {}).get("title")
            found[n] = None if title is None else str(title)
    return found


def existing_parents(run: Runner, owner: str, name: str, numbers: list[int]) -> dict[int, tuple[str, int] | None]:
    """The parent of each issue of this repo, as (owner/name in lower case, number), or None
    with none, 50 to a query (D-114)"""
    found: dict[int, tuple[str, int] | None] = {}
    for start in range(0, len(numbers), 50):
        chunk = numbers[start : start + 50]
        parts = " ".join(
            f"p{n}: issue(number: {n}) {{ parent {{ number repository {{ nameWithOwner }} }} }}" for n in chunk
        )
        query = f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {parts} }} }}"
        data = repository(run, query, {"owner": owner, "name": name})
        for n in chunk:
            node = data.get(f"p{n}")
            if node is None:
                fail(f"no issue #{n} in {owner}/{name}, which a plan names as an existing item")
            parent = node.get("parent")
            if parent is None:
                found[n] = None
                continue
            repo = str((parent.get("repository") or {}).get("nameWithOwner") or "")
            if not repo or not isinstance(parent.get("number"), int):
                fail(f"#{n} in {owner}/{name} has a parent with no repository or number")
            found[n] = (repo.lower(), int(parent["number"]))
    return found


def closed_states(run: Runner, owner: str, name: str, numbers: list[int]) -> dict[int, str | None]:
    """How each issue of this repo closed, 50 to a query (spec 097): `completed`, `not
    planned`, `duplicate`, or `closed` with no reason given; None while it is open"""
    found: dict[int, str | None] = {}
    for start in range(0, len(numbers), 50):
        chunk = numbers[start : start + 50]
        parts = " ".join(f"s{n}: issue(number: {n}) {{ state stateReason }}" for n in chunk)
        query = f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {parts} }} }}"
        data = repository(run, query, {"owner": owner, "name": name})
        for n in chunk:
            node = data.get(f"s{n}")
            if node is None:
                fail(f"no issue #{n} in {owner}/{name}, which a plan's item names")
            reason = str(node.get("stateReason") or "")
            found[n] = None if node.get("state") != "CLOSED" else CLOSED_AS.get(reason, "closed")
    return found


OPPORTUNITY_ITEM = re.compile(r"^#([1-9][0-9]*)\b")  # spec 106: a feature item naming an accepted opportunity


def gh_filing(
    repo: str, bot_login: str | None, run: Runner, opportunities: dict[int, set[str]] | None = None
) -> FilingReader:
    """The default filing reader: plans.py's items query, and the existing items' milestones and
    parents (D-114); once the plan reads filed, how its items' issues closed (spec 097). A
    feature item whose text starts `#N`, N an opportunity of this repo (opportunities, by its
    labels), files no issue (S-106-23): the opportunity is its carrier, linked as the plan's
    sub-issue and labelled `project`, the note naming one not yet labelled"""
    owner, name = split_repo(repo)
    opportunities = opportunities or {}

    def opportunity(item: Any) -> int | None:
        named = OPPORTUNITY_ITEM.match(item.text) if item.kind == "feature" else None
        return int(named.group(1)) if named is not None and int(named.group(1)) in opportunities else None

    def read(issue: dict[str, Any], plan: Any) -> tuple[str, str]:
        try:
            _, filed = PLANS.plan_carriers(f"{owner}/{name}#{issue['number']}", bot_login, run)
        except PLANS.PlanError as exc:
            fail(str(exc))
        kept = {item.id for item in plan.items}  # a partial accept's plan holds its kept items alone (spec 096)
        filed = [(item, carrier) for item, carrier in filed if item.id in kept]
        unfiled = [
            item.id
            for item, carrier in filed
            if item.kind in FILED_KINDS and carrier is None and opportunity(item) is None
        ]
        carried = [carrier for item, carrier in filed if item.kind in FILED_KINDS and carrier is not None]
        # each item's issue of this repo, in Work order: a filed item's carrier, an existing item here
        work: list[tuple[str, int]] = []
        here: list[int] = []
        unlabelled: list[int] = []
        for item, carrier in filed:
            named = opportunity(item) if carrier is None else None
            if named is not None:  # S-106-23: the opportunity is the item's head
                here.append(named)
                work.append((item.id, named))
                if PROJECT_LABEL not in opportunities[named]:
                    unlabelled.append(named)
                continue
            if item.kind in FILED_KINDS and carrier is not None:
                work.append((item.id, carrier.number))
            ref = EXISTING_REF.match(item.text) if item.kind == "existing" else None
            if ref is None:
                continue
            named = (ref.group(1) or owner, ref.group(2) or name)
            if (named[0].lower(), named[1].lower()) == (owner.lower(), name.lower()):  # another repo's: unread
                here.append(int(ref.group(3)))
                work.append((item.id, int(ref.group(3))))
        outside: list[int] = []
        if plan.milestone is not None:
            outside += [c.number for c in carried if c.milestone != plan.milestone]
            titles = existing_milestones(run, owner, name, sorted(set(here)))
            outside += [n for n in sorted(set(here)) if titles[n] != plan.milestone]
        # D-114: each existing item of this repo becomes the plan's sub-issue, open or closed; one
        # with another parent is named and holds nothing, as GitHub gives an issue one parent
        parents = existing_parents(run, owner, name, sorted(set(here))) if here else {}
        ours = (f"{owner}/{name}".lower(), int(issue["number"]))
        unlinked = [n for n, parent in parents.items() if parent is None]
        elsewhere = [n for n, parent in parents.items() if parent is not None and parent != ours]
        notes = []
        if unfiled:
            notes.append(f"not filed: {', '.join(unfiled)}")
        if outside:
            notes.append(f"not in milestone {plan.milestone}: {', '.join(f'#{n}' for n in sorted(set(outside)))}")
        if unlinked:
            notes.append(f"not linked: {', '.join(f'#{n}' for n in unlinked)}")
        if unlabelled:
            notes.append(f"not labelled project: {', '.join(f'#{n}' for n in unlabelled)}")
        other = f"another parent: {', '.join(f'#{n}' for n in elsewhere)}" if elsewhere else ""
        if notes:
            return "PLAN_ACCEPTED", "; ".join([*notes, other] if other else notes)
        closed = closed_states(run, owner, name, sorted({n for _, n in work}))
        if all(closed[n] is not None for _, n in work):
            listed = ", ".join(f"{ident} #{n} {closed[n]}" for ident, n in work)
            return "PLAN_DONE", f"work closed: {listed}" if listed else "work closed: no item of this repository"
        filed_note = f"filed: {', '.join(f'#{c.number}' for c in carried)}" if carried else "nothing to file"
        return "PLAN_FILED", "; ".join([filed_note, other] if other else [filed_note])

    return read


def spec_texts(tree: dict[str, Any] | None) -> list[str]:
    """The text of each spec in docs/specs/ at the default branch's head"""
    entries = (tree or {}).get("entries") or []
    texts = []
    for entry in entries:
        name = str(entry.get("name") or "")
        if name.endswith(".md") and name not in NOT_SPECS:
            texts.append(str((entry.get("object") or {}).get("text") or ""))
    return texts


def fetch_plans(
    repo: str,
    intake: Intake,
    *,
    goals: GoalsReader,
    marker: str,
    bot_login: str | None,
    wip: int | None,
    room: RoomReader,
    run: Runner = gh_graphql,
    filing: FilingReader | None = None,
    maintainers: frozenset[str] = frozenset(),
    holds: HoldReader | None = None,
    now: dt.datetime | None = None,
    stable: re.Pattern[str] = STABLE,
    checked: set[str] | None = None,
    into: dict[str, tuple[int, dt.datetime]] | None = None,
    opportunities: dict[int, set[str]] | None = None,
) -> list[PlanRow]:
    """The plan rows: two queries more than fetch, the open pull requests with the specs at the
    default branch's head, and the plan issues; then a plan's older comments when it has more
    than PAGE, for each accepted plan its items' issues, and for each held plan its item, or
    the tags once (spec 098); triage_state.py only when a goal waits on --wip"""
    owner, name = split_repo(repo)
    if holds is None:
        holds = gh_holds(repo, run, now or dt.datetime.now(UTC), stable)
    base: Variables = {"owner": owner, "name": name}
    direction = goals()
    if not direction:
        return []
    pulls, first = paged(run, PULLS, base, "pullRequests")
    plan_issues, _ = paged(run, PLAN_ISSUES, {**base, "label": PLAN_LABEL}, "issues")
    for issue in plan_issues:
        # a plan closed as completed too: the items its newest answer dropped stay dropped (spec
        # 096), and a goal's newest one's outcome comment is read (spec 097)
        if is_plan(issue, bot_login) and (issue["state"] == "OPEN" or issue["stateReason"] in READ_CLOSED):
            complete_plan_comments(run, owner, name, issue)
    by_issue = plan_issue_rows(
        plan_issues,
        goals=frozenset(g.id for g in direction),
        marker=marker,
        bot_login=bot_login,
        filing=filing or gh_filing(repo, bot_login, run, opportunities or {}),
        maintainers=maintainers,
        holds=holds,
        now=now,
    )
    by_goal = plan_rows(
        direction,
        maintainers=maintainers,
        open_issues=intake.open_issues,
        opportunities=intake.opportunity_issues,
        plan_issues=plan_issues,
        pulls=pulls,
        specs=spec_texts(first.get("specs")),
        marker=marker,
        bot_login=bot_login,
        wip=wip,
        room=room,
        checked=checked,
        into=into,
    )
    found = by_goal + by_issue
    found.sort(key=lambda r: PLAN_ORDER.index(r.state))
    return found


def show_plan(row: PlanRow) -> str:
    if row.kind == "plan":
        note = "; ".join(part for part in (row.goal, row.note) if part)
        return f"#{row.number:<5} {row.state:<16} {row.title[:70]}  [{note}]"
    return f"{row.goal:<6} {row.state:<16} {row.title[:70]}  [{row.note}]"


# -- the config: [autonomy] intake, read with tomllib on 3.11+, with regexes on 3.10, where any
# form but a plain key = value line in a plain [table] is refused rather than misread


def config_file(given: Path | None) -> Path | None:
    if given is not None:
        if not given.is_file():
            fail(f"no config at {given}")
        return given
    return CONFIG if CONFIG.is_file() else None


def config_values(path: Path, table: str, keys: tuple[str, ...]) -> dict[str, object]:
    """The keys a config table sets, of those asked for"""
    return text_values(path.read_text(encoding="utf-8"), path, table, keys)


def text_values(text: str, path: Path | str, table: str, keys: tuple[str, ...]) -> dict[str, object]:
    """The keys a config's text sets in a table, of those asked for; path names it in an error"""
    if tomllib is not None:
        try:
            raw = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            fail(f"{path}: {exc}")
        section = raw.get(table, {})
        if not isinstance(section, dict):
            fail(f"{path}: {table} must be a table")
        return {k: section[k] for k in keys if k in section}
    return config_values_310(text, path, table, keys)


def config_values_310(text: str, path: Path | str, table: str, keys: tuple[str, ...]) -> dict[str, object]:
    unreadable = f"{path}: can't read [{table}] on Python 3.10: use 3.11+, or plain key = value lines in [{table}]"
    body: list[str] | None = None
    current = ""
    for line in text.splitlines():
        header = re.match(r"^\s*\[\[?\s*([^\[\]]+?)\s*\]\]?\s*(?:#.*)?$", line)
        if header:
            current = ".".join(p.strip().strip("\"'") for p in header.group(1).split("."))
            if current == table:
                body = []
            continue
        if current == "" and re.match(rf"^\s*[\"']?{re.escape(table)}[\"']?\s*[.=]", line):
            fail(unreadable)
        if current == table and body is not None:
            body.append(line)
    found: dict[str, object] = {}
    for line in body or []:
        for key in keys:
            if not re.match(rf"^\s*[\"']?{re.escape(key)}[\"']?\s*=", line):
                continue
            value = re.match(
                r"^[^=]*=\s*(?:\"([^\"\\]*)\"|'([^']*)'|(-?\d+)|(true|false)"
                r"|\[\s*((?:\"[^\"\\]*\"\s*,\s*)*(?:\"[^\"\\]*\"\s*,?\s*)?)\])\s*(?:#.*)?$",
                line,
            )
            if value is None or (value.group(5) is not None and key not in ARRAY_KEYS):
                fail(unreadable)
            text_value = value.group(1) if value.group(1) is not None else value.group(2)
            if value.group(5) is not None:  # a one-line array of plain strings, such as [product] repos
                found[key] = re.findall(r"\"([^\"\\]*)\"", value.group(5))
            elif text_value is not None:
                found[key] = text_value
            elif value.group(3) is not None:
                found[key] = int(value.group(3))
            else:
                found[key] = value.group(4) == "true"
    return found


def intake_autonomy(path: Path | None) -> str:
    if path is None:
        return "propose"
    level = config_values(path, "autonomy", ("intake",)).get("intake", "propose")
    if level == "act":
        fail(f"{path}: [autonomy] intake is observe or propose: only the maintainer accepts an opportunity")
    if not isinstance(level, str) or level not in INTAKE_LEVELS:
        fail(f"{path}: [autonomy] intake must be one of {list(INTAKE_LEVELS)}, got {level!r}")
    return level


# -- spec 101: [agents] outcomes, how many outcomes the product has in flight at once, and its
# open opportunities across the product's repos


@dataclass(frozen=True)
class Product:
    """Where the product's limit is set and the repos whose open opportunities count"""

    home: str  # owner/name: the repo whose config sets the limit, the checkout's own outside a component
    repos: tuple[str, ...]  # every repo of the product, the checkout's own first, none twice
    limit: int | None  # [agents] outcomes (or projects); None without the key, and then nothing is counted


@dataclass(frozen=True)
class Outcomes:
    """The --json first line's outcomes and the text output's second line"""

    home: str
    limit: int
    in_flight: int

    @property
    def room(self) -> int:
        return max(self.limit - self.in_flight, 0)

    def json(self) -> dict[str, int]:
        return {"limit": self.limit, "in_flight": self.in_flight, "room": self.room}

    def line(self) -> str:
        return f"outcomes in flight: {self.in_flight} of {self.limit} (product {self.home})"


def outcomes_limit(value: object, where: Path | str, key: str = "outcomes") -> int:
    """[agents] outcomes (or projects, spec 106), checked as src/shipmill/agents.py reads it: an
    integer from 1 to wip's ceiling"""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= OUTCOMES_CEILING:
        fail(f"{where}: [agents] {key} must be an integer from 1 to {OUTCOMES_CEILING}, got {value!r}")
    return value


def product_repos(value: object, where: Path | str) -> list[str]:
    """[product] repos, each owner/name"""
    if not isinstance(value, list) or not all(isinstance(r, str) and PLAIN_REPO.fullmatch(r) for r in value):
        fail(f"{where}: [product] repos must be a list of owner/name, got {value!r}")
    return list(value)


def unique(repos: list[str]) -> tuple[str, ...]:
    """The repos in order, a repo named twice (in any case) kept once"""
    seen: set[str] = set()
    kept = []
    for repo in repos:
        if repo.lower() not in seen:
            seen.add(repo.lower())
            kept.append(repo)
    return tuple(kept)


# Reads a config from a repo's default branch: its text, or None when it has none; raises
# Unreadable when the read fails
HomeReader = Callable[[str], str | None]


class Unreadable(Exception):
    """A `shipmill gh --product` read that failed, its message naming the step and the repo"""


def unlimited(home: str, repo: str, reason: str, key: str = "outcomes") -> Product:
    """A component whose home's config can't be read: no limit, as without the key (S-101-3),
    and one note on stderr naming the failed read so it isn't silent"""
    sys.stderr.write(f"note: no [agents] {key} limit, the home's config is unreadable: {reason}\n")
    return Product(home, (repo,), None)


def product_of(repo: str, path: Path | None, read_home: HomeReader, key: str = "outcomes") -> Product:
    """The product the checkout's config places repo in (spec 101). A lone repo, or one whose
    [product] says standalone, is its own product; in the product's home ([product] repos), the
    home and the repos it lists; in a component ([product] home), the limit and the repos are
    read from the home's config on its default branch, through read_home, and a component that
    sets [agents] outcomes itself is refused, naming the home. A home whose config can't be read
    (read_home raises Unreadable, or the home has none) sets no limit: the run goes on as before
    with one note on stderr (S-101-3). [product] repos is read only with a limit, so a run without
    one reads the config as before. key is the limit's: outcomes, or projects with --projects
    (S-106-28), read the same way"""
    if path is None:
        return Product(repo, (repo,), None)
    product = config_values(path, "product", ("home", "standalone"))
    local = config_values(path, "agents", (key,))
    home = None if product.get("standalone") is True else product.get("home")
    if home is not None:
        if not isinstance(home, str) or not PLAIN_REPO.fullmatch(home):
            fail(f"{path}: [product] home must be owner/name, got {home!r}")
        if key in local:
            fail(f"{path}: [agents] {key} is the product's, set in its home {home}'s {CONFIG}, not in a component")
        where = f"{home}:{CONFIG}"
        try:
            text = read_home(home)
        except Unreadable as failed:
            return unlimited(home, repo, str(failed), key)
        if text is None:
            reason = f"reading the product's limit: GitHub has no {where} on its default branch"
            return unlimited(home, repo, reason, key)
        found = text_values(text, where, "agents", (key,))
        if key not in found:
            return Product(home, (repo,), None)
        limit = outcomes_limit(found[key], where, key)
        listed = product_repos(text_values(text, where, "product", ("repos",)).get("repos", []), where)
        return Product(home, unique([repo, home, *listed]), limit)
    if key not in local:
        return Product(repo, (repo,), None)
    limit = outcomes_limit(local[key], path, key)
    listed = [] if product.get("standalone") is True else config_values(path, "product", ("repos",)).get("repos", [])
    return Product(repo, unique([repo, *product_repos(listed, path)]), limit)


class ProductGh:
    """`shipmill gh --product <repo> api graphql` from the checkout, as triage_state.py --home
    runs it (spec 065): `uvx shipmill==<the plugin's version> --repo <the checkout> gh`, run
    once more with uv's index refreshed when uv found no such version (#597), the coordinator's
    token in the home (D-83) and the read token in a component (D-84). A read that fails raises
    Unreadable naming the step and the repo, never reading it as empty: a count exits 2 on it,
    and a component reading its home's limit goes on with none (S-101-3)"""

    def __init__(self, here: Path, execute: Callable[[list[str]], subprocess.CompletedProcess[str]] = run_uvx):
        self.here = here
        self.execute = execute

    def graphql(self, via: str, query: str, variables: dict[str, str], step: str) -> dict[str, Any]:
        top = next((d for d in (self.here, *self.here.parents) if (d / ".git").exists()), self.here)
        cmd = [*shipmill_command(None), "--repo", str(top), "gh", "--product", via, "api", "graphql"]
        cmd += ["-f", f"query={query}"]
        for key, value in variables.items():
            cmd += ["-f", f"{key}={value}"]
        try:
            proc: subprocess.CompletedProcess[str] = watch_module().pinned(cmd, self.execute)
        except FileNotFoundError:
            raise Unreadable(f"{step}: uvx is not on PATH, and {via} is read with `shipmill gh --product`") from None
        said = (proc.stderr or "").strip().splitlines()
        if proc.returncode != 0:
            exited = f"{step}: shipmill gh --product {via} exited {proc.returncode}"
            raise Unreadable(exited + (f": {said[0]}" if said else ""))
        try:
            response = json.loads(proc.stdout)
        except ValueError:
            raise Unreadable(f"{step}: shipmill gh --product {via} printed no JSON: {proc.stdout[:200]!r}") from None
        if not isinstance(response, dict) or response.get("errors"):
            raise Unreadable(f"{step}: shipmill gh --product {via} answered {json.dumps(response)[:300]}")
        data: dict[str, Any] = response.get("data") or {}
        return data

    def home_config(self, home: str) -> str | None:
        """The home's config on its default branch, None when it has none; raises Unreadable
        when the read fails or GitHub returns no such repository to the token"""
        owner, name = split_repo(home)
        step = f"reading the product's limit from {home}:{CONFIG}"
        node = self.graphql(home, HOME_CONFIG, {"owner": owner, "name": name}, step).get("repository")
        if node is None:
            raise Unreadable(f"{step}: GitHub returned no repository {home}")
        blob = node.get("object")
        return None if blob is None else str(blob.get("text") or "")


def count_query(repos: list[str]) -> str:
    """One query that counts each repo's open issues labelled $label"""
    parts = []
    for i, repo in enumerate(repos):
        owner, name = split_repo(repo)
        where = f"owner: {json.dumps(owner)}, name: {json.dumps(name)}"
        parts.append(f"r{i}: repository({where}) {{ issues(labels: [$label], states: OPEN) {{ totalCount }} }}")
    return "query($label: String!) { " + " ".join(parts) + " }"


def outcomes_in_flight(product: Product, local_open: int, label: str, gh: ProductGh) -> Outcomes | None:
    """The product's open opportunities (spec 101): the checkout's own, local_open, as fetch read
    them, and every other repo's, counted with one `shipmill gh --product` per owner, its repo the
    home when the owner's repos include it, else the owner's first. Open is all that counts:
    OPPORTUNITY_OPEN, ACCEPTED, and HANDED_OFF, an expedite or fixed-date one like any other.
    None without a limit, and then nothing is read"""
    if product.limit is None:
        return None
    owners: dict[str, list[str]] = {}
    for repo in product.repos[1:]:
        owners.setdefault(repo.partition("/")[0].lower(), []).append(repo)
    total = local_open
    for group in owners.values():
        via = next((r for r in group if r.lower() == product.home.lower()), group[0])
        step = f"counting the open opportunities of {', '.join(group)}"
        try:
            data = gh.graphql(via, count_query(group), {"label": label}, step)
        except Unreadable as failed:
            fail(str(failed))
        for i, repo in enumerate(group):
            count = ((data.get(f"r{i}") or {}).get("issues") or {}).get("totalCount")
            if not isinstance(count, int) or isinstance(count, bool):
                fail(f"{step}: GitHub returned no open issue count for {repo}")
            total += count
    return Outcomes(product.home, product.limit, total)


def first_line(
    autonomy: str, outcomes: Outcomes | None, projects: Projects | None = None, overdue: tuple[str, ...] = ()
) -> dict[str, Any]:
    """--json's first line: the autonomy, and with a limit the outcomes (spec 101) and the
    projects (spec 106); with --projects, the product's overdue plans as owner/repo#P while any
    is (S-106-25: what a held head waits for)"""
    line: dict[str, Any] = {"autonomy": autonomy}
    if outcomes is not None:
        line["outcomes"] = outcomes.json()
    if projects is not None:
        line["projects"] = projects.json()
    if overdue:
        line["overdue"] = list(overdue)
    return line


# -- spec 106: projects, a head issue labelled `project` with its `Check: ` issue and parts, and
# [agents] projects, how many of the product's run at once

PROJECT_LABEL = "project"
PROJECT_HELD_LABEL = "held"
PROJECT_FOCUS_LABEL = "focus"
STOP_RECORD = "<!-- shipmill:project-stopped -->"  # the --bot-login's record on a stopped head
PROJECT_DAYS = 30  # a head closed within this many days still prints its row
CHECK_TITLE = "Check: "
CHECK_SECTION = re.compile(r"^##[ \t]+Check[ \t]*$", re.MULTILINE)
CLEANUP_SECTION = re.compile(r"^##[ \t]+Cleanup[ \t]*$", re.MULTILINE)
UNCHECKED = re.compile(r"^[ \t]*[-*][ \t]+\[ \][ \t]+(.+?)[ \t]*$", re.MULTILINE)
# The page sizes keep each read to a few of the host's rate-limit points (#1459): GitHub charges
# a query by its worst case, one request per node of each nested connection, so a page of heads
# with their sub-issues and those sub-issues' own is small; tests/test_intake_projects.py pins them
PROJECT_PAGE = 10  # heads per page of the checkout's own read
PRODUCT_HEADS = 25  # open heads per repo in a product count, refused past it
# sub-issues of a head, and of each of its sub-issues (the check issue's parts); a head with
# more is refused, never read short
PROJECT_SUBS = 20
PROJECT_PARTS = 10
# the states a head reads, and who holds each (spec 106's table): its start, agents and the
# maintainer's steps, the maintainer's steps first, the person who runs the check, none
PROJECT_HOLDERS = {
    "PROJECT_HELD": "start",
    "PROJECT_ACTIVE": "agents",
    "PROJECT_FOCUS": "maintainer",
    "PROJECT_CLOSING": "checker",
    "PROJECT_CLOSED": None,
    "PROJECT_STOPPED": None,
    "PROJECT_IDLE": "agent",  # S-106-17: a session asks the maintainer continue, hold, or stop
    "PROJECT_START_DUE": "agent",  # S-106-14: a session files its check issue, or removes `held`
    "PROJECT_STOP_DUE": "agent",  # S-106-18: a session stops it
}
PROJECT_COUNTED = ("PROJECT_ACTIVE", "PROJECT_FOCUS")  # S-106-28: held and closing heads count nothing
# each starts a session (exit 1); PROJECT_START_DUE (spec 106): a held head whose turn has come
PROJECT_ACTION = frozenset({"PROJECT_IDLE", "PROJECT_STOP_DUE", "PROJECT_START_DUE"})
WORK_ITEM = re.compile(r"^<!-- shipmill:plan-item #([1-9][0-9]*) W-([1-9][0-9]*) -->$")
IDLE_DAYS = 14  # S-106-17: a tree with no update this long reads PROJECT_IDLE
# S-106-18: a stop, `stop: <reason>` as a reply's first line, or `stop` answering the idle
# question with the reason on its next line
STOP_LINE = re.compile(r"^stop:[ \t]*(\S.*?)[ \t]*$", re.IGNORECASE)
STOP_ANSWER = re.compile(r"^stop\.?$", re.IGNORECASE)
# the pull requests that close the head or one of its sub-issues, read for an open head of the
# checkout's own only (the idle read); a part's pull request moves the part's own updatedAt
LINKED = "closedByPullRequestsReferences(first: 5, includeClosedPrs: true) { nodes { updatedAt } }"


def head_fields(linked: str, summary: bool = False) -> str:
    """A head's fields, as GraphQL text; linked adds the head's and its sub-issues' pull requests;
    summary reads each sub-issue's own sub-issues as counts (subIssuesSummary), no connection"""
    parts = (
        "subIssuesSummary { total completed }"
        if summary
        else f"subIssues(first: {PROJECT_PARTS}) {{ totalCount nodes {{ number state updatedAt }} }}"
    )
    return f"""
number title body state stateReason createdAt closedAt author {{ __typename login }} authorAssociation {linked}
parent {{ number }}
labels(first: 100) {{ pageInfo {{ hasNextPage }} nodes {{ name }} }}
timelineItems(itemTypes: [LABELED_EVENT], first: 20) {{
  nodes {{ ... on LabeledEvent {{ createdAt label {{ name }} actor {{ __typename login }} }} }}
}}
comments(last: 30) {{ nodes {{ author {{ __typename login }} authorAssociation body createdAt }} }}
subIssues(first: {PROJECT_SUBS}) {{
  totalCount
  nodes {{
    number title body state updatedAt {linked}
    {parts}
  }}
}}
"""


# a closed head's and a product count's: the states alone, a check issue's parts as counts, so
# an owner's repos cost a point or two (a part closed as not planned that GitHub doesn't count
# completed leaves the head active: counted, never a slot given away)
COUNT_FIELDS = head_fields("", summary=True)
LOCAL_FIELDS = head_fields(LINKED)  # an open head's of the checkout's own


def projects_query(states: str, fields: str) -> str:
    """One page of the checkout's heads in states, oldest first; the closed ones since $since"""
    return (
        "query($owner: String!, $name: String!, $since: DateTime, $cursor: String) {"
        " repository(owner: $owner, name: $name) {"
        f' issues(labels: ["{PROJECT_LABEL}"], states: {states}, first: {PROJECT_PAGE}, after: $cursor,'
        " filterBy: {since: $since}, orderBy: {field: CREATED_AT, direction: ASC}) {"
        " pageInfo { hasNextPage endCursor } nodes { " + fields + " } } } }"
    )


OPEN_HEADS = projects_query("OPEN", LOCAL_FIELDS)
CLOSED_HEADS = projects_query("CLOSED", COUNT_FIELDS)


@dataclass(frozen=True)
class ProjectRow:
    """One head's row (S-106-12): its state, note, holder, check issue, and parts"""

    number: int
    state: str
    title: str
    note: str
    check: int | None
    parts_open: int
    parts_closed: int
    base: str | None = None  # an action's state underneath it, PROJECT_IDLE's and PROJECT_STOP_DUE's
    parent: int | None = None  # the head's sub-issue parent, its plan for a filed item (spec 106's goal rows)
    work: int | None = None  # a filed plan item's W-n, from its plan-item marker: its place in the plan's Work
    labelled: str | None = None  # when it was labelled project, ISO 8601 (the order of heads with no plan)

    @property
    def holder(self) -> str | None:
        return PROJECT_HOLDERS[self.state]

    @property
    def counted(self) -> bool:
        """S-106-28: active or in focus, under an action too"""
        return (self.base or self.state) in PROJECT_COUNTED


@dataclass(frozen=True)
class Projects:
    """--json's first line's projects and the text output's projects line (S-106-28)"""

    home: str
    limit: int
    active: int

    @property
    def room(self) -> int:
        return max(self.limit - self.active, 0)

    def json(self) -> dict[str, int]:
        return {"limit": self.limit, "active": self.active, "room": self.room}

    def line(self) -> str:
        return f"projects active: {self.active} of {self.limit} (product {self.home})"


def is_head(head: dict[str, Any], bot_login: str | None) -> bool:
    """A head is labelled `project` and was opened by an OWNER, MEMBER, or COLLABORATOR or the
    --bot-login, or labelled `project` by a person other than its opener, or by the --bot-login:
    GitHub lets only a person with triage access label another's issue, while a label an issue
    form adds on opening is the opener's own. Another bot's label counts for nothing, as an
    outsider's text can make a workflow add one (D-16)"""
    if PROJECT_LABEL not in labels(head):
        return False
    # logins as --bot-login spells them: GraphQL gives a Bot's without "[bot]" (plans.py's login)
    author = PLANS.login(head.get("author"))
    if bot_login is not None and author.lower() == bot_login.lower():
        return True
    if str(head.get("authorAssociation") or "NONE") in PLANS.TRUSTED:
        return True
    for event in (head.get("timelineItems") or {}).get("nodes") or []:
        if (event.get("label") or {}).get("name") != PROJECT_LABEL:
            continue
        actor = event.get("actor")
        if not actor or not actor.get("login"):
            continue
        login = PLANS.login(actor)
        if bot_login is not None and login.lower() == bot_login.lower():
            return True
        if actor.get("__typename") == "User" and login != author:
            return True
    return False


def complete(connection: dict[str, Any], what: str) -> list[dict[str, Any]]:
    """A sub-issue connection's nodes, refused when GitHub has more than the page read"""
    nodes: list[dict[str, Any]] = connection.get("nodes") or []
    if int(connection.get("totalCount") or 0) > len(nodes):
        fail(f"{what} has {connection['totalCount']} sub-issues, more than intake_state.py reads ({len(nodes)})")
    return nodes


def is_check(sub: dict[str, Any]) -> bool:
    """spec 042's check issue: a title starting `Check: ` and a `## Check` section"""
    return (
        str(sub.get("title") or "").startswith(CHECK_TITLE) and CHECK_SECTION.search(sub.get("body") or "") is not None
    )


def cleanup_note(body: str) -> str:
    """The unchecked `- [ ]` lines of the check issue's `## Cleanup` section, or `no cleanup listed`"""
    found = CLEANUP_SECTION.search(body)
    if found is None:
        return "no cleanup listed"
    section = body[found.end() :]
    following = re.search(r"^##[ \t]", section, re.MULTILINE)
    lines = UNCHECKED.findall(section if following is None else section[: following.start()])
    return "cleanup: " + "; ".join(lines) if lines else "no cleanup listed"


def stopped(head: dict[str, Any], bot_login: str | None) -> str | None:
    """The --bot-login's stop record on the head, a comment whose first line is the marker: its
    reason, the first line after the marker that isn't the agent marker (S-106-21), or `stopped`
    when it gives none; None without a record"""
    if bot_login is None:
        return None
    for comment in reversed((head.get("comments") or {}).get("nodes") or []):
        body = (comment.get("body") or "").strip()
        first, _, rest = body.partition("\n")
        if PLANS.login(comment.get("author")).lower() != bot_login.lower() or first.strip() != STOP_RECORD:
            continue
        reason = next(
            (ln.strip() for ln in rest.splitlines() if ln.strip() and not AGENT_MARKER.fullmatch(ln.strip())), ""
        )
        return f"stopped: {reason}" if reason else "stopped"
    return None


def project_row(head: dict[str, Any], bot_login: str | None) -> ProjectRow | None:
    """S-106-12: the state a head reads, None for an issue that is no head (not labelled
    `project`, or not by a trusted author) and for a head closed otherwise than completed or
    stopped. Its check issue is the head's sub-issue titled `Check: ` with a `## Check` section,
    an open one first; its parts are the head's other sub-issues and the check issue's"""
    if not is_head(head, bot_login):
        return None
    number, title = int(head["number"]), str(head.get("title") or "")
    subs = complete(head.get("subIssues") or {}, f"project #{number}")
    checks = [sub for sub in subs if is_check(sub)]
    check = next((c for c in checks if c["state"] == "OPEN"), checks[0] if checks else None)
    parts = [sub for sub in subs if not is_check(sub)]  # a second check issue is no part
    counted = (check or {}).get("subIssuesSummary")  # a product count's: the check's parts as counts
    if check is not None and counted is None:
        parts += complete(check.get("subIssues") or {}, f"check issue #{check['number']}")
    open_parts = sum(1 for part in parts if part["state"] == "OPEN")
    all_parts = len(parts)
    if counted is not None:
        open_parts += int(counted["total"]) - int(counted["completed"])
        all_parts += int(counted["total"])
    check_number = None if check is None else int(check["number"])

    parent = (head.get("parent") or {}).get("number")
    item = WORK_ITEM.match(PLANS.first_line(head.get("body") or ""))
    work = int(item.group(2)) if item is not None and parent is not None and int(item.group(1)) == parent else None
    events = (head.get("timelineItems") or {}).get("nodes") or []
    labelled = next(
        (
            str(e["createdAt"])
            for e in events
            if (e.get("label") or {}).get("name") == PROJECT_LABEL and e.get("createdAt")
        ),
        None,
    )

    def row(state: str, note: str) -> ProjectRow:
        closed = all_parts - open_parts
        return ProjectRow(
            number, state, title, note, check_number, open_parts, closed, parent=parent, work=work, labelled=labelled
        )

    if head["state"] != "OPEN":
        if head.get("stateReason") == "COMPLETED":
            return row("PROJECT_CLOSED", "closed as completed")
        record = stopped(head, bot_login) if head.get("stateReason") == "NOT_PLANNED" else None
        return None if record is None else row("PROJECT_STOPPED", record)
    names = labels(head)
    if PROJECT_HELD_LABEL in names:
        return row("PROJECT_HELD", f"labelled {PROJECT_HELD_LABEL}")
    if check is None:
        return row("PROJECT_HELD", "no check issue")
    if check["state"] != "OPEN":  # checked, but the head is still open: whoever closes it next
        return row("PROJECT_CLOSING", f"check #{check_number} closed; the head is open")
    if all_parts and open_parts == 0:
        return row("PROJECT_CLOSING", cleanup_note(check.get("body") or ""))
    focus = PROJECT_FOCUS_LABEL in names
    note = f"{open_parts} of {all_parts} parts open" if all_parts else "no part filed"
    return row("PROJECT_FOCUS" if focus else "PROJECT_ACTIVE", note)


def is_question(comment: dict[str, Any], bot_login: str | None) -> bool:
    """A needs-decision question by the --bot-login (its first line the marker)"""
    by_bot = bot_login is not None and PLANS.login(comment.get("author")).lower() == bot_login.lower()
    return by_bot and PLANS.first_line(comment.get("body") or "") == DECISION_MARKER


def stop_reason(head: dict[str, Any], bot_login: str | None, marker: str, maintainers: frozenset[str]) -> str | None:
    """S-106-18: the reason of a stop, when the newest trusted reply on the head is one: a
    first line `stop: <reason>`, or `stop` answering the --bot-login's question before it, the
    reason on its next non-blank line. A reply is an OWNER's, MEMBER's, or COLLABORATOR's other
    than the --bot-login, or the --bot-login's relay of a maintainer's answer (D-16, D-68); a
    newer reply that is no stop lifts it, and an untrusted one changes nothing"""
    comments = sorted((head.get("comments") or {}).get("nodes") or [], key=lambda c: timestamp(c["createdAt"]))
    asked = False
    newest: tuple[str, bool] | None = None  # the newest reply, and whether a question came before it
    for comment in comments:
        if is_question(comment, bot_login):
            asked = True
            continue
        answer = relayed_answer(comment, bot_login, marker, maintainers)
        if answer is None and answerer(comment, bot_login, marker):
            answer = comment.get("body") or ""
        if answer is not None:
            newest = (answer, asked)
            asked = False  # a bare `stop` answers only the question right before it
    if newest is None:
        return None
    lines = [ln.strip() for ln in newest[0].strip().splitlines() if ln.strip()]
    line = STOP_LINE.match(lines[0]) if lines else None
    if line is not None:
        return line.group(1)
    if newest[1] and lines and STOP_ANSWER.match(lines[0]) and len(lines) > 1:
        return lines[1]
    return None


def tree_updated(head: dict[str, Any], bot_login: str | None) -> dt.datetime:
    """S-106-17: the tree's last update: its parts' and check issue's, the pull requests that
    close any of them or the head, and the head's comments, the --bot-login's questions left
    out (a question is no change), or its opening. The head's own updatedAt isn't read: the
    question itself would move it"""
    times = [timestamp(head["createdAt"])]
    times += [timestamp(c["createdAt"]) for c in head["comments"]["nodes"] if not is_question(c, bot_login)]

    def linked(node: dict[str, Any]) -> list[dt.datetime]:
        refs = (node.get("closedByPullRequestsReferences") or {}).get("nodes") or []
        return [timestamp(p["updatedAt"]) for p in refs]

    times += linked(head)
    for sub in (head.get("subIssues") or {}).get("nodes") or []:
        times += [timestamp(sub["updatedAt"]), *linked(sub)]
        for part in (sub.get("subIssues") or {}).get("nodes") or []:
            times += [timestamp(part["updatedAt"]), *linked(part)]
    return max(times)


def project_action(
    head: dict[str, Any],
    read: ProjectRow,
    bot_login: str | None,
    now: dt.datetime,
    marker: str,
    maintainers: frozenset[str],
) -> ProjectRow:
    """An open head's action over its state: PROJECT_STOP_DUE on a stop (S-106-18), else
    PROJECT_IDLE for an active, in-focus, or closing head whose tree has had no update for
    IDLE_DAYS days and no question by the --bot-login since (S-106-17); its state otherwise"""
    if head["state"] != "OPEN":
        return read
    reason = stop_reason(head, bot_login, marker, maintainers)
    if reason is not None:
        return replace(read, state="PROJECT_STOP_DUE", note=f"stop: {reason}", base=read.state)
    if read.state not in ("PROJECT_ACTIVE", "PROJECT_FOCUS", "PROJECT_CLOSING"):
        return read
    last = tree_updated(head, bot_login)
    if now - last < dt.timedelta(days=IDLE_DAYS):
        return read
    comments = (head.get("comments") or {}).get("nodes") or []
    if any(is_question(c, bot_login) and timestamp(c["createdAt"]) > last for c in comments):
        return read  # the idle question waits for its answer
    note = f"no change since {last.strftime('%Y-%m-%d')}"
    return replace(read, state="PROJECT_IDLE", note=note, base=read.state)


def fetch_projects(
    repo: str,
    bot_login: str | None,
    now: dt.datetime,
    run: Runner,
    marker: str = "Triage:",
    maintainers: frozenset[str] = frozenset(),
) -> list[ProjectRow]:
    """S-106-12: a row per open head and per head closed within PROJECT_DAYS days, oldest first,
    an open head's action over its state (project_action)"""
    owner, name = split_repo(repo)
    since = (now - dt.timedelta(days=PROJECT_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    found: list[ProjectRow] = []
    for states, after in (("OPEN", None), ("CLOSED", since)):
        query = OPEN_HEADS if states == "OPEN" else CLOSED_HEADS
        variables: Variables = {"owner": owner, "name": name, **({"since": after} if after else {})}
        heads, _ = paged(run, query, variables, "issues")
        for head in heads:
            if states == "CLOSED" and timestamp(str(head.get("closedAt"))) < now - dt.timedelta(days=PROJECT_DAYS):
                continue
            read = project_row(head, bot_login)
            if read is not None:
                found.append(project_action(head, read, bot_login, now, marker, maintainers))
    return found


def heads_query(repos: list[str]) -> str:
    """One query that reads each repo's open heads, as fetch_projects reads them"""
    parts = []
    for i, repo in enumerate(repos):
        owner, name = split_repo(repo)
        where = f"owner: {json.dumps(owner)}, name: {json.dumps(name)}"
        connection = f'issues(labels: ["{PROJECT_LABEL}"], states: OPEN, first: {PRODUCT_HEADS})'
        parts.append(f"r{i}: repository({where}) {{ {connection} {{ totalCount nodes {{ {COUNT_FIELDS} }} }} }}")
    return "query { " + " ".join(parts) + " }"


def projects_active(
    product: Product,
    local: list[ProjectRow],
    gh: ProductGh,
    bot_login: str | None,
    seen: dict[str, list[ProjectRow]] | None = None,
) -> Projects | None:
    """S-106-28: the product's heads reading active or in focus: the checkout's own, local, and
    every other repo's, read with one `shipmill gh --product` per owner (its repo the home when
    the owner's repos include it, else the owner's first) and read as fetch_projects reads them.
    A read that fails exits 2 naming the repos, never counted as empty. None without a limit,
    and then nothing is read. seen, when given, gets each other repo's heads (spec 106's start
    order reads them)"""
    if product.limit is None:
        return None
    owners: dict[str, list[str]] = {}
    for repo in product.repos[1:]:
        owners.setdefault(repo.partition("/")[0].lower(), []).append(repo)
    total = sum(1 for r in local if r.counted)
    for group in owners.values():
        via = next((r for r in group if r.lower() == product.home.lower()), group[0])
        step = f"counting the active projects of {', '.join(group)}"
        try:
            data = gh.graphql(via, heads_query(group), {}, step)
        except Unreadable as failed:
            fail(str(failed))
        for i, repo in enumerate(group):
            issues = (data.get(f"r{i}") or {}).get("issues")
            if not isinstance(issues, dict) or not isinstance(issues.get("totalCount"), int):
                fail(f"{step}: GitHub returned no open heads for {repo}")
            if issues["totalCount"] > len(issues.get("nodes") or []):
                fail(f"{step}: {repo} has {issues['totalCount']} open heads, more than intake_state.py reads")
            for head in issues.get("nodes") or []:
                read = project_row(head, bot_login)
                if read is not None and seen is not None:
                    seen.setdefault(repo, []).append(read)
                if read is not None and read.counted:
                    total += 1
    return Projects(product.home, product.limit, total)


# -- spec 106: an overdue plan stops the product's new starts, and held heads start in turn

OPEN_PLAN_ISSUES = PLAN_ISSUES.replace(
    "issues(labels: [$label], first:", "issues(labels: [$label], states: OPEN, first:"
)
if OPEN_PLAN_ISSUES == PLAN_ISSUES:
    raise RuntimeError("OPEN_PLAN_ISSUES no longer narrows PLAN_ISSUES to open plans")


def unmet(hold: Hold) -> HoldMet:
    """Another repo's held plan reads held: its hold isn't read here, and a held plan is never
    overdue (spec 106's product read stays one query a repo)"""
    return HoldMet(None, hold.until)


@dataclass(frozen=True)
class ProductPlans:
    """What the product's open plans say (spec 106): the overdue ones, as owner/repo#P, and when
    each accepted plan was accepted, by (owner/repo lowercased, P)"""

    overdue: tuple[str, ...]
    accepted: dict[tuple[str, int], dt.datetime]


def read_product_plans(
    issues: dict[str, list[dict[str, Any]]],
    now: dt.datetime,
    bot_login: str | None,
    marker: str,
    maintainers: frozenset[str],
    own: tuple[str, HoldReader, frozenset[str]] | None = None,
) -> ProductPlans:
    """S-106-9, S-106-14: each repo's open plan issues read as --plans reads them: overdue past
    its answer date, or accepted at its answer's time. own is the checkout's repo, its hold
    reader, and its direction's goals, so its plans read exactly as --plans prints them; another
    repo's held plan reads held, and its goals are each plan's own"""
    overdue: list[str] = []
    accepted: dict[tuple[str, int], dt.datetime] = {}
    for repo, plans in issues.items():
        for issue in plans:
            if issue.get("state") != "OPEN" or not is_plan(issue, bot_login):
                continue
            goal = plan_goal(issue)
            mine = own is not None and repo.lower() == own[0].lower()
            goals = own[2] if own is not None and mine and own[2] else frozenset({goal} if goal else set())
            row = plan_state(
                issue,
                goals=goals,
                marker=marker,
                bot_login=bot_login,
                filing=lambda issue, plan: ("PLAN_FILED", ""),
                maintainers=maintainers,
                holds=own[1] if own is not None and mine else unmet,
            )
            if row is None:
                continue
            row = dated(row, issue, now, bot_login, marker, maintainers)
            if row.state == "PLAN_OVERDUE":
                overdue.append(f"{repo}#{issue['number']}")
            answer = plan_answer(issue, bot_login, marker, maintainers)
            if row.state in ("PLAN_ACCEPTED", "PLAN_FILED") and answer is not None and answer.kind == "accept":
                accepted[(repo.lower(), int(issue["number"]))] = answer.at
    return ProductPlans(tuple(sorted(overdue)), accepted)


def product_plan_issues(product: Product, here: list[dict[str, Any]], gh: ProductGh) -> dict[str, list[dict[str, Any]]]:
    """The open plan issues of every repo of the product: the checkout's own, here, and every
    other repo's through `shipmill gh --product`, a query a page; a read that fails exits 2
    naming the repo"""
    found = {product.repos[0]: here}
    for repo in product.repos[1:]:
        owner, name = split_repo(repo)
        nodes: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            variables = {"owner": owner, "name": name, "label": PLAN_LABEL, **({"cursor": cursor} if cursor else {})}
            step = f"reading the open plans of {repo}"
            try:
                data = gh.graphql(repo, OPEN_PLAN_ISSUES, variables, step)
            except Unreadable as failed:
                fail(str(failed))
            issues = (data.get("repository") or {}).get("issues")
            if not isinstance(issues, dict):
                fail(f"{step}: GitHub returned no issues for {repo}")
            nodes += issues["nodes"]
            if not issues["pageInfo"]["hasNextPage"]:
                break
            cursor = issues["pageInfo"]["endCursor"]
        found[repo] = nodes
    return found


def overdue_waits(rows: list[PlanRow], overdue: tuple[str, ...]) -> list[PlanRow]:
    """S-106-9: while a plan of the product reads PLAN_OVERDUE, a goal's no-work PLAN_DUE reads
    PLAN_WAITS `plan <owner/repo>#P overdue`; a request's PLAN_DUE stays"""
    if not overdue:
        return rows
    note = f"plan {overdue[0]} overdue"
    found = []
    for row in rows:
        automatic = row.kind == "goal" and row.state in ("PLAN_DUE", "PLAN_WAITS") and row.note.startswith("no-work")
        found.append(replace(row, state="PLAN_WAITS", note=note, dropped=None) if automatic else row)
    return found


def start_due(
    heads: dict[str, list[ProjectRow]],
    here: str,
    projects: Projects | None,
    plans: ProductPlans,
) -> list[ProjectRow]:
    """S-106-14: the checkout's heads, its held ones read PROJECT_START_DUE in their turn. With
    room under [agents] projects (no limit: every held head), and no plan of the product
    overdue, the product's held heads start as many as the room, a filed plan item's first, by
    its plan's accept time across the product and then its Work order, then heads with no
    accepted plan by when they were labelled; each repo's pass starts its own alone"""
    held = [(repo, h) for repo, rows in heads.items() for h in rows if h.state == "PROJECT_HELD"]
    if plans.overdue:
        room = 0
    elif projects is None:
        room = len(held)
    else:
        room = projects.room

    def turn(entry: tuple[str, ProjectRow]) -> tuple[Any, ...]:
        repo, head = entry
        accepted = plans.accepted.get((repo.lower(), head.parent)) if head.parent is not None else None
        if accepted is not None:  # an item with no marker comes after its plan's numbered ones
            return (0, accepted.isoformat(), head.work if head.work is not None else 10**9, repo.lower(), head.number)
        return (1, head.labelled or "9999", 0, repo.lower(), head.number)  # never labelled: last

    chosen = {(repo.lower(), head.number) for repo, head in sorted(held, key=turn)[:room]}
    found = []
    for head in heads.get(here, []):
        if (here.lower(), head.number) in chosen:
            head = replace(head, state="PROJECT_START_DUE", note="its turn to start", base=head.state)
        found.append(head)
    return found


def show_project(row: ProjectRow) -> str:
    return f"{row.state:<17} #{row.number:<6} {row.note}  {row.title}"


def project_json(row: ProjectRow) -> dict[str, Any]:
    """A project row's --json line (S-106-12): state, holder, check (null without one), and parts"""
    return {
        "kind": "project",
        "number": row.number,
        "state": row.state,
        "title": row.title,
        "note": row.note,
        "holder": row.holder,
        "check": row.check,
        "parts": {"open": row.parts_open, "closed": row.parts_closed},
    }


# -- spec 106: a goal's state, read from the direction, its plans, and its projects

GOAL_PROPOSAL_LABEL = "goal-proposal"
GOAL_REVIEW_LABEL = "goal-review"
# the --bot-login's goal-review issue for a goal past its horizon, its first line (S-106-5)
OVERDUE_MARKER = re.compile(r"^<!-- shipmill:goal-overdue (G-[1-9][0-9]*) by=(\S+) -->$")
GOAL_REVIEWS = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(labels: ["goal-review"], first: 100, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor } nodes { number body author { __typename login } }
    }
  }
}
"""
# the goal rows' holders (spec 106's table)
GOAL_ACTION = frozenset({"GOAL_OVERDUE"})


@dataclass(frozen=True)
class GoalRow:
    """One goal's row (S-106-4): its state, holder, and horizon; a proposal's row has no goal id
    and the proposal issue's number"""

    goal: str | None
    state: str
    title: str
    note: str
    holder: str | None
    by: str | None
    number: int | None = None


def release_tagged(repo: str, releases: list[str], run: Runner) -> set[str]:
    """S-106-5: the release horizons with a tag of that version on the forge, `X.Y.Z` or
    `vX.Y.Z` (a stable version, no pre-release), read with one query for them all"""
    if not releases:
        return set()
    owner, name = split_repo(repo)
    parts = []
    for i, release in enumerate(releases):
        bare = release.removeprefix("v")
        refs = (f"refs/tags/{bare}", f"refs/tags/v{bare}")
        parts += [f"t{i}a: ref(qualifiedName: {json.dumps(refs[0])}) {{ name }}"]
        parts += [f"t{i}b: ref(qualifiedName: {json.dumps(refs[1])}) {{ name }}"]
    query = "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { " + " ".join(parts)
    data = repository(run, query + " } }", {"owner": owner, "name": name})
    return {r for i, r in enumerate(releases) if data.get(f"t{i}a") or data.get(f"t{i}b")}


def reviewed(repo: str, bot_login: str | None, run: Runner) -> set[tuple[str, str]]:
    """S-106-5: each (goal, horizon) a goal-review issue by the --bot-login names on its first
    line; anyone else's marker counts for nothing"""
    owner, name = split_repo(repo)
    issues, _ = paged(run, GOAL_REVIEWS, {"owner": owner, "name": name}, "issues")
    found: set[tuple[str, str]] = set()
    for issue in issues:
        by_bot = bot_login is not None and PLANS.login(issue.get("author")).lower() == bot_login.lower()
        marker = OVERDUE_MARKER.match(PLANS.first_line(issue.get("body") or ""))
        if by_bot and marker is not None:
            found.add((marker.group(1), marker.group(2)))
    return found


def goal_rows(
    goals: list[Goal],
    plans: list[PlanRow],
    heads: list[ProjectRow],
    open_issues: list[dict[str, Any]],
    bot_login: str | None,
    tagged: set[str],
    reviews: set[tuple[str, str]],
    checked: frozenset[str] = frozenset(),
) -> list[GoalRow]:
    """S-106-4, S-106-5: a row per open goal-proposal issue by a trusted author or the
    --bot-login, then one per goal of kind goal: met or dropped from the direction; planned
    while an accepted plan of it is open (PLAN_ACCEPTED or PLAN_FILED) or a project head whose
    parent is one of its plans is open; written otherwise. A written or planned goal whose date
    horizon has ended, or whose release is tagged, reads GOAL_OVERDUE until the --bot-login's
    goal-review issue names that goal and horizon. A measure and a goal of no kind read none"""
    found: list[GoalRow] = []
    for issue in open_issues:
        if GOAL_PROPOSAL_LABEL not in labels(issue) or not PLANS.trusted(issue, bot_login):
            continue
        number = int(issue["number"])
        title = str(issue.get("title") or "")
        found.append(GoalRow(None, "GOAL_PROPOSED", title, "waits on your answer", "maintainer", None, number))
    plans_of: dict[str, list[PlanRow]] = {}
    for plan in plans:
        if plan.kind == "plan" and plan.goal is not None:
            plans_of.setdefault(plan.goal, []).append(plan)
    ended = ("PROJECT_CLOSED", "PROJECT_STOPPED")
    open_heads = {h.parent: h.number for h in heads if h.parent is not None and h.state not in ended}
    for goal in goals:
        if goal.kind != "goal":
            continue
        if goal.state is not None:
            found.append(GoalRow(goal.id, f"GOAL_{goal.state.upper()}", goal.text, goal.state, None, goal.by))
            continue
        mine = plans_of.get(goal.id, [])
        accepted = [p for p in mine if p.state in ("PLAN_ACCEPTED", "PLAN_FILED")]
        project = next((open_heads[p.number] for p in mine if p.number in open_heads), None)
        own = [p for p in mine if p.state not in ("PLAN_DECLINED", "PLAN_DONE")]
        if accepted:
            state, note, holder = "GOAL_PLANNED", f"plan #{accepted[0].number} accepted", "projects"
        elif project is not None:
            state, note, holder = "GOAL_PLANNED", f"project #{project} open", "projects"
        elif goal.id in checked:
            state, note, holder = "GOAL_PLANNED", "its check holds; the goal met waits on your merge", "maintainer"
        elif own and own[0].state == "PLAN_OPEN":
            state, note, holder = "GOAL_WRITTEN", f"plan #{own[0].number} waits on your answer", "maintainer"
        elif own:
            state, note, holder = "GOAL_WRITTEN", f"plan #{own[0].number} reads {own[0].state}", "agent"
        else:
            state, note, holder = "GOAL_WRITTEN", "a plan is due", "agent"
        due = goal.past is True or (goal.by is not None and goal.past is None and goal.by in tagged)
        due = due and goal.id not in checked  # its check holds: the goal met waits, not a new horizon
        if due and goal.by is not None and (goal.id, goal.by) not in reviews:
            when = f"past {goal.by}" if goal.past else f"release {goal.by} tagged"
            found.append(GoalRow(goal.id, "GOAL_OVERDUE", goal.text, f"{when}; {note}", "agent", goal.by))
            continue
        found.append(GoalRow(goal.id, state, goal.text, note, holder, goal.by))
    return found


def show_goal(row: GoalRow) -> str:
    where = row.goal if row.goal is not None else f"#{row.number}"
    return f"{row.state:<16} {where:<7} {row.note}  {row.title}"


def goal_json(row: GoalRow) -> dict[str, Any]:
    """A goal row's --json line (S-106-4): state, holder, and by (the horizon, or null)"""
    return {
        "kind": "goal-state",
        "goal": row.goal,
        "number": row.number,
        "state": row.state,
        "title": row.title,
        "note": row.note,
        "holder": row.holder,
        "by": row.by,
    }


# -- spec 106: an accepted opportunity names the goal it serves

# Opportunities accepted (labelled) from this time on name their goal; one accepted before
# spec 106's build keeps its path to the spec gate (S-106-24)
GOAL_ACCEPTS_FROM = dt.datetime(2026, 11, 27, tzinfo=UTC)
ACCEPT_GOAL = re.compile(r"^accept[ \t]+(G-[1-9][0-9]*)[ \t]*\.?$", re.IGNORECASE)
ACCEPT_NEW_GOAL = re.compile(r"^accept[ \t]+new[ \t]+goal[ \t]*\.?$", re.IGNORECASE)
NEW_GOAL = "new goal"
ACCEPTED_OPPORTUNITIES = """
query($owner: String!, $name: String!, $label: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(labels: [$label], states: OPEN, first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number parent { number }
        timelineItems(itemTypes: [LABELED_EVENT], last: 10) {
          nodes { ... on LabeledEvent { createdAt label { name } } }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class Accepted:
    """When an open opportunity was labelled accepted, and its sub-issue parent (spec 106)"""

    at: dt.datetime | None
    parent: int | None


def accepted_reads(repo: str, label: str, run: Runner) -> dict[int, Accepted]:
    """Each open issue labelled the accept label: when the label was last added, and its parent"""
    owner, name = split_repo(repo)
    nodes, _ = paged(run, ACCEPTED_OPPORTUNITIES, {"owner": owner, "name": name, "label": label}, "issues")
    found: dict[int, Accepted] = {}
    for node in nodes:
        events = (node.get("timelineItems") or {}).get("nodes") or []
        times = [timestamp(e["createdAt"]) for e in events if (e.get("label") or {}).get("name") == label]
        found[int(node["number"])] = Accepted(max(times) if times else None, (node.get("parent") or {}).get("number"))
    return found


def accept_goal(issue: dict[str, Any], marker: str, bot_login: str | None, maintainers: frozenset[str]) -> str | None:
    """S-106-22: the goal an accepted opportunity serves: the newest trusted reply whose first
    line is `accept G-<n>` or `accept new goal` (the App's relay naming a maintainer too, D-68),
    else the one goal its body's `Serves:` line names; None with neither"""
    named: str | None = None
    for comment in (issue.get("comments") or {}).get("nodes") or []:
        answer = relayed_answer(comment, bot_login, marker, maintainers)
        if answer is None and answerer(comment, bot_login, marker):
            answer = comment.get("body") or ""
        first = PLANS.first_line(answer or "")
        goal = ACCEPT_GOAL.match(first)
        if goal is not None:
            named = goal.group(1).upper()
        elif ACCEPT_NEW_GOAL.match(first):
            named = NEW_GOAL
    if named is not None:
        return named
    goals = serves(issue.get("body") or "")
    return next(iter(goals)) if len(goals) == 1 else None


def opportunity_goals(
    found: list[Item],
    intake: Intake,
    goals: list[Goal],
    reads: dict[int, Accepted],
    marker: str,
    bot_login: str | None,
    maintainers: frozenset[str],
) -> list[Item]:
    """S-106-22, S-106-24: an ACCEPTED opportunity accepted from GOAL_ACCEPTS_FROM on reads by
    the goal it names: ACCEPTED_INTO `G-<n>` for a goal of kind goal still open (written or
    planned); for `accept new goal`, GOAL_PROPOSAL_DUE until the App's open `goal-proposal`
    issue is its sub-issue parent, then GOAL_PROPOSED; NEEDS_GOAL for no goal, or one that is a
    measure, of no kind, met, dropped, or not listed. Any other opportunity reads as before"""
    issues = {int(i["number"]): i for i in intake.opportunity_issues}
    proposals = {
        int(i["number"])
        for i in intake.open_issues
        if GOAL_PROPOSAL_LABEL in labels(i)
        and bot_login is not None
        and PLANS.login(i.get("author")).lower() == bot_login.lower()
    }
    open_goals = {g.id for g in goals if g.kind == "goal" and g.state is None}
    rows = []
    for item in found:
        read = reads.get(item.number)
        issue = issues.get(item.number)
        if item.state != "ACCEPTED" or read is None or issue is None or read.at is None or read.at < GOAL_ACCEPTS_FROM:
            rows.append(item)
            continue
        goal = accept_goal(issue, marker, bot_login, maintainers)
        if goal == NEW_GOAL:
            if read.parent in proposals:
                item = replace(item, state="GOAL_PROPOSED", note=f"goal proposal #{read.parent} waits on your answer")
            else:
                item = replace(item, state="GOAL_PROPOSAL_DUE", note="open its goal proposal")
        elif goal in open_goals:
            item = replace(item, state="ACCEPTED_INTO", note=goal)
        else:
            why = "names no goal" if goal is None else f"{goal} is no goal still open"
            item = replace(item, state="NEEDS_GOAL", note=f"{why}: answer `accept G-<n>` or `accept new goal`")
        rows.append(item)
    return rows


def show(row: Item) -> str:
    detail = []
    if row.kind == "opportunity":
        detail.append(f"{len(row.members)} requests, +1 {row.thumbs}")
    else:
        detail.append(f"+1 {row.thumbs}")
    if row.note:
        detail.append(row.note)
    return f"#{row.number:<5} {row.state:<16} {row.title[:70]}  [{'; '.join(detail)}]"


# the lines the watch places (spec 074), and the accepted opportunities that name their goal,
# whose opener the watch's trust reads before a session starts for one (spec 106, D-16)
PLACED = {"NEW_FEEDBACK", "ACCEPTED", "ACCEPTED_INTO", "GOAL_PROPOSAL_DUE", "GOAL_PROPOSED", "NEEDS_GOAL"}


def json_row(row: Item) -> dict[str, Any]:
    """A row's --json line; a NEW_FEEDBACK or ACCEPTED line also has author, association, and handed"""
    line: dict[str, Any] = {
        "number": row.number,
        "kind": row.kind,
        "state": row.state,
        "title": row.title,
        "thumbs": row.thumbs,
        "members": row.members,
        "note": row.note,
    }
    if row.state in PLACED:
        line.update(author=row.author, association=row.association, handed=row.handed)
    return line


def plan_json(row: PlanRow) -> dict[str, Any]:
    """A plan row's --json line: its opener and their author association, which the watch's
    trust reads (D-16, #1680), null on a goal's row; an accepted plan's row also has kept and
    dropped, and a PLAN_DUE row dropped, the items the goal's earlier plans dropped (spec 096)"""
    found: dict[str, Any] = {"goal": row.goal, "kind": row.kind, "number": row.number, "state": row.state}
    found.update(title=row.title, note=row.note, author=row.author, association=row.association)
    if row.kept is not None:
        found["kept"] = list(row.kept)
    if row.dropped is not None:
        found["dropped"] = list(row.dropped)
    if row.follows is not None:  # spec 097: the finished plan a goal's row follows, and what it left missing
        found.update(follows=row.follows, missing=list(row.missing or ()))
    if row.hold is not None:  # spec 098: a held plan's condition and when it was met
        found["hold"] = {"until": row.hold[0], "met_at": row.hold[1]}
    if row.answer_by is not None:  # spec 106: a PLAN_OPEN or PLAN_OVERDUE plan's answer date
        found["answer_by"] = row.answer_by
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--config", type=Path, help="the shipmill config (default: .github/shipmill.toml)")
    parser.add_argument("--label", default="opportunity", help="the label of opportunity issues")
    parser.add_argument("--accepted-label", default="planned", help="the label the maintainer accepts with")
    parser.add_argument("--marker", default="Triage:", help="prefix of a triage comment")
    parser.add_argument(
        "--skip-label", action="append", default=[], help=f"not feedback, added to {list(SKIP_LABELS)} (repeatable)"
    )
    parser.add_argument("--category", action="append", help="discussion categories that count (repeatable)")
    parser.add_argument("--json", action="store_true", help="JSON lines instead of a table")
    parser.add_argument("--plans", action="store_true", help="also report the goals a plan is due for (spec 028)")
    parser.add_argument("--wip", type=int, help="with --plans: no-work plans wait while N issues are in progress")
    parser.add_argument(
        "--projects", action="store_true", help="also report the projects, heads labelled project (spec 106)"
    )
    parser.add_argument(
        "--goals", action="store_true", help="also report each goal's state, and the goal proposals (spec 106)"
    )
    parser.add_argument(
        "--bot-login", help="the login shipmill's sessions write as (<slug>[bot]); its triage comments count (D-16)"
    )
    parser.add_argument(
        "--tool", help="with --plans: where uvx gets shipmill (default: shipmill==<the plugin.json version>)"
    )
    parser.add_argument(
        "--role",
        action="append",
        default=[],
        metavar="NAME=FILLER[,FILLER...]",
        help="with --plans: a role's resolved fillers, as `shipmill roles --flags` prints them; a relayed answer "
        "counts only when it names a maintainer (D-68)",
    )
    parser.add_argument(
        "--stable-tag-regex",
        default=STABLE.pattern,
        help="with --plans: tags that count as stable releases for a plan held `until release` (spec 098), "
        "as triage_state.py's flag, e.g. '^\\d{4}\\.\\d{2}' for CalVer",
    )
    args = parser.parse_args()
    if not args.plans and args.wip is not None:
        parser.error("--wip goes with --plans")
    if not (args.plans or args.projects or args.goals) and args.role:
        parser.error("--role goes with --plans, --projects, or --goals")
    if args.wip is not None and args.wip < 1:
        parser.error("--wip must be at least 1")
    if args.bot_login is not None and not args.bot_login.strip():
        parser.error("--bot-login must not be empty")
    try:
        maintainers = maintainer_logins(args.role)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        stable = re.compile(args.stable_tag_regex)
    except re.error as exc:
        parser.error(f"--stable-tag-regex: {exc}")

    config = config_file(args.config)
    autonomy = intake_autonomy(config)
    product_gh = ProductGh(Path.cwd().resolve())
    product = product_of(args.repo, config, product_gh.home_config)
    intake = fetch(
        args.repo,
        label=args.label,
        accepted=args.accepted_label,
        marker=args.marker,
        skip=skip_labels(args.skip_label),
        categories=set(args.category) if args.category else None,
        autonomy=autonomy,
        bot_login=args.bot_login,
    )
    local_open = sum(1 for issue in intake.opportunity_issues if issue["state"] == "OPEN")
    outcomes = outcomes_in_flight(product, local_open, args.label, product_gh)
    found = rows(intake, None if outcomes is None else outcomes.room)
    planned: list[PlanRow] = []
    direction: list[Goal] = []
    checked: set[str] = set()  # spec 106: goals whose finished plan's check holds
    if args.plans or args.goals:  # the goals are read once; --goals reads the plans to place each goal
        direction = uvx_goals(args.tool)()
        # spec 106: an accepted opportunity names its goal, and its goal's plan takes it
        reads = accepted_reads(args.repo, args.accepted_label, gh_graphql) if direction else {}
        found = opportunity_goals(found, intake, direction, reads, args.marker, args.bot_login, maintainers)
        into: dict[str, tuple[int, dt.datetime]] = {}
        for item in sorted(found, key=lambda i: i.number):
            accepted_at = reads[item.number].at if item.number in reads else None
            if item.state == "ACCEPTED_INTO" and accepted_at is not None and item.note not in into:
                into[item.note] = (item.number, accepted_at)
        # every opportunity, open or closed: a plan item's head may close before its plan does
        named = {int(i["number"]): labels(i) for i in intake.opportunity_issues}
        planned = fetch_plans(
            args.repo,
            intake,
            checked=checked,
            into=into,
            opportunities=named,
            goals=lambda: direction,
            marker=args.marker,
            bot_login=args.bot_login,
            wip=args.wip,
            room=triage_room(args.repo, args.bot_login),
            maintainers=maintainers,
            holds=gh_holds(args.repo, gh_graphql_unreadable, dt.datetime.now(UTC), stable),
        )
    heads: list[ProjectRow] = []
    projects = None
    if args.projects or args.goals:  # spec 106: the heads; --goals reads them for a planned goal
        now = dt.datetime.now(UTC)
        heads = fetch_projects(args.repo, args.bot_login, now, gh_graphql, args.marker, maintainers)
    others: dict[str, list[ProjectRow]] = {}
    overdue: tuple[str, ...] = ()
    if args.plans or args.projects:  # spec 106: the product, as [agents] projects reads it
        limits = product_of(args.repo, config, product_gh.home_config, "projects")
        if args.projects:  # with [agents] projects, the product's active count
            projects = projects_active(limits, heads, product_gh, args.bot_login, others)
        owner, name = split_repo(args.repo)
        here, _ = paged(gh_graphql, OPEN_PLAN_ISSUES, {"owner": owner, "name": name, "label": PLAN_LABEL}, "issues")
        when = dt.datetime.now(UTC)
        own = (args.repo, gh_holds(args.repo, gh_graphql_unreadable, when, stable), frozenset(g.id for g in direction))
        issues = product_plan_issues(limits, here, product_gh)
        product_plans = read_product_plans(issues, when, args.bot_login, args.marker, maintainers, own)
        planned = overdue_waits(planned, product_plans.overdue)  # S-106-9
        overdue = product_plans.overdue if args.projects else ()
        heads = start_due({args.repo: heads, **others}, args.repo, projects, product_plans)  # S-106-14
    goal_states: list[GoalRow] = []
    if args.goals:  # spec 106: a row per goal of kind goal, and per goal proposal
        releases = sorted({g.by for g in direction if g.kind == "goal" and g.by is not None and g.past is None})
        tagged = release_tagged(args.repo, releases, gh_graphql)
        reviews = reviewed(args.repo, args.bot_login, gh_graphql)
        goal_states = goal_rows(
            direction, planned, heads, intake.open_issues, args.bot_login, tagged, reviews, frozenset(checked)
        )
    planned = planned if args.plans else []
    heads = heads if args.projects else []
    if args.json:
        print(json.dumps(first_line(autonomy, outcomes, projects, overdue)))
        for r in found:
            print(json.dumps(json_row(r), sort_keys=True))
        for p in planned:
            print(json.dumps(plan_json(p), sort_keys=True))
        for h in heads:
            print(json.dumps(project_json(h), sort_keys=True))
        for g in goal_states:
            print(json.dumps(goal_json(g), sort_keys=True))
    else:
        print(f"intake autonomy: {autonomy}")
        if outcomes is not None:
            print(outcomes.line())
        if projects is not None:
            print(projects.line())
        for r in found:
            print(show(r))
        for p in planned:
            print(show_plan(p))
        for h in heads:
            print(show_project(h))
        for g in goal_states:
            print(show_goal(g))
    actions = any(r.state in ACTION for r in found) or any(p.state in PLAN_ACTION for p in planned)
    actions = (
        actions or any(h.state in PROJECT_ACTION for h in heads) or any(g.state in GOAL_ACTION for g in goal_states)
    )
    return 1 if actions else 0


if __name__ == "__main__":
    sys.exit(main())
