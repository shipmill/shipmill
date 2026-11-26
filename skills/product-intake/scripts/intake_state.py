#!/usr/bin/env python3
"""Where a repo's product feedback stands: which requests no opportunity groups yet, and
where each opportunity issue is in the maintainer's accept or decline.

Usage: intake_state.py <owner/repo> [--config PATH] [--label opportunity]
                       [--accepted-label planned] [--marker "Triage:"] [--skip-label L]...
                       [--category C]... [--json] [--bot-login LOGIN]
                       [--plans [--wip N] [--tool SPEC] [--role NAME=FILLER[,FILLER...]]...
                                [--stable-tag-regex REGEX]]

Feedback is an open issue, or an open discussion when the repo enables Discussions, that:
  - carries none of SKIP_LABELS (bug, roadmap, and shipmill's own labels, goal-plan among
    them, so a plan issue or a request for one is never feedback), no --skip-label
    (repeatable, added to SKIP_LABELS), and not --label
  - is not triage's by its labels, whatever its comments say: not labelled postponed (it
    reads POSTPONED there), human, or role:<name> (a person's item; these two compared
    case-insensitively), as triage_state.py reads them
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
A component whose home's config can't be read (no read token, a home that doesn't list it, no
config on its default branch) has no limit either: output and exit code are as before, with
one `note:` line on stderr naming the failed read and the home.

With --json, each NEW_FEEDBACK and ACCEPTED line also has (spec 074): author, the opener's
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
(PLAN_HELD is no action), 2 on bad input (an
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
)
# Triage's own, whatever its comments say (#1628), as triage_state.py reads them: an issue
# labelled postponed (its --postponed-label default) reads POSTPONED, and one labelled human
# or role:<name>, compared case-insensitively, is a person's item (spec 017, spec 036)
POSTPONED_LABEL = "postponed"
HUMAN_LABEL = "human"
ROLE_PREFIX = "role:"
SKIP_CATEGORIES = ("Announcements",)
# A postponed issue is triage's too (spec 074): an unattended pass must not group it
CLOSING_VERDICTS = ("implement", "feature", "duplicate", "won't fix", "won’t fix", "wont fix", "postpone")
OWN_VERDICT = "opportunity"  # intake's triage comment on an opportunity it opens
REASON_WINDOW = dt.timedelta(hours=1)  # "close with comment" posts the comment just before the close
ACTION = {"NEW_FEEDBACK", "ACCEPTED", "NO_REASON", "OVERLAP"}
ORDER = (
    "OVERLAP",
    "NO_REASON",
    "ACCEPTED",
    "NEW_FEEDBACK",
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
PLAN_ACTION = {"PLAN_DUE", "PLAN_MALFORMED", "PLAN_ANSWERED", "PLAN_ACCEPTED", "PLAN_DONE", "PLAN_HOLD_MET"}
PLAN_ORDER = (
    "PLAN_DUE",
    "PLAN_MALFORMED",
    "PLAN_ANSWERED",
    "PLAN_ACCEPTED",
    "PLAN_DONE",
    "PLAN_HOLD_MET",
    "PLAN_WAITS",
    "PLAN_OPEN",
    "PLAN_HELD",
    "PLAN_FILED",
    "PLAN_DECLINED",
)
READ_CLOSED = ("NOT_PLANNED", "COMPLETED")  # the closed plans whose comments are paged back to their first
PLAN_OPENER = "<!-- shipmill:plan "  # a first line that means to be the plan marker, well-formed or not
SHIPMILL_MARKER = "<!-- shipmill:"  # a session's own marked comment, never an answer
REVISED = re.compile(r"^<!-- shipmill:plan-revised rev=([1-9][0-9]*) -->$")
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


def triage_owns(names: set[str]) -> bool:
    """Labelled postponed, or a person's item (human or role:<name>, any case) (#1628)"""
    folded = {n.lower() for n in names}
    return POSTPONED_LABEL in names or HUMAN_LABEL in folded or any(n.startswith(ROLE_PREFIX) for n in folded)


def is_feedback(issue: dict[str, Any], skip: set[str], marker: str, bot_login: str | None = None) -> bool:
    names = labels(issue)
    if names & skip or triage_owns(names):
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
    feedback = [
        Item(
            i["number"],
            "issue",
            i["title"],
            i["reactions"]["totalCount"],
            feedback=True,
            author=opener(i),
            association=i.get("authorAssociation"),
            handed=handed_at(i, marker, bot_login),
        )
        for i in opened
        if is_feedback(i, skip, marker, bot_login)
    ]
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


def rows(intake: Intake) -> list[Item]:
    """The opportunities with their evidence, then NEW_FEEDBACK and OVERLAP"""
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
            item.state = "NEW_FEEDBACK"
            item.note = item.kind
            found.append(item)
    states = {o.number: o.state for o in intake.opportunities}
    titles = {i.number: (i.kind, i.title) for i in intake.feedback}
    for number, owners in sorted(listed.items()):
        live = [o for o in owners if states[o] in LIVE]
        if len(live) > 1:
            kind, title = titles.get(number, ("member", ""))
            shown = ", ".join(f"#{o}:{states[o].lower()}" for o in live)
            found.append(Item(number, kind, title, intake.thumbs.get(number, 0), state="OVERLAP", note=shown))
    found.sort(key=lambda r: (ORDER.index(r.state), -r.number))
    return found


# -- goal plans (spec 028): which goals a plan is due for


@dataclass(frozen=True)
class Goal:
    id: str  # G-<n>
    text: str


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


# Reads the direction's goals, in the direction's order
GoalsReader = Callable[[], list[Goal]]
# The room `triage_state.py --wip N` reports under the limit N
RoomReader = Callable[[int], int]


def parse_goals(text: str) -> list[Goal]:
    """`shipmill product show --section goals --json`'s output, strictly"""
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
        goals.append(Goal(ident, text_))
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
    for issue in plan_issues:
        goal = plan_goal(issue)
        if goal is None:
            continue
        plans_of[issue["number"]] = goal
        if issue["state"] == "OPEN":
            planned.add(goal)
    declined = {g for g, i in newest.items() if i["state"] == "CLOSED" and i["stateReason"] == "NOT_PLANNED"}
    finished: set[str] = set()  # goals whose newest plan reads PLAN_DONE `closed without an outcome`
    follows: dict[str, tuple[int, tuple[str, ...]]] = {}  # the plan a goal's next one follows, and what it left missing
    for goal, issue in newest.items():
        if issue["state"] != "CLOSED" or issue["stateReason"] != "COMPLETED":
            continue
        found = plan_outcome(issue, bot_login)
        if found is None:
            finished.add(goal)
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
            requests[goal] = min(requests.get(goal, issue["number"]), issue["number"])

    found: list[PlanRow] = []
    left: int | None = None  # the room under --wip, read once and only when a goal waits on it
    for goal in goals:
        if goal.id in planned:
            continue
        if goal.id in requests:
            number = requests[goal.id]
            found.append(row(goal, "PLAN_DUE", f"requested in #{number}", number))
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
        if issue["stateReason"] != "NOT_PLANNED":
            return None
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
) -> list[PlanRow]:
    found: list[PlanRow] = []
    newest = {issue["number"] for issue in newest_plans(plan_issues).values()}
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
            if row is not None:
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


def gh_filing(repo: str, bot_login: str | None, run: Runner) -> FilingReader:
    """The default filing reader: plans.py's items query, and the existing items' milestones and
    parents (D-114); once the plan reads filed, how its items' issues closed (spec 097)"""
    owner, name = split_repo(repo)

    def read(issue: dict[str, Any], plan: Any) -> tuple[str, str]:
        try:
            _, filed = PLANS.plan_carriers(f"{owner}/{name}#{issue['number']}", bot_login, run)
        except PLANS.PlanError as exc:
            fail(str(exc))
        kept = {item.id for item in plan.items}  # a partial accept's plan holds its kept items alone (spec 096)
        filed = [(item, carrier) for item, carrier in filed if item.id in kept]
        unfiled = [item.id for item, carrier in filed if item.kind in FILED_KINDS and carrier is None]
        carried = [carrier for item, carrier in filed if item.kind in FILED_KINDS and carrier is not None]
        # each item's issue of this repo, in Work order: a filed item's carrier, an existing item here
        work: list[tuple[str, int]] = []
        here: list[int] = []
        for item, carrier in filed:
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
        filing=filing or gh_filing(repo, bot_login, run),
        maintainers=maintainers,
        holds=holds,
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
    limit: int | None  # [agents] outcomes; None without the key, and then nothing is counted


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


def outcomes_limit(value: object, where: Path | str) -> int:
    """[agents] outcomes, checked as src/shipmill/agents.py reads it: an integer from 1 to wip's ceiling"""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= OUTCOMES_CEILING:
        fail(f"{where}: [agents] outcomes must be an integer from 1 to {OUTCOMES_CEILING}, got {value!r}")
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


def unlimited(home: str, repo: str, reason: str) -> Product:
    """A component whose home's config can't be read: no limit, as without the key (S-101-3),
    and one note on stderr naming the failed read so it isn't silent"""
    sys.stderr.write(f"note: no [agents] outcomes limit, the home's config is unreadable: {reason}\n")
    return Product(home, (repo,), None)


def product_of(repo: str, path: Path | None, read_home: HomeReader) -> Product:
    """The product the checkout's config places repo in (spec 101). A lone repo, or one whose
    [product] says standalone, is its own product; in the product's home ([product] repos), the
    home and the repos it lists; in a component ([product] home), the limit and the repos are
    read from the home's config on its default branch, through read_home, and a component that
    sets [agents] outcomes itself is refused, naming the home. A home whose config can't be read
    (read_home raises Unreadable, or the home has none) sets no limit: the run goes on as before
    with one note on stderr (S-101-3). [product] repos is read only with a limit, so a run without
    one reads the config as before"""
    if path is None:
        return Product(repo, (repo,), None)
    product = config_values(path, "product", ("home", "standalone"))
    local = config_values(path, "agents", ("outcomes",))
    home = None if product.get("standalone") is True else product.get("home")
    if home is not None:
        if not isinstance(home, str) or not PLAIN_REPO.fullmatch(home):
            fail(f"{path}: [product] home must be owner/name, got {home!r}")
        if "outcomes" in local:
            fail(f"{path}: [agents] outcomes is the product's, set in its home {home}'s {CONFIG}, not in a component")
        where = f"{home}:{CONFIG}"
        try:
            text = read_home(home)
        except Unreadable as failed:
            return unlimited(home, repo, str(failed))
        if text is None:
            return unlimited(home, repo, f"reading the product's limit: GitHub has no {where} on its default branch")
        found = text_values(text, where, "agents", ("outcomes",))
        if "outcomes" not in found:
            return Product(home, (repo,), None)
        limit = outcomes_limit(found["outcomes"], where)
        listed = product_repos(text_values(text, where, "product", ("repos",)).get("repos", []), where)
        return Product(home, unique([repo, home, *listed]), limit)
    if "outcomes" not in local:
        return Product(repo, (repo,), None)
    limit = outcomes_limit(local["outcomes"], path)
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


def first_line(autonomy: str, outcomes: Outcomes | None) -> dict[str, Any]:
    """--json's first line: the autonomy, and with a limit the outcomes (spec 101)"""
    line: dict[str, Any] = {"autonomy": autonomy}
    if outcomes is not None:
        line["outcomes"] = outcomes.json()
    return line


def show(row: Item) -> str:
    detail = []
    if row.kind == "opportunity":
        detail.append(f"{len(row.members)} requests, +1 {row.thumbs}")
    else:
        detail.append(f"+1 {row.thumbs}")
    if row.note:
        detail.append(row.note)
    return f"#{row.number:<5} {row.state:<16} {row.title[:70]}  [{'; '.join(detail)}]"


PLACED = {"NEW_FEEDBACK", "ACCEPTED"}  # the lines the watch places (spec 074)


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
    if not args.plans and (args.wip is not None or args.role):
        parser.error("--wip and --role go with --plans")
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
    found = rows(intake)
    local_open = sum(1 for issue in intake.opportunity_issues if issue["state"] == "OPEN")
    outcomes = outcomes_in_flight(product, local_open, args.label, product_gh)
    planned: list[PlanRow] = []
    if args.plans:
        planned = fetch_plans(
            args.repo,
            intake,
            goals=uvx_goals(args.tool),
            marker=args.marker,
            bot_login=args.bot_login,
            wip=args.wip,
            room=triage_room(args.repo, args.bot_login),
            maintainers=maintainers,
            holds=gh_holds(args.repo, gh_graphql_unreadable, dt.datetime.now(UTC), stable),
        )
    if args.json:
        print(json.dumps(first_line(autonomy, outcomes)))
        for r in found:
            print(json.dumps(json_row(r), sort_keys=True))
        for p in planned:
            print(json.dumps(plan_json(p), sort_keys=True))
    else:
        print(f"intake autonomy: {autonomy}")
        if outcomes is not None:
            print(outcomes.line())
        for r in found:
            print(show(r))
        for p in planned:
            print(show_plan(p))
    actions = any(r.state in ACTION for r in found) or any(p.state in PLAN_ACTION for p in planned)
    return 1 if actions else 0


if __name__ == "__main__":
    sys.exit(main())
