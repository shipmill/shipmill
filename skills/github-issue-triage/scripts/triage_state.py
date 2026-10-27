#!/usr/bin/env python3
"""Classify a repo's issues by what triage still owes them.

Usage: triage_state.py <owner/repo> [--marker "Triage:"] [--postponed-label postponed]
                       [--stable-tag-regex REGEX] [--hold-label release-blocker]
                       [--incident-label incident] [--closed N] [--json] [--wip N]
                       [--bot-login LOGIN] [--trusted-only] [--home OWNER/NAME]
                       [--role NAME=FILLER[,FILLER...] ...] [--label LABEL ...]

For each open issue:
  NEW              no comment starts with the triage marker
  NEEDS_PR         triaged "implement", no linked PR
  IN_PROGRESS      a linked PR is open
  DONE_NOT_CLOSED  a PR that closes it merged, none open, issue still open. A merged
                   "Part of #N" PR alone doesn't count: the rest of the issue is
                   still owed, so the issue reads as its other state
  BLOCKED          labelled blocked, or a comment says it is on hold / blocked /
                   waiting on an upstream issue that is still open, or on a pull
                   request (such as a spec PR) that is still open. The hold line
                   names it as owner/repo#N or its URL anywhere in the hold
                   phrase's sentence, or as a plain #N (this repo) right after
                   "waits on", "waiting on", "depends on", "blocked by", "blocked
                   on", "decided in", or "on hold until" (a #N elsewhere on the
                   line is context). A sentence ends at ".", "!", or "?" followed
                   by a space and a capital letter (not after "e.g.", "i.e.",
                   "cf.", or "vs."), so a hold word in one sentence of a
                   paragraph doesn't hold on a link in another (#309). Or,
                   once triaged, its body has a "Depends on owner/repo#N" line (or
                   "#N", the same repo: a build issue split from a spec) naming an
                   issue still open. A Depends on line outside a ``` or ~~~ fence
                   reads the strict shape (spec 041): "Depends on[:]", references
                   (owner/repo#N, an issues or pull URL, #N, or a #{key}
                   placeholder) separated by ",", "and", or spaces, then an
                   optional note after " (", ";", or " — " that names no hold.
                   Or, once triaged, GitHub
                   records an open issue it is blocked by (blockedBy) or an open
                   sub-issue, in any repo: these and the text holds are one set,
                   so an issue named both ways is listed once. The note marks one
                   only GitHub records with (native) and a sub-issue with (child),
                   such as o/r#12:open(child), and a parent's note starts with
                   "children K/N closed". An untriaged issue reads NEW whatever its
                   body depends on and whatever GitHub records holds it
  UNFILLED         a "Depends on" line of its body still names a placeholder such
                   as #{B1} from specs.py split: put in the dependency's number
  MALFORMED_DEPENDS once triaged (or a person's item), a "Depends on" line of its body
                   names a reference outside the strict shape: it holds on every
                   reference it names, and its note is "line <n>: <the line>" for
                   each, then the holds. Read right after UNFILLED, before CYCLE,
                   SPEC_REFUSED, BLOCKED, UNBLOCKED, and HANDOFF_DUE: rewrite the line
  CYCLE            once triaged (or a person's item), it is on a cycle of the repo's open
                   issues (spec 041): each holds the next through its Depends on lines (a
                   malformed one's included), blockedBy, or sub-issues, as read here, so
                   none can start. Only issues whose holds are read count, and with
                   --trusted-only none read UNTRUSTED. Its note is "cycle <loop>", the
                   shortest loop through it from its least issue, such as "cycle o/r#3 ->
                   o/r#5 -> o/r#3", then the holds. Read right after MALFORMED_DEPENDS,
                   before SPEC_REFUSED, BLOCKED, UNBLOCKED, and HANDOFF_DUE: ask which link
                   is wrong. When another issue on its loop reads MALFORMED_DEPENDS or is
                   labelled needs-decision, it reads BLOCKED instead, its note "cycle <loop>
                   waits on owner/repo#N" naming that issue (the first on the loop), then
                   the holds: that question or line fix breaks the loop
  SPEC_REFUSED    a pull request it waits on (such as its spec PR) closed without
                   merging, and no triage comment came after the hold: decide again
                   (revise the spec in a new PR, postpone, or won't fix). A newer
                   triage comment is that decision, and the refused PR stops counting
  UNBLOCKED        every upstream issue it waits on has closed, and every pull
                   request merged: resume it. One closed as not planned shows as
                   owner/repo#N:not_planned in the note: its work never landed, so
                   decide whether the issue still makes sense before resuming
  POSTPONED        has the postponed label
  REVISIT          postponed before the newest stable tag: decide again. Stable means
                   the tag matches --stable-tag-regex (default: vX.Y.Z, no pre-release)
  TRIAGED          triaged, nothing pending (clarify, waiting on the reporter, ...). A
                   goal's plan (labelled goal-plan, spec 028) whose newest triage comment
                   is product intake's own, "Triage: **plan**", reads TRIAGED whatever the
                   rest of that comment says: the maintainer's answer moves it, not triage
  NEEDS_DECISION   labelled needs-decision and its question has no reply: a headless
                   session asked the user and left it (references/needs-decision.md).
                   The question is the newest comment whose first line is the marker
                   <!-- shipmill:needs-decision --> by an OWNER, MEMBER, or COLLABORATOR,
                   or with --bot-login the newest such comment by that login, unless an
                   OWNER, MEMBER, or COLLABORATOR wrote a newer one (then there is no
                   question); a reply is a newer comment without the marker by an OWNER,
                   MEMBER, or COLLABORATOR (other than the --bot-login). A marker comment
                   by anyone else never counts. A labelled issue with no question waits
                   too, until the label comes off
  DECIDED          labelled needs-decision and its question has a reply: act on the
                   reply and remove the label (references/needs-decision.md), after
                   which the issue reads its usual state. Read right after
                   NEEDS_DECISION, before any other state, so an answer that links an
                   open issue doesn't read BLOCKED (#309)
  VETOED           labelled decided (spec 030, a decision taken at notify) and a veto
                   came after its first decided marker, the comment whose first line is
                   <!-- shipmill:decided ... --> by the --bot-login or an OWNER, MEMBER,
                   or COLLABORATOR, with no newer <!-- shipmill:veto-handled ... -->
                   comment by such an author answering it: take the veto up
                   (references/needs-decision.md). A veto is a comment by an OWNER,
                   MEMBER, or COLLABORATOR other than the --bot-login whose first word is
                   "veto" in any case; an outsider's, or a "veto" further into a comment,
                   never counts. Read right after DECIDED, before any other state; an
                   item labelled decided without such a veto reads its usual state
  UNTRUSTED       with --trusted-only, an issue whose author is neither an OWNER,
                   MEMBER, or COLLABORATOR nor the --bot-login, whatever it would read
                   otherwise: an unattended session leaves it to an interactive one (D-16).
                   One exception (D-30): a config upgrade's issue the release workflow
                   opened, authored by the Bot github-actions[bot], labelled
                   shipmill-upgrade, and with <!-- shipmill-upgrade: <id> <version> --> as
                   its body's first line, reads as usual; any other github-actions[bot]
                   issue, or one with only the label or only the marker, is UNTRUSTED
  UPSTREAM         labelled upstream: a report of a fault another repo owns, or a stand-in
                   for another repo's work, which waits outside (spec 038). Read right
                   after UNTRUSTED, before NEEDS_DECISION, DECIDED, VETOED, and every other state,
                   triaged or not, whatever its holds. Its note is "routed by OWNER/NAME"
                   with --home OWNER/NAME (the config's [product] home), else "no
                   coordinator: waits for the maintainer", and adds "asks the maintainer"
                   when it is labelled needs-decision and its question has no reply.
                   Never an action: it starts no session
  OFF_MILESTONE    a build issue whose feature issue (its sub-issue parent, in this
                   repo) is in a milestone it isn't in (spec 022): set its milestone
                   to the parent's. Read after UNTRUSTED, UPSTREAM, NEEDS_DECISION, DECIDED, and
                   VETOED, before any other state; one already in that milestone, or whose
                   parent has none, reads its usual state

An open issue labelled human or role:<name> (label names compared case-insensitively) is a
person's item (spec 017, spec 036): its assignees do it, no PR state (IN_PROGRESS,
DONE_NOT_CLOSED) applies, and it counts as triaged from the start, so its "Depends on" lines
and GitHub's holds apply with no triage comment. Its roles are its role:<name> labels, and
human counts as role:maintainer. --role NAME=FILLER[,FILLER...], one flag per role and
maintainer among them, gives each role's fillers already resolved: GitHub logins and teams
as @<org>/<team-slug> (a malformed name or filler, an empty list, a name given twice, or no
maintainer exits 2). A role no flag gives resolves to maintainer's fillers, and several
roles to the union of theirs. After UNTRUSTED, UPSTREAM, NEEDS_DECISION, DECIDED, VETOED,
and OFF_MILESTONE, it reads NO_ASSIGNEE (without --role) or ASSIGN_DUE (with it), else
UNFILLED, MALFORMED_DEPENDS, CYCLE, SPEC_REFUSED, BLOCKED, REVISIT, or POSTPONED as any issue would, else, with every
hold closed, one of:
  NO_ASSIGNEE      without --role flags, a person's item with no assignee: read again
                   with the flags `shipmill roles --flags` prints. With them, never read
  ASSIGN_DUE       with --role flags, a person's item with no assignee whose roles
                   resolve to at least one user, read while it is still held: assign
                   them. Its note is "assign @a @b (role:infra)", plus "role:<name>
                   undefined" for each role no flag gives; with --json, its line has an
                   "assign" list of those logins. One whose roles resolve to teams only
                   reads its holds, then the states below
  HANDOFF_DUE      no hand-off came after its newest hold closed (or ever, with no
                   hold): tell its assignees, and with --role flags its roles' teams, it
                   is their turn. A hand-off is a comment whose first line is
                   <!-- shipmill:handoff -->, by an OWNER, MEMBER, or COLLABORATOR or
                   the --bot-login; a marker comment by anyone else never counts
  WITH_PERSON      a hand-off came after its newest hold closed and no done report
                   followed it: it waits on the person, however long (not an action).
                   With --json, its line has an "assignees" list of the logins it waits
                   on too, and without --role flags no other state's line has one. With
                   them, its line and HANDOFF_DUE's carry "assignees" (empty for a
                   team-only role's item) and a "teams" list of its roles' teams
  VERIFY_DUE       a done report came after the newest hand-off: run its ## Check. A
                   done report is a comment whose first line (past leading blank lines)
                   starts with "done" in any case, by one of its assignees or an OWNER,
                   MEMBER, or COLLABORATOR or the --bot-login

A parent (an open issue with a sub-issue, not a person's item; an upstream one reads
UPSTREAM) whose body has a "## Check" section (spec 042) reads, where it would read
UNBLOCKED, one of these; without the section it reads as before:
  VERIFY_DUE       no check-failed comment came after the newest close among its holds:
                   run its ## Check. Its note is the children's progress and its holds,
                   then "run its ## Check"
  CHECK_FAILED     a check-failed comment came after that close: file the fix as a new
                   child. A check-failed comment's first line is
                   <!-- shipmill:check-failed -->, by an OWNER, MEMBER, or COLLABORATOR or
                   the --bot-login; a marker comment by anyone else never counts
  WITH_PERSON      a check-waiting comment came after that close, and no check-failed or
                   verified comment after it: a person runs its ## Check by hand (#740),
                   not an action. A check-waiting comment's first line is
                   <!-- shipmill:check-waiting -->, by the same authors; it waits on the
                   first @login past that line, or on its author. Its note is "check waiting
                   on @login since <date>", then the progress and its holds; with --json, its
                   line's "assignees" is that login alone, and it has no "teams"

For the N most recently closed issues (default 20):
  SUSPECT_CLOSE    closed by a commit whose message names "#N" after a closing
                   keyword only mid-line (a quote, a test string), not as a
                   trailer, and no same-repo merged PR closes it (by GitHub's
                   link, a closing keyword in its title outside backticks, or one
                   starting a line of its body outside a code fence), or closed as
                   COMPLETED with no closer at all, unless it
                   carries --hold-label (a release hold is meant to close by hand).
                   An issue with --incident-label closed as COMPLETED with no closer
                   isn't one either: an incident closes by hand once the environment
                   is healthy, and ship-watch's POSTMORTEM_DUE follows it up. The
                   script can't read the shipmill config: pass [operate]
                   incident_label here when it isn't "incident". A person's item
                   closed as completed never reads SUSPECT_CLOSE: a person
                   closes their own item by hand. Nor does a close someone confirmed:
                   a comment after its last close whose first line is
                   <!-- shipmill:close-confirmed --> by an OWNER, MEMBER, or
                   COLLABORATOR or the --bot-login (D-29); a marker comment by anyone
                   else never counts, and a reopen and a new close re-arm it. Nor does
                   an issue labelled upstream, whoever closed it and however: the
                   product's coordinator, or the maintainer without one, closes it by
                   hand by design (spec 038)
  VERIFY_CLOSED    a person's item, closed as completed by someone other than the
                   --bot-login, with a "## Check" section and no comment after its close
                   whose first line is <!-- shipmill:verified --> by an OWNER, MEMBER, or
                   COLLABORATOR or the --bot-login: run its check. Also a parent (an
                   issue with a sub-issue, not a person's item, not labelled upstream)
                   closed as completed with a "## Check" section, by a pull request, a
                   commit, or the --bot-login, with no such verified comment after its
                   last close (spec 042): never SUSPECT_CLOSE. One a person closed by
                   hand reads as any issue does

For each closed issue labelled decided and updated in the last 14 days (a veto comment
updates it), read in the first query and paged past 50:
  VETOED           it holds an unanswered trusted veto, as an open issue's VETOED reads it;
                   its line carries "closed": true (with --json). Such an issue reads
                   nothing else, SUSPECT_CLOSE and VERIFY_CLOSED included, and one without
                   such a veto reports nothing here

With --json, an open direction issue's line (spec 034: labelled shipmill-direction, the
marker <!-- shipmill-direction --> as its body's first line, opened by an OWNER, MEMBER, or
COLLABORATOR or the --bot-login) carries "direction": true, whatever its state, so
github-ship-watch keeps it out of its issue rows without reading it again.

With --label LABEL (repeatable), only the open issues carrying any of the labels are read
and classified, the recently closed ones as without it: shipmill gate's tier 4 reads the
items labelled needs-decision or decided this way (spec 046).

With --wip N (a work-in-progress limit, such as the config's [agents] wip), a last
line says how many issues are IN_PROGRESS (counting an OFF_MILESTONE one with an open
PR), the room left under N, and the issues
ready to start (NEEDS_PR or UNBLOCKED), oldest first; with --json, as one JSON object.
A person's item never counts as in progress or ready: the limit is on agents' work.

--bot-login names the login shipmill's sessions write as (an App's <slug>[bot]). --home
names the product's home repo, the config's [product] home, as owner/name (letters, digits,
".", "-", or "_" on each side; anything else exits 2); it only words UPSTREAM's note.

Exit 0 when nothing needs action, 1 when any issue is NEW, NEEDS_PR, UNBLOCKED, UNFILLED,
MALFORMED_DEPENDS, CYCLE, SPEC_REFUSED, REVISIT, DONE_NOT_CLOSED, DECIDED, VETOED, SUSPECT_CLOSE, HANDOFF_DUE,
VERIFY_DUE, NO_ASSIGNEE, ASSIGN_DUE, VERIFY_CLOSED, or OFF_MILESTONE (never for NEEDS_DECISION, UNTRUSTED, UPSTREAM, or
WITH_PERSON),
1 too when any is CHECK_FAILED (spec 042), 2 on bad input (an issue with more than 100
labels) or a gh failure. It pages past 100 open issues and an issue's 50 comments, 50
cross-references, 50 blocking issues, or 50 sub-issues, and back through tags to the
newest stable one, with one query when nothing is capped. A page GitHub rejects for its
resource limits is asked again at half the size, down to 10 items; one rejected at 10
fails with one error line. When GitHub's schema has no blockedBy, subIssues, or parent (an
undefinedField error naming one, such as a GitHub Enterprise Server without issue
dependencies), it classifies on the text holds alone, with no OFF_MILESTONE, and prints one "note: native
relations unavailable: <first error line>" line to stderr; any other gh error, an error
on one issue's relations too, still exits 2. Needs the gh
CLI, authenticated. Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Any, NoReturn

OPEN_TIMELINE = """
          nodes {
            ... on CrossReferencedEvent {
              willCloseTarget isCrossRepository
              source { ... on PullRequest { number state title body } }
            }
            ... on ConnectedEvent { subject { ... on PullRequest { number state } } }
          }
"""
CLOSED_REFS = """
          nodes {
            ... on CrossReferencedEvent {
              willCloseTarget isCrossRepository
              source { ... on PullRequest { number state title body } }
            }
          }
"""
# Who wrote it: GraphQL gives a Bot's login without the "[bot]" that REST and --bot-login carry
AUTHOR = "author { __typename login } authorAssociation"
COMMENT = "body createdAt " + AUTHOR
TAG_NODES = "nodes { name target { ... on Tag { tagger { date } } ... on Commit { committedDate } } }"
# The forge's own holds on an issue (spec 017): the issues it is blocked by, and its
# sub-issues, each with its repository, so a relation across repos holds as well
NATIVE_FIELDS = ("blockedBy", "subIssues")
NATIVE_NODES = (
    "pageInfo { hasNextPage endCursor } nodes { number state stateReason closedAt repository { nameWithOwner } }"
)
NATIVE = "".join(f"\n        {field}(first: 50) {{ {NATIVE_NODES} }}" for field in NATIVE_FIELDS)
# A build issue's feature issue is its sub-issue parent, whose milestone it should share
# (spec 022): one field of the same query, never a call per issue
PARENT = "\n        parent { number repository { nameWithOwner } milestone { title } }"
# The fields only a forge with sub-issues and dependencies has: refusing one falls back
NATIVE_SCHEMA = (*NATIVE_FIELDS, "parent")
# A decision taken at notify carries this label (spec 030); a veto comment updates the item, so
# a closed one is read back over VETO_WINDOW, in the first query, never with a call per issue
DECIDED_LABEL = "decided"
VETO_WINDOW = dt.timedelta(days=14)
UTC = dt.timezone.utc  # noqa: UP017 (dt.UTC needs 3.11)
VETOABLE_FIRST = 50  # the first query's page of them; more are paged with VETOABLE_PAGE
VETOABLE_NODES = (
    "pageInfo { hasNextPage endCursor } nodes { number title comments(last: 50) { nodes { " + COMMENT + " } } }"
)


def vetoable(size: str, cursor: str = "") -> str:
    """The closed issues labelled decided and updated since $since, newest first"""
    return (
        f'vetoable: issues(states: CLOSED, labels: ["{DECIDED_LABEL}"], first: {size}{cursor},'
        " filterBy: {since: $since}, orderBy: {field: UPDATED_AT, direction: DESC}) { " + VETOABLE_NODES + " }"
    )


def open_issue_fields(native: bool) -> str:
    """An open issue's fields; without ``native``, the text holds' only, for a forge or
    token that can't read blockedBy or subIssues"""
    return (
        """
      nodes {
        number title body """
        + AUTHOR
        + """
        milestone { title }
        labels(first: 100) { pageInfo { hasNextPage } nodes { name } }
        assignees(first: 10) { nodes { login } }
        comments(last: 50) { nodes { """
        + COMMENT
        + """ } }
        timelineItems(itemTypes: [CROSS_REFERENCED_EVENT, CONNECTED_EVENT], first: 50) {
          pageInfo { hasNextPage endCursor }"""
        + OPEN_TIMELINE
        + """
        }"""
        + (NATIVE + PARENT if native else "")
        + """
      }
"""
    )


def label_filter(labels: Sequence[str]) -> str:
    """The open issues' filter by --label (spec 046): those carrying any of the labels; none
    without one. Each label is a JSON string, so a quote in one can't end the query's"""
    return f", labels: [{', '.join(json.dumps(label) for label in labels)}]" if labels else ""


def first_query(native: bool, labels: Sequence[str] = ()) -> str:
    return (
        """
query($owner: String!, $name: String!, $size: Int!, $closed: Int!, $since: DateTime!) {
  repository(owner: $owner, name: $name) {
    open: issues(states: OPEN"""
        + label_filter(labels)
        + """, first: $size, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }"""
        + open_issue_fields(native)
        + (CLOSED_AND_TAGS.replace(CLOSED_FIELDS, CLOSED_FIELDS + CLOSED_NATIVE, 1) if native else CLOSED_AND_TAGS)
    )


def open_page(native: bool, labels: Sequence[str] = ()) -> str:
    return (
        """
query($owner: String!, $name: String!, $size: Int!, $cursor: String!) {
  repository(owner: $owner, name: $name) {
    open: issues(states: OPEN"""
        + label_filter(labels)
        + """, first: $size, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }"""
        + open_issue_fields(native)
        + """
    }
  }
}
"""
    )


def native_page(field: str) -> str:
    """The next page of an issue's blockedBy or subIssues"""
    return (
        """
query($owner: String!, $name: String!, $size: Int!, $number: Int!, $cursor: String!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      """
        + field
        + "(first: $size, after: $cursor) { "
        + NATIVE_NODES
        + """ }
    }
  }
}
"""
    )


# Whether a closed issue has sub-issues, which makes it a parent whose ## Check a close may
# owe (spec 042): a native field, so the native first query alone asks for it
CLOSED_FIELDS = "number title stateReason body"
CLOSED_NATIVE = " subIssues(first: 1) { totalCount }"
CLOSED_AND_TAGS = (
    """
    }
    tags: refs(refPrefix: "refs/tags/", last: 50, orderBy: {field: TAG_COMMIT_DATE, direction: ASC}) {
      pageInfo { hasPreviousPage startCursor }
      """
    + TAG_NODES
    + """
    }
    closed: issues(states: CLOSED, first: $closed, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number title stateReason body
        labels(first: 100) { pageInfo { hasNextPage } nodes { name } }
        comments(last: 5) { nodes { """
    + COMMENT
    + """ } }
        refs: timelineItems(itemTypes: [CROSS_REFERENCED_EVENT], first: 50) {
          pageInfo { hasNextPage endCursor }"""
    + CLOSED_REFS
    + """
        }
        timelineItems(itemTypes: [CLOSED_EVENT], last: 1) {
          nodes {
            ... on ClosedEvent {
              createdAt
              actor { __typename login }
              closer {
                __typename
                ... on PullRequest { number merged }
                ... on Commit { abbreviatedOid message }
              }
            }
          }
        }
      }
    }
    """
    + vetoable(str(VETOABLE_FIRST))
    + """
  }
}
"""
)
QUERY = first_query(native=True)
TEXT_QUERY = first_query(native=False)  # once the forge refused blockedBy or subIssues

# Follow-up queries, each run only for a connection that an earlier page reports as capped
# (comments: one that filled its page). Every query takes its page size as $size, which
# halves when GitHub rejects the page for its resource limits (see SIZES and sized)
OPEN_PAGE = open_page(native=True)
TEXT_OPEN_PAGE = open_page(native=False)
NATIVE_PAGES = {field: native_page(field) for field in NATIVE_FIELDS}
COMMENTS_PAGE = (
    """
query($owner: String!, $name: String!, $size: Int!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      comments(last: $size, before: $cursor) { pageInfo { hasPreviousPage startCursor } nodes { """
    + COMMENT
    + """ } }
    }
  }
}
"""
)
TIMELINE_PAGE = (
    """
query($owner: String!, $name: String!, $size: Int!, $number: Int!, $cursor: String!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      timelineItems(itemTypes: [CROSS_REFERENCED_EVENT, CONNECTED_EVENT], first: $size, after: $cursor) {
        pageInfo { hasNextPage endCursor }"""
    + OPEN_TIMELINE
    + """
      }
    }
  }
}
"""
)
REFS_PAGE = (
    """
query($owner: String!, $name: String!, $size: Int!, $number: Int!, $cursor: String!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      refs: timelineItems(itemTypes: [CROSS_REFERENCED_EVENT], first: $size, after: $cursor) {
        pageInfo { hasNextPage endCursor }"""
    + CLOSED_REFS
    + """
      }
    }
  }
}
"""
)
VETOABLE_PAGE = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String!, $since: DateTime!) {
  repository(owner: $owner, name: $name) {
    """
    + vetoable("$size", ", after: $cursor")
    + """
  }
}
"""
)
TAGS_PAGE = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String!) {
  repository(owner: $owner, name: $name) {
    tags: refs(refPrefix: "refs/tags/", last: $size, before: $cursor,
               orderBy: {field: TAG_COMMIT_DATE, direction: ASC}) {
      pageInfo { hasPreviousPage startCursor }
      """
    + TAG_NODES
    + """
    }
  }
}
"""
)

COMMENTS_CAP = 50  # comments(last: 50) in OPEN_ISSUE
CLOSED_COMMENTS_CAP = 5  # comments(last: 5) of a closed issue in CLOSED_AND_TAGS
# Each query's first page size, and what a page holds, for the error line. Older open
# issues carry more history: a page of 100 tripped GitHub's resource limits on
# astral-sh/uv, so later open-issue pages start at 50
SIZES = {
    QUERY: 100,
    TEXT_QUERY: 100,
    OPEN_PAGE: 50,
    TEXT_OPEN_PAGE: 50,
    COMMENTS_PAGE: 100,
    TIMELINE_PAGE: 100,
    REFS_PAGE: 100,
    TAGS_PAGE: 100,
    VETOABLE_PAGE: VETOABLE_FIRST,
    **{query: 100 for query in NATIVE_PAGES.values()},
}
# A rejected page halves down to this floor; one that fails at the floor ends the run.
# At 10 open issues a page asks for a tenth of the first query, so a page still rejected
# there holds an issue too heavy for any size, and pypa/pip's 957 issues would already
# take some 100 calls of about 5 seconds each
MIN_PAGE = 10
RESOURCE_LIMITS = "RESOURCE_LIMITS_EXCEEDED"
Variables = dict[str, str | int]
# Runs one GraphQL query with its variables and returns the parsed JSON response
Runner = Callable[[str, Variables], dict[str, Any]]
Sizes = dict[str, int]


class ResourceLimitsExceeded(Exception):
    """GitHub rejected a query as too costly to run; a smaller page may fit"""


def resource_limited(response: dict[str, Any]) -> bool:
    """Every error is GitHub's resource limit (gh prints one per rejected node), so a
    smaller page may succeed; any other error is real"""
    errors = response.get("errors")
    return bool(errors) and all(isinstance(e, dict) and e.get("type") == RESOURCE_LIMITS for e in errors)


class NativeUnavailable(Exception):
    """The forge has no blockedBy or subIssues: classify on text holds alone"""


NATIVE_NAME = re.compile(r"\b(?:" + "|".join(NATIVE_SCHEMA) + r")\b")
UNDEFINED = re.compile(r"doesn't exist on type|isn't a defined input type")


def names_native(error: object) -> bool:
    """Whether a GraphQL error is the schema refusing blockedBy or subIssues: an
    undefinedField naming one, or a message saying one "doesn't exist on type". An error on
    one issue's relations (a blocker the token can't read) is not: falling back then would
    read an issue held only natively as ready, so it fails like any other error"""
    if not isinstance(error, dict):
        return False
    extensions = error.get("extensions")
    message = str(error.get("message", ""))
    if isinstance(extensions, dict) and extensions.get("code") == "undefinedField":
        return extensions.get("fieldName") in NATIVE_SCHEMA or NATIVE_NAME.search(message) is not None
    return UNDEFINED.search(message) is not None and NATIVE_NAME.search(message) is not None


def native_refused(response: dict[str, Any]) -> str | None:
    """The first error's first line when every error is the schema refusing blockedBy or
    subIssues (a GitHub Enterprise Server without issue dependencies); None for any other
    response, whose errors are real"""
    errors = response.get("errors")
    if not errors or not isinstance(errors, list) or not all(names_native(e) for e in errors):
        return None
    lines = str(errors[0].get("message", "")).strip().splitlines()
    return lines[0] if lines else json.dumps(errors[0])


INCIDENT_LABEL = "incident"  # the default of [operate] incident_label
DECISION_LABEL = "needs-decision"  # references/needs-decision.md
DECISION_MARKER = "<!-- shipmill:needs-decision -->"  # the first line of a session's question
# Spec 030's notify level: a decided comment's first line, `<!-- shipmill:decided zone=<id>
# until=<time> -->`, and the take-up of a veto's, `<!-- shipmill:veto-handled zone=<id> -->`
DECIDED_MARKER = re.compile(r"^<!-- shipmill:decided(?:\s[^>]*)?-->$")
VETO_HANDLED_MARKER = re.compile(r"^<!-- shipmill:veto-handled(?:\s[^>]*)?-->$")
VETO = re.compile(r"veto\b", re.IGNORECASE)  # a veto's first word, in any case
# A report of a fault another repo owns, or a stand-in for another repo's work (spec 038): it
# waits outside, for the product's coordinator or, without one, the maintainer
UPSTREAM_LABEL = "upstream"
# An owner or a repo name: the characters GitHub allows, shipmill's app._SEGMENT
SEGMENT = re.compile(r"[A-Za-z0-9._-]+")
# The author associations whose comment answers a question, and whose issue an unattended
# session works on (D-16); CONTRIBUTOR, FIRST_TIMER, NONE, and the rest never count
TRUSTED = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
# A config upgrade's issue (spec 014), as the release workflow opens it: shipmill's
# github.UPGRADE_LABEL, and its first line, shipmill's upgrades.marker (the id and version)
UPGRADE_LABEL = "shipmill-upgrade"
UPGRADE_MARKER = re.compile(r"^<!-- shipmill-upgrade: ([a-z][a-z0-9]*(?:-[a-z0-9]+)*) (\S+) -->\s*$")
WORKFLOW_BOT = "github-actions[bot]"  # who the release workflow writes as
# shipmill's question for a repo's missing direction (spec 034): the label, and the marker
# that is its body's first line; github-ship-watch asks it, so triage posts no verdict on it
DIRECTION_LABEL = "shipmill-direction"
DIRECTION_MARKER = "<!-- shipmill-direction -->"
# A goal's plan (spec 028): product-intake's intake_state.py PLAN_LABEL, and the verdict its
# triage comment on a plan starts with, "Triage: **plan**. ..."
PLAN_LABEL = "goal-plan"
PLAN_VERDICT = "**plan**"
# A person's item (spec 017): its assignees do it, a hand-off comment tells them it is
# their turn, and a verified comment records that a session checked a close by hand
HUMAN_LABEL = "human"
# A role's item (spec 036): labelled role:<name>, a person's item exactly as a human one,
# which counts as role:maintainer. --role NAME=FILLER,... gives each role's fillers, already
# resolved: a role name, a GitHub user login, or a team as @<org>/<team-slug>
ROLE_PREFIX = "role:"
MAINTAINER = "maintainer"
ROLE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,44}")
LOGIN_PATTERN = r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}"
USER = re.compile(LOGIN_PATTERN)
TEAM = re.compile(r"@" + LOGIN_PATTERN + r"/[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
HANDOFF_MARKER = "<!-- shipmill:handoff -->"
VERIFIED_MARKER = "<!-- shipmill:verified -->"
# A trusted comment after a close saying it was right: SUSPECT_CLOSE stops reading it (D-29)
CLOSE_CONFIRMED_MARKER = "<!-- shipmill:close-confirmed -->"
# A trusted comment saying a parent's ## Check failed: it reads CHECK_FAILED until a hold closes after it (spec 042)
CHECK_FAILED_MARKER = "<!-- shipmill:check-failed -->"
# A trusted comment saying a person runs a parent's ## Check by hand, on the needs-decision answer
# "leave it open" (#740): it reads WITH_PERSON until a hold closes or a check-failed or verified comment follows
CHECK_WAITING_MARKER = "<!-- shipmill:check-waiting -->"
MENTION = re.compile(r"(?<![\w@/-])@(" + LOGIN_PATTERN + r")(?![\w/-])")  # an @login, not an @org/team
CHECK = re.compile(r"^[ \t]*##[ \t]+Check[ \t]*$", re.MULTILINE)  # how a person's result is checked
ACTION = {
    "NEW",
    "NEEDS_PR",
    "UNBLOCKED",
    "UNFILLED",
    "MALFORMED_DEPENDS",
    "CYCLE",
    "SPEC_REFUSED",
    "REVISIT",
    "DONE_NOT_CLOSED",
    "DECIDED",
    "VETOED",
    "SUSPECT_CLOSE",
    "HANDOFF_DUE",
    "VERIFY_DUE",
    "CHECK_FAILED",
    "NO_ASSIGNEE",
    "ASSIGN_DUE",
    "VERIFY_CLOSED",
    "OFF_MILESTONE",
}
CLOSED_STATES = ("CLOSED", "NOT_PLANNED", "MERGED")  # a hold in one of these holds nothing
HOLD = re.compile(r"\b(?:on hold|blocked|waits? on|waiting on|pending|depends on)\b", re.IGNORECASE)
# Where a sentence of a comment line ends: a hold phrase holds only on the links of its own
# sentence, so "a command whose run length depends on its input" in one sentence of a
# paragraph doesn't hold on an issue another sentence of it names (#309). "e.g. #5" and
# "github.com" don't end one: a sentence ends only before a capital letter, and never after
# "e.g.", "i.e.", "cf.", or "vs.", which a capitalised owner ("e.g. PyCQA/flake8#5") follows
SENTENCE = re.compile(r"(?<!\b[eE]\.g\.)(?<!\b[iI]\.e\.)(?<!\b[cC]f\.)(?<!\b[vV]s\.)(?<=[.!?])\s+(?=[A-Z])")
UPSTREAM = re.compile(r"(?:https://github\.com/)?(?P<owner>[\w.-]+)/(?P<name>[\w.-]+)(?:#|/issues/|/pull/)(?P<num>\d+)")
# A plain #N right after a hold phrase names the issue or pull request of the repo itself
# that the hold waits on; a #N elsewhere on the line ("#59 stays open") is only context
SAME_REPO = re.compile(
    r"\b(?:waits? on|waiting on|depends on|blocked (?:by|on)|decided in|on hold until)[ \t]+#(?P<num>\d+)\b",
    re.IGNORECASE,
)
# A "Depends on" line of an issue body (a build issue split from a spec), outside a code fence,
# and the issues it names: owner/repo#N, a URL, or a plain #N for the same repo
DEPENDS = re.compile(r"^[ \t]*(?:[-*][ \t]+)?depends on\b:?(?P<refs>.*)$", re.IGNORECASE | re.MULTILINE)
DEPENDENCY = re.compile(
    r"(?:(?:https://github\.com/)?(?P<owner>[\w.-]+)/(?P<name>[\w.-]+)(?:#|/issues/|/pull/)|(?<![\w/])#)(?P<num>\d+)\b"
)
# A dependency specs.py split names by key until the issue is filed: #{B1}, o/r#{B1}
PLACEHOLDER = re.compile(r"#\{(?P<key>[^{}\s]*)\}")
# The strict shape of a Depends on line past "Depends on[:]" (spec 041): references separated
# by any mix of ",", "and", and whitespace, then a note after " (", ";", or " — " that is
# never read for references. A line naming a reference in any other shape is malformed.
# The separator takes one blank at a time: "(?:[ \t]+|...)+" backtracks exponentially on a
# run of blanks before a character that doesn't fit, and every gate tick reads every body
STRICT_REF = r"(?:https://github\.com/[\w.-]+/[\w.-]+/(?:issues|pull)/\d+|(?:[\w.-]+/[\w.-]+)?#(?:\d+|\{[^{}\s]*\}))"
STRICT_DEPENDS = re.compile(
    rf"[ \t]*(?P<refs>{STRICT_REF}(?:(?:[ \t]|,|\band\b)+{STRICT_REF})*)(?:(?:[ \t]+\(|[ \t]*;|[ \t]+—[ \t]).*)?[ \t]*"
)
STABLE = re.compile(r"^v?\d+\.\d+\.\d+$")
KEYWORDS = r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)"
# A PR's closing keyword, the one rule github-pr-triage's shipped.py reads too (#368, #416):
# in the title outside code spans, or starting a body line (after a list bullet) outside a fence
LINE_CLOSER = re.compile(rf"^\s*(?:[-*]\s*)?{KEYWORDS}:?\s+#(\d+)\b", re.IGNORECASE)
TITLE_CLOSER = re.compile(rf"\b{KEYWORDS}:?\s+#(\d+)\b", re.IGNORECASE)
CODE_SPAN = re.compile(r"`+[^`]*`+")
FENCE = re.compile(r"^[ \t]*(?:```|~~~)")


def gh_graphql(query: str, variables: Variables) -> dict[str, Any]:
    """The default runner: one ``gh api graphql`` call"""
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        # -F sends an int as a number; -f keeps a string a string (a cursor, a numeric repo name)
        cmd += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        # gh exits 1 on a resource limit, with the response on stdout and its message once
        # per rejected node on stderr: hand the response back to be retried smaller. It
        # exits 1 too on a schema without blockedBy or subIssues: hand that back to be
        # asked again without them
        try:
            rejected = json.loads(proc.stdout)
        except ValueError:
            rejected = None
        if isinstance(rejected, dict) and (resource_limited(rejected) or native_refused(rejected) is not None):
            return rejected
        sys.stderr.write(proc.stderr)
        raise SystemExit(2)
    response: dict[str, Any] = json.loads(proc.stdout)
    return response


def fail(message: str) -> NoReturn:
    sys.stderr.write(f"error: {message}\n")
    raise SystemExit(2)


def repository(run: Runner, query: str, variables: Variables) -> dict[str, Any]:
    response = run(query, variables)
    if resource_limited(response):
        raise ResourceLimitsExceeded
    refused = native_refused(response)
    if refused is not None:
        raise NativeUnavailable(refused)
    if response.get("errors"):
        fail(f"GitHub GraphQL errors: {json.dumps(response['errors'])}")
    data = (response.get("data") or {}).get("repository")
    if data is None:
        fail(f"no repository {variables['owner']}/{variables['name']} in the GraphQL response")
    result: dict[str, Any] = data
    return result


def advance(cursor: str | None, seen: set[str], what: str) -> str:
    """The next page's cursor; a missing or repeated one would page forever"""
    if not cursor or cursor in seen:
        fail(f"GitHub reported more {what}, but the page cursor did not advance ({cursor!r})")
    seen.add(cursor)
    return cursor


def sized(run: Runner, query: str, variables: Variables, sizes: Sizes, what: str) -> dict[str, Any]:
    """``repository`` at the query's page size, halving it while GitHub rejects the page for
    its resource limits. The smaller size sticks for the query's later pages, and a cursor
    from a bigger page stays valid. A page rejected at MIN_PAGE fails with one line"""
    while True:
        size = sizes[query]
        try:
            return repository(run, query, {**variables, "size": size})
        except ResourceLimitsExceeded:
            if size <= MIN_PAGE:
                fail(
                    f"{variables['owner']}/{variables['name']}: GitHub's resource limits rejected "
                    f"{what} even at {size} per page"
                )
            sizes[query] = max(size // 2, MIN_PAGE)


def issue_page(
    run: Runner, query: str, base: Variables, sizes: Sizes, number: int, field: str, cursor: str | None
) -> dict[str, Any]:
    """One page of an issue's connection; with no cursor, its first page (for comments, the newest)"""
    variables: Variables = {**base, "number": number}
    if cursor is not None:
        variables["cursor"] = cursor
    what = {
        "comments": "comments",
        "timelineItems": "cross-references",
        "refs": "cross-references",
        "blockedBy": "blocking issues",
        "subIssues": "sub-issues",
    }[field]
    issue = sized(run, query, variables, sizes, f"the {what} of #{number}").get("issue")
    if issue is None:
        fail(f"issue #{number} vanished while paging its {field}")
    page: dict[str, Any] = issue[field]
    return page


def check_labels(issue: dict[str, Any]) -> None:
    if issue["labels"]["pageInfo"]["hasNextPage"]:
        fail(f"bad input: issue #{issue['number']} has more than 100 labels, which triage_state.py does not page")


def complete_comments(run: Runner, base: Variables, sizes: Sizes, issue: dict[str, Any]) -> None:
    """Page an issue's comments backwards, keeping them oldest first. pageInfo on the first
    query's comments trips GitHub's resource limits on a busy repo, so a full first page
    (COMMENTS_CAP) is read again here with it"""
    if len(issue["comments"]["nodes"]) < COMMENTS_CAP:
        return
    comments = issue_page(run, COMMENTS_PAGE, base, sizes, issue["number"], "comments", None)
    issue["comments"] = comments
    seen: set[str] = set()
    while comments["pageInfo"]["hasPreviousPage"]:
        cursor = advance(comments["pageInfo"]["startCursor"], seen, f"comments on #{issue['number']}")
        page = issue_page(run, COMMENTS_PAGE, base, sizes, issue["number"], "comments", cursor)
        comments["nodes"] = page["nodes"] + comments["nodes"]
        comments["pageInfo"] = page["pageInfo"]


def complete_refs(run: Runner, query: str, base: Variables, sizes: Sizes, issue: dict[str, Any], field: str) -> None:
    """Page an issue's cross-references (or blockedBy, or subIssues) forwards, oldest first"""
    items = issue[field]
    seen: set[str] = set()
    while items["pageInfo"]["hasNextPage"]:
        what = field if field in NATIVE_FIELDS else "cross-references"
        cursor = advance(items["pageInfo"]["endCursor"], seen, f"{what} on #{issue['number']}")
        page = issue_page(run, query, base, sizes, issue["number"], field, cursor)
        items["nodes"] = items["nodes"] + page["nodes"]
        items["pageInfo"] = page["pageInfo"]


# Each role's fillers, from the --role flags: (user logins, @org/team entries)
Roles = dict[str, tuple[tuple[str, ...], tuple[str, ...]]]


def item_roles(issue: dict[str, Any]) -> list[str]:
    """The roles of a person's item, label names compared case-insensitively (spec 036): its
    role:<name> labels' names, with human counting as role:maintainer, in label order; empty
    for an issue that is no person's item"""
    found: list[str] = []
    for node in issue["labels"]["nodes"]:
        name = str(node["name"]).lower()
        if name == HUMAN_LABEL:
            role = MAINTAINER
        elif name.startswith(ROLE_PREFIX):
            role = name[len(ROLE_PREFIX) :]
        else:
            continue
        if role not in found:
            found.append(role)
    return found


def person_item(issue: dict[str, Any]) -> bool:
    """A person's item: labelled human or role:<name> (spec 017, spec 036)"""
    return bool(item_roles(issue))


def unique(names: list[str]) -> tuple[str, ...]:
    """The names in order, each once; GitHub logins and team slugs ignore case"""
    seen: dict[str, str] = {}
    for name in names:
        seen.setdefault(name.lower(), name)
    return tuple(seen.values())


def resolve(issue: dict[str, Any], roles: Roles) -> tuple[tuple[str, ...], tuple[str, ...], list[str]]:
    """A person's item's roles resolved through the --role flags: the union of their users,
    of their teams, and the roles no flag gives, which resolve to the maintainer's fillers"""
    users: list[str] = []
    teams: list[str] = []
    undefined: list[str] = []
    for role in item_roles(issue):
        if role not in roles:
            undefined.append(role)
        given_users, given_teams = roles.get(role, roles[MAINTAINER])
        users += given_users
        teams += given_teams
    return unique(users), unique(teams), undefined


def parse_roles(values: list[str]) -> Roles:
    """The --role NAME=FILLER[,FILLER...] flags, one per role, which must include maintainer;
    ValueError names what is wrong"""
    roles: Roles = {}
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
        users: list[str] = []
        teams: list[str] = []
        for filler in fillers.split(","):
            if USER.fullmatch(filler):
                users.append(filler)
            elif TEAM.fullmatch(filler):
                teams.append(filler)
            else:
                raise ValueError(f"--role {name}: {filler!r} is neither a GitHub login nor @org/team")
        roles[name] = (unique(users), unique(teams))
    if MAINTAINER not in roles:
        raise ValueError(f"--role flags must include {MAINTAINER}=FILLER[,FILLER...]")
    return roles


def checkable(issue: dict[str, Any]) -> bool:
    """A closed person's item whose close a session may owe a check (VERIFY_CLOSED): labelled
    human or role:<name>, closed as completed, with a ## Check section"""
    return (
        person_item(issue) and issue["stateReason"] == "COMPLETED" and CHECK.search(issue.get("body") or "") is not None
    )


def parent_checkable(issue: dict[str, Any]) -> bool:
    """A closed parent whose close may owe its check (spec 042): it has a sub-issue (only the
    native query asks), is no person's item and no upstream report, closed as completed, with
    a ## Check section"""
    labels = {n["name"] for n in issue["labels"]["nodes"]}
    return (
        (issue.get("subIssues") or {}).get("totalCount", 0) > 0
        and not person_item(issue)
        and UPSTREAM_LABEL not in labels
        and issue["stateReason"] == "COMPLETED"
        and CHECK.search(issue.get("body") or "") is not None
    )


def closed_at(issue: dict[str, Any]) -> dt.datetime:
    """When a closed issue last closed; one without a close event can't be checked"""
    events = issue["timelineItems"]["nodes"]
    moment = events[0].get("createdAt") if events else None
    if not moment:
        fail(f"closed issue #{issue['number']} has no close event to check its close against")
    return timestamp(moment)


def comments_since_close(run: Runner, base: Variables, sizes: Sizes, issue: dict[str, Any]) -> None:
    """A closed issue's comments, oldest first, back to its close: the first query asks a
    closed issue for its last few comments only, and the ones after its close tell whether
    a session verified it or someone confirmed it"""
    since = closed_at(issue)
    comments = issue_page(run, COMMENTS_PAGE, base, sizes, issue["number"], "comments", None)
    seen: set[str] = set()
    while (
        comments["pageInfo"]["hasPreviousPage"]
        and comments["nodes"]
        and timestamp(comments["nodes"][0]["createdAt"]) > since
    ):
        cursor = advance(comments["pageInfo"]["startCursor"], seen, f"comments on #{issue['number']}")
        page = issue_page(run, COMMENTS_PAGE, base, sizes, issue["number"], "comments", cursor)
        comments["nodes"] = page["nodes"] + comments["nodes"]
        comments["pageInfo"] = page["pageInfo"]
    issue["comments"] = comments


def complete_closed_comments(run: Runner, base: Variables, sizes: Sizes, issue: dict[str, Any]) -> None:
    """Every comment after a closed issue's last close: a person's item may owe a check,
    and any close may have been confirmed. The first query's last few comments are enough
    unless they fill the page and all came after the close"""
    if checkable(issue) or parent_checkable(issue):
        comments_since_close(run, base, sizes, issue)
        return
    nodes = issue["comments"]["nodes"]
    events = issue["timelineItems"]["nodes"]
    if (
        len(nodes) >= CLOSED_COMMENTS_CAP
        and events
        and events[0].get("createdAt")
        and timestamp(nodes[0]["createdAt"]) > closed_at(issue)
    ):
        comments_since_close(run, base, sizes, issue)


def fetch(
    repo: str,
    closed: int,
    stable_pattern: re.Pattern[str] = STABLE,
    run: Runner = gh_graphql,
    now: dt.datetime | None = None,
    labels: Sequence[str] = (),
) -> dict[str, Any]:
    """One query, plus follow-up pages only for the connections it reports as capped. When
    the forge refuses blockedBy or subIssues, one stderr note, then the text holds alone.
    ``now`` (default: the clock) dates the window of closed decided issues it reads back;
    ``labels`` (--label, spec 046) narrows the open issues to those carrying any of them"""
    owner, _, name = repo.partition("/")
    if not owner or not name or "/" in name:
        fail(f"repo must be owner/name, got {repo!r}")
    moment = now if now is not None else dt.datetime.now(UTC)
    since = (moment - VETO_WINDOW).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        return fetch_pages(owner, name, closed, stable_pattern, run, native=True, since=since, labels=labels)
    except NativeUnavailable as refused:
        sys.stderr.write(f"note: native relations unavailable: {refused}\n")
    return fetch_pages(owner, name, closed, stable_pattern, run, native=False, since=since, labels=labels)


def fetch_pages(
    owner: str,
    name: str,
    closed: int,
    stable_pattern: re.Pattern[str],
    run: Runner,
    native: bool,
    since: str,
    labels: Sequence[str] = (),
) -> dict[str, Any]:
    base: Variables = {"owner": owner, "name": name}
    sizes = dict(SIZES)
    first, later = (QUERY, OPEN_PAGE) if native else (TEXT_QUERY, TEXT_OPEN_PAGE)
    if labels:  # the same queries narrowed, at their page sizes
        sizes[first_query(native, labels)], sizes[open_page(native, labels)] = sizes[first], sizes[later]
        first, later = first_query(native, labels), open_page(native, labels)
    what = "the first query (open issues, tags, recent closes)"
    data = sized(run, first, {**base, "closed": closed, "since": since}, sizes, what)

    issues = data["open"]
    # A first query that had to shrink says how heavy this repo's issues are
    sizes[later] = min(sizes[later], sizes[first])
    seen: set[str] = set()
    while issues["pageInfo"]["hasNextPage"]:
        cursor = advance(issues["pageInfo"]["endCursor"], seen, "open issues")
        what = f"the open issues after the first {len(issues['nodes'])}"
        page = sized(run, later, {**base, "cursor": cursor}, sizes, what)["open"]
        issues["nodes"] = issues["nodes"] + page["nodes"]
        issues["pageInfo"] = page["pageInfo"]
    for issue in issues["nodes"]:
        check_labels(issue)
        complete_comments(run, base, sizes, issue)
        complete_refs(run, TIMELINE_PAGE, base, sizes, issue, "timelineItems")
        for field, query in NATIVE_PAGES.items():
            if issue.get(field) is not None:  # absent when the query didn't ask for it
                complete_refs(run, query, base, sizes, issue, field)
    for issue in data["closed"]["nodes"]:
        check_labels(issue)
        complete_refs(run, REFS_PAGE, base, sizes, issue, "refs")
        complete_closed_comments(run, base, sizes, issue)
    # The closed issues labelled decided in the veto window: every comment, since a veto
    # counts only after the decided marker, however far back that is
    decided = data["vetoable"]
    seen = set()
    while decided["pageInfo"]["hasNextPage"]:
        cursor = advance(decided["pageInfo"]["endCursor"], seen, "closed decided issues")
        variables: Variables = {**base, "cursor": cursor, "since": since}
        page = sized(run, VETOABLE_PAGE, variables, sizes, "the closed decided issues")["vetoable"]
        decided["nodes"] = decided["nodes"] + page["nodes"]
        decided["pageInfo"] = page["pageInfo"]
    for issue in decided["nodes"]:
        complete_comments(run, base, sizes, issue)

    # Only the newest stable tag is used: page back until one is in hand, not through every tag
    tags = data["tags"]
    seen = set()
    while tags["pageInfo"]["hasPreviousPage"] and latest_stable(tags["nodes"], stable_pattern) is None:
        cursor = advance(tags["pageInfo"]["startCursor"], seen, "tags")
        page = sized(run, TAGS_PAGE, {**base, "cursor": cursor}, sizes, "older tags")["tags"]
        tags["nodes"] = page["nodes"] + tags["nodes"]
        tags["pageInfo"] = page["pageInfo"]
    return data


def keyword_closes(title: str, body: str) -> set[int]:
    """The issue numbers a PR's closing keywords name: one in the title outside code spans, or
    one starting a line of the body (after an optional list bullet) outside a code fence. A
    keyword quoted mid-line, in backticks, or in a fence names nothing (#368, #416)"""
    found = {int(n) for n in TITLE_CLOSER.findall(CODE_SPAN.sub("", title))}
    fenced = False
    for line in body.splitlines():
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            found |= {int(n) for n in LINE_CLOSER.findall(line)}
    return found


def closes(pr: dict[str, Any], number: int, *, partial: bool = False) -> bool:
    """A closing keyword naming the issue by keyword_closes' rule (or, with ``partial``,
    "Part of #N" anywhere in the PR's title or body, for a PR covering part of the issue);
    GitHub's own willCloseTarget misses some"""
    title, body = pr.get("title") or "", pr.get("body") or ""
    if number in keyword_closes(title, body):
        return True
    return partial and re.search(rf"\bpart of:?\s+#{number}\b", f"{title}\n{body}", re.IGNORECASE) is not None


def linked_prs(issue: dict[str, Any]) -> list[tuple[int, str, bool]]:
    """Same-repo PRs that will close the issue, cover part of it, or were linked to it by
    hand, each with whether it closes the whole issue"""
    found: dict[int, tuple[str, bool]] = {}
    for node in issue["timelineItems"]["nodes"]:
        if "subject" in node:
            pr = node["subject"] or {}
            whole = True
        elif node.get("isCrossRepository"):
            continue
        else:
            pr = node.get("source") or {}
            whole = bool(node.get("willCloseTarget")) or closes(pr, issue["number"])
            if not (whole or closes(pr, issue["number"], partial=True)):
                continue
        if "number" in pr:
            _, before = found.get(pr["number"], ("", False))
            found[pr["number"]] = (pr["state"], whole or before)
    return sorted((n, s, w) for n, (s, w) in found.items())


def merged_mentions(issue: dict[str, Any]) -> list[int]:
    """Same-repo merged PRs that mention the issue at all"""
    return sorted(
        n["source"]["number"]
        for n in issue["refs"]["nodes"]
        if not n.get("isCrossRepository") and n.get("source", {}).get("state") == "MERGED"
    )


def merged_closers(issue: dict[str, Any]) -> list[int]:
    """Same-repo merged PRs that close the issue: GitHub's willCloseTarget, or a closing
    keyword naming it by keyword_closes' rule, the link DONE_NOT_CLOSED reads too"""
    return sorted(
        n["source"]["number"]
        for n in issue["refs"]["nodes"]
        if not n.get("isCrossRepository")
        and n.get("source", {}).get("state") == "MERGED"
        and (n.get("willCloseTarget") or closes(n["source"], issue["number"]))
    )


def upstream_refs(issue: dict[str, Any], repo: tuple[str, str]) -> list[tuple[str, str, int]]:
    """Issues and pull requests that a hold comment says this one waits on"""
    return sorted(hold_refs(issue, repo))


def hold_refs(issue: dict[str, Any], repo: tuple[str, str]) -> dict[tuple[str, str, int], int]:
    """Each issue or pull request a hold comment names, with the index of the newest
    comment naming it: an owner/repo#N or URL in a sentence with a hold phrase, or a plain
    #N right after one, which is one of repo's own (owner, name)"""
    refs: dict[tuple[str, str, int], int] = {}
    for i, c in enumerate(issue["comments"]["nodes"]):
        for line in c["body"].splitlines():
            for sentence in SENTENCE.split(line):
                if HOLD.search(sentence):
                    refs.update(((m["owner"], m["name"], int(m["num"])), i) for m in UPSTREAM.finditer(sentence))
                    refs.update(((*repo, int(m["num"])), i) for m in SAME_REPO.finditer(sentence))
    return refs


def depends_lines(body: str) -> list[tuple[int, str, str, bool]]:
    """Each "Depends on" line of a body outside a ``` or ~~~ fence (spec 041): its number
    counted from 1, the line, the text its references are read from, and whether it is
    malformed. A strict line's text stops at its note; a malformed one, naming a reference
    outside the strict shape, is read whole, so nothing it held starts early"""
    found: list[tuple[int, str, str, bool]] = []
    fenced = False
    for n, line in enumerate(body.replace("\r\n", "\n").split("\n"), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        depends = None if fenced else DEPENDS.fullmatch(line)
        if depends is None:
            continue
        strict = STRICT_DEPENDS.fullmatch(depends["refs"])
        if strict is not None:
            found.append((n, line, strict["refs"], False))
        else:
            named = DEPENDENCY.search(depends["refs"]) or PLACEHOLDER.search(depends["refs"])
            found.append((n, line, depends["refs"], named is not None))
    return found


def dependency_refs(issue: dict[str, Any], repo: tuple[str, str]) -> list[tuple[str, str, int]]:
    """The issues a "Depends on" line of the issue's body names (depends_lines); a plain #N
    is one of repo's own (owner, name)"""
    found: set[tuple[str, str, int]] = set()
    for _, _, text, _ in depends_lines(issue["body"]):
        for m in DEPENDENCY.finditer(text):
            found.add((m["owner"], m["name"], int(m["num"])) if m["owner"] is not None else (*repo, int(m["num"])))
    return sorted(found)


def unfilled_dependencies(issue: dict[str, Any]) -> list[str]:
    """The placeholders ({B1}) a "Depends on" line of the issue's body still names instead
    of an issue number: specs.py split's keys, never filled in"""
    keys = (m["key"] for _, _, text, _ in depends_lines(issue["body"]) for m in PLACEHOLDER.finditer(text))
    return list(dict.fromkeys(keys))


def malformed_dependencies(issue: dict[str, Any]) -> list[str]:
    """Each malformed "Depends on" line of the issue's body as "line <n>: <the line>" (spec 041)"""
    return [f"line {n}: {line.strip()}" for n, line, _, malformed in depends_lines(issue["body"]) if malformed]


def upstream_states(
    refs: set[tuple[str, str, int]],
) -> tuple[dict[tuple[str, str, int], str], dict[tuple[str, str, int], str]]:
    """Each upstream issue's or pull request's state as ref_state reads it, and, for one
    that closed, when it closed: a person's hand-off counts only after its newest hold closed"""
    if not refs:
        return {}, {}
    ordered = sorted(refs)
    parts = [
        f'r{i}: repository(owner: "{o}", name: "{n}") {{ issueOrPullRequest(number: {k}) '
        "{ __typename ... on Issue { state stateReason closedAt } ... on PullRequest { state closedAt } } }"
        for i, (o, n, k) in enumerate(ordered)
    ]
    proc = subprocess.run(
        ["gh", "api", "graphql", "-f", "query={" + " ".join(parts) + "}"], capture_output=True, text=True, check=False
    )
    data = json.loads(proc.stdout or "{}").get("data") or {}
    states = {}
    closes = {}
    for i, ref in enumerate(ordered):
        node = (data.get(f"r{i}") or {}).get("issueOrPullRequest") or {}
        states[ref] = ref_state(node)
        if node.get("closedAt"):
            closes[ref] = str(node["closedAt"])
    return states, closes


def ref_state(node: dict[str, Any]) -> str:
    """An upstream issue's state (OPEN, CLOSED, and NOT_PLANNED for one closed as not
    planned: it holds nothing, but its work never landed), or a pull request's (OPEN,
    MERGED, and CLOSED_UNMERGED for one closed without merging, such as a refused spec PR:
    the issue reads SPEC_REFUSED until a newer triage comment decides again). GitHub
    numbers issues and PRs in one sequence, so owner/repo#N may be either"""
    state: str = node.get("state", "UNKNOWN")
    if node.get("__typename") == "Issue" and state == "CLOSED" and node.get("stateReason") == "NOT_PLANNED":
        return "NOT_PLANNED"
    if node.get("__typename") == "PullRequest" and state == "CLOSED":
        return "CLOSED_UNMERGED"
    return state


Ref = tuple[str, str, int]
# An issue's loop on a cycle (cycles), with the issue on it that breaks it, or None (spec 041)
Cycle = tuple[list[Ref], Ref | None]


def native_holds(issue: dict[str, Any]) -> dict[Ref, tuple[str, str, str | None]]:
    """The issues the forge says hold this one, each with its kind ("native" for one it
    is blocked by, "child" for a sub-issue, which wins when it is both), its state as
    ref_state reads it, and when it closed (None while open). An issue fetched without
    them (the forge refused them) has none"""
    holds: dict[Ref, tuple[str, str, str | None]] = {}
    for field, kind in (("blockedBy", "native"), ("subIssues", "child")):
        for node in (issue.get(field) or {}).get("nodes", []):
            owner, _, name = node["repository"]["nameWithOwner"].partition("/")
            ref = (owner, name, int(node["number"]))
            if kind == "child" or ref not in holds:
                holds[ref] = (kind, ref_state({**node, "__typename": "Issue"}), node.get("closedAt"))
    return holds


def fold(ref: Ref) -> Ref:
    """GitHub owner and repo names ignore case: O/R#3 and o/r#3 are one issue"""
    return (ref[0].lower(), ref[1].lower(), ref[2])


def shortest_loop(graph: dict[Ref, list[Ref]], node: Ref) -> list[Ref] | None:
    """The shortest loop through node in graph (each issue's open holds, as folded refs, spec
    041), rotated to start at its least ref, ties broken by the least sequence: the loop's
    refs without the first repeated, or None when node is on no loop. A ref is on a shortest
    loop through node exactly when it is i steps from node and the loop's length less i steps
    back to it. The least loop starts at the least such ref, and is the least shortest path
    from it to node, then the least from node back to it: each walked by taking the least
    next ref one step nearer the end. That is linear per step, where enumerating every
    shortest loop grows exponentially on a dense backlog"""
    back = reverse(graph)
    ahead, behind = distances(graph, node), distances(back, node)
    lengths = [ahead[ref] + 1 for ref in back.get(node, []) if ref in ahead]
    if not lengths:
        return None
    size = min(lengths)
    first = min([node, *(ref for ref, step in ahead.items() if step + behind.get(ref, size) == size and step)])

    def walk(start: Ref, near: dict[Ref, int], steps: int) -> list[Ref]:
        path = [start]
        for left in range(steps - 1, 0, -1):
            path.append(min(ref for ref in graph.get(path[-1], []) if near.get(ref) == left))
        return path

    if first == node:
        return walk(node, behind, size)
    return walk(first, behind, behind[first]) + walk(node, distances(back, first), ahead[first])


def reverse(graph: dict[Ref, list[Ref]]) -> dict[Ref, list[Ref]]:
    """graph with every edge turned round"""
    back: dict[Ref, list[Ref]] = {}
    for ref, holds in graph.items():
        for hold in holds:
            back.setdefault(hold, []).append(ref)
    return back


def distances(graph: dict[Ref, list[Ref]], start: Ref) -> dict[Ref, int]:
    """Each ref graph reaches from start, with the fewest steps it takes"""
    found = {start: 0}
    queue = [start]
    for ref in queue:
        for hold in graph.get(ref, []):
            if hold not in found:
                found[hold] = found[ref] + 1
                queue.append(hold)
    return found


def cycles(issues: list[dict[str, Any]], repo: tuple[str, str], marker: str, skipped: set[int]) -> dict[int, list[Ref]]:
    """Each open issue of the repo on a cycle (spec 041), by number, with its loop as
    shortest_loop reads it, each issue in the repo's spelling and the first repeated at the
    end. The links are the holds triage reads, in one graph and with no extra query: an open
    issue's, once triaged or a person's item, on its Depends on lines (a malformed one's
    included) and the forge's blockedBy and sub-issues, kept to the repo's open issues. A
    ``skipped`` issue (read as UNTRUSTED) has none, so no loop runs through one. A comment's
    hold sentence is no link, as chains.py reads none"""
    home = fold((*repo, 0))[:2]
    numbers = {int(issue["number"]) for issue in issues}
    graph: dict[Ref, list[Ref]] = {}
    for issue in issues:
        number = int(issue["number"])
        triaged = any(c["body"].lstrip().startswith(marker) for c in issue["comments"]["nodes"])
        if number in skipped or not (triaged or person_item(issue)):
            continue
        holds = {fold(ref) for ref in [*dependency_refs(issue, repo), *native_holds(issue)]}
        graph[(*home, number)] = sorted(r for r in holds if r[:2] == home and r[2] in numbers and r[2] != number)
    found: dict[int, list[Ref]] = {}
    for key in graph:
        loop = shortest_loop(graph, key)
        if loop is not None:
            found[key[2]] = [(*repo, ref[2]) for ref in [*loop, loop[0]]]
    return found


def timestamp(text: str) -> dt.datetime:
    """A GitHub ISO 8601 time; tagger dates carry an offset, comment dates a "Z", which
    fromisoformat rejects before Python 3.11"""
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        moment = None
    if moment is None or moment.tzinfo is None:
        sys.stderr.write(f"error: gh returned a time without a timezone or not ISO 8601: {text!r}\n")
        raise SystemExit(2)
    return moment


def latest_stable(tags: list[dict[str, Any]], pattern: re.Pattern[str] = STABLE) -> tuple[dt.datetime, str] | None:
    stable = []
    for t in tags:
        target = t["target"] or {}
        date = (target.get("tagger") or {}).get("date") or target.get("committedDate")
        if date and pattern.match(t["name"]):
            stable.append((timestamp(date), t["name"]))
    return max(stable) if stable else None


def off_milestone(issue: dict[str, Any], repo: tuple[str, str]) -> str | None:
    """The note of OFF_MILESTONE (spec 022): a build issue whose feature issue, its sub-issue
    parent in this repository, is in a milestone the build issue isn't in; None when it is
    in that milestone, the parent has none, or it has no parent here (another repo's
    milestones aren't this one's, and an issue fetched without native fields has none)"""
    parent = issue.get("parent")
    if not parent:
        return None
    if parent["repository"]["nameWithOwner"].lower() != "/".join(repo).lower():
        return None
    goal = (parent.get("milestone") or {}).get("title")
    own = (issue.get("milestone") or {}).get("title")
    if goal is None or own == goal:
        return None
    where = f"milestone {own}" if own is not None else "no milestone"
    return f"parent #{parent['number']} is in milestone {goal}, this is in {where}"


def classify_open(
    issue: dict[str, Any],
    marker: str,
    postponed: str,
    states: dict[tuple[str, str, int], str],
    stable: tuple[dt.datetime, str] | None,
    repo: tuple[str, str],
    bot_login: str | None = None,
    closes: dict[tuple[str, str, int], str] | None = None,
    milestone: bool = True,
    roles: Roles | None = None,
    cycle: Cycle | None = None,
) -> tuple[str, str]:
    """An open issue's state once gated found none; ``closes`` says when each closed hold
    closed, which a person's item (labelled human or role:<name>) reads its hand-off against.
    Without ``milestone``, the state OFF_MILESTONE hides (--wip counts one hiding IN_PROGRESS).
    ``roles``, the --role flags (None without them), turns NO_ASSIGNEE into ASSIGN_DUE.
    ``cycle`` is the issue's loop when it is on a cycle (cycles), with the issue on it that
    breaks the loop, if any: it reads CYCLE, or BLOCKED waiting on that issue (spec 041)"""
    missed = off_milestone(issue, repo) if milestone else None
    if missed is not None:
        return "OFF_MILESTONE", missed
    labels = {n["name"] for n in issue["labels"]["nodes"]}
    # A person's item (labelled human or role:<name>): its assignees do it, never an
    # implementer, so no PR state applies, and it counts as triaged from the start (spec 017)
    own_roles = item_roles(issue)
    human = bool(own_roles)
    triaged = [c for c in issue["comments"]["nodes"] if c["body"].lstrip().startswith(marker)]
    triage = [c["body"] for c in triaged]
    prs = linked_prs(issue)
    open_prs = [n for n, s, _ in prs if s == "OPEN"]
    merged = [n for n, s, whole in prs if s == "MERGED" and whole]
    note = " ".join(f"#{n}:{s.lower()}" + ("" if whole else "(part)") for n, s, whole in prs)
    people = assignees(issue) if human else []
    teams: tuple[str, ...] = ()
    if human and roles is None and not people:
        return "NO_ASSIGNEE", no_assignee_note(issue)
    if human and roles is not None:
        # Spec 036: its roles' teams are mentioned at the hand-off; with no assignee, its
        # roles' users are assigned, while it is still held, so the step is theirs at once
        users, teams, undefined = resolve(issue, roles)
        if users and not people:
            return "ASSIGN_DUE", assign_note(users, own_roles, undefined)
    if open_prs and not human:
        return "IN_PROGRESS", note
    if merged and not human:
        return "DONE_NOT_CLOSED", note
    # The body's dependencies are older than every comment; a comment naming one too is newer.
    # They hold a triaged issue only, as the forge's own relations do (spec 017): an
    # untriaged one with "Depends on #48", a blockedBy issue, or a sub-issue still reads NEW
    held = bool(triage) or human
    body = dependency_refs(issue, repo) if held else []
    named = {**dict.fromkeys(body, -1), **hold_refs(issue, repo)}
    # The forge's relations join the text holds as one set: an issue named both ways counts
    # once, under the text's spelling. The note marks one only the forge records (native)
    # and a sub-issue (child), and a parent's starts with how many of its children closed
    texts = {fold(r): r for r in named}
    native = native_holds(issue) if held else {}
    states = {**states}
    closes = {**(closes or {})}
    marks: dict[Ref, str] = {}
    children: list[str] = []
    for ref, (kind, state, closed) in native.items():
        key = texts.get(fold(ref), ref)
        named.setdefault(key, -1)
        states[key] = state
        if closed is not None:
            closes[key] = closed
        if kind == "child":
            marks[key] = "(child)"
            children.append(state)
        elif fold(ref) not in texts:
            marks[key] = "(native)"
    comments = issue["comments"]["nodes"]
    verdict = max((i for i, c in enumerate(comments) if c["body"].lstrip().startswith(marker)), default=-1)
    # A refused PR named before the newest triage comment was decided again: it holds nothing
    waits = sorted(r for r, i in named.items() if states.get(r) != "CLOSED_UNMERGED" or i >= verdict)
    shown = " ".join(f"{o}/{n}#{k}:{states.get((o, n, k), '?').lower()}{marks.get((o, n, k), '')}" for o, n, k in waits)
    if children:
        closed = sum(1 for s in children if s in ("CLOSED", "NOT_PLANNED"))
        shown = f"children {closed}/{len(children)} closed {shown}"
    unfilled = unfilled_dependencies(issue)
    if unfilled:
        # Which issue it waits on is unknown, so neither BLOCKED nor ready: someone fills it in
        return "UNFILLED", " ".join([*(f"unfilled dependency {{{k}}}" for k in unfilled), shown]).strip()
    malformed = malformed_dependencies(issue) if held else []
    if malformed:
        # Which of its references are holds is unclear, so nothing starts on it: a session
        # rewrites the line (spec 041). CYCLE is read right after this, before SPEC_REFUSED
        return "MALFORMED_DEPENDS", " | ".join([*malformed, shown] if shown else malformed)
    if cycle is not None:
        # Nothing on the loop can start, so a session asks which link is wrong; when another
        # item on it already waits on a question or a line fix, that one breaks the loop (spec 041)
        loop, breaker = cycle
        said = f"cycle {' -> '.join(f'{o}/{n}#{k}' for o, n, k in loop)}"
        if breaker is not None:
            said += f" waits on {breaker[0]}/{breaker[1]}#{breaker[2]}"
        return ("CYCLE" if breaker is None else "BLOCKED"), " | ".join([said, shown] if shown else [said])
    if waits or "blocked" in labels:
        if any(states.get(r) == "CLOSED_UNMERGED" for r in waits):
            return "SPEC_REFUSED", shown
        still = [r for r in waits if states.get(r) not in CLOSED_STATES]
        if still or not waits:
            return "BLOCKED", shown or "labelled blocked"
        if not human and children and CHECK.search(issue.get("body") or ""):
            return parent_check(comments, bot_login, [closes[r] for r in waits if r in closes], shown)
        if not human:
            return "UNBLOCKED", shown
    if postponed in labels:
        # Comments come oldest first: a re-decision after the tag clears REVISIT
        if stable and triaged and timestamp(triaged[-1]["createdAt"]) < stable[0]:
            return "REVISIT", f"postponed before {stable[1]}"
        return "POSTPONED", note
    if human:
        # Every hold has closed: the person's turn starts at the newest close
        ends = [timestamp(closes[r]) for r in waits if r in closes and states.get(r) in CLOSED_STATES]
        since = max(ends, default=None)
        return person_state(issue["comments"]["nodes"], people, bot_login, since, shown, teams)
    if not triage:
        return "NEW", note
    if PLAN_LABEL in labels and triage[-1].lstrip()[len(marker) :].lstrip().lower().startswith(PLAN_VERDICT):
        return "TRIAGED", note  # product intake's comment on a goal's plan (S-028-14), never an implement
    if re.search(r"\bimplement\b", triage[-1], re.IGNORECASE):
        return "NEEDS_PR", note
    return "TRIAGED", note


def login(author: dict[str, Any] | None) -> str:
    """An author's login as REST and --bot-login spell it: a Bot's with "[bot]", a deleted
    account's as ghost"""
    if not author:
        return "ghost"
    name = str(author.get("login") or "ghost")
    if author.get("__typename") == "Bot" and not name.endswith("[bot]"):
        name += "[bot]"
    return name


def same_login(a: str, b: str) -> bool:
    return a.lower() == b.lower()  # GitHub logins ignore case


def first_line(body: str) -> str:
    """A comment's first line, past any leading blank lines"""
    return body.lstrip().split("\n", 1)[0].strip()


def marked(body: str, marker: str = DECISION_MARKER) -> bool:
    """Whether a comment's first line is the marker (by default the needs-decision one); a
    quote of it further down is no question, hand-off, or verification"""
    return first_line(body) == marker


def question(comments: list[tuple[str, str, str]], bot_login: str | None) -> int | None:
    """The index of an item's question, or None; comments are (login, author association,
    body), oldest first. A question's first line is the marker. Without --bot-login it is
    the newest such comment by an OWNER, MEMBER, or COLLABORATOR; with it, the newest such
    comment by that login, unless an OWNER, MEMBER, or COLLABORATOR wrote a newer one: a
    person asked after the bot, so the item has no question. A marker comment by any other
    author never counts, so an outsider can't re-park an answered item (#184)"""
    for i in range(len(comments) - 1, -1, -1):
        author, association, body = comments[i]
        if not marked(body):
            continue
        if bot_login is not None and same_login(author, bot_login):
            return i
        if association in TRUSTED:
            return None if bot_login is not None else i
    return None


def replies(comment: tuple[str, str, str], bot_login: str | None) -> bool:
    """A reply: a comment without the marker by an OWNER, MEMBER, or COLLABORATOR other
    than the --bot-login"""
    author, association, body = comment
    if bot_login is not None and same_login(author, bot_login):
        return False
    return association in TRUSTED and not marked(body)


def waits_on_decision(comments: list[tuple[str, str, str]], bot_login: str | None) -> bool:
    """Whether a needs-decision item still waits; comments are (login, author association,
    body), oldest first. It waits until a reply comes after its question; with no question
    at all, a person parked it, so it waits too"""
    asked = question(comments, bot_login)
    if asked is None:
        return True
    return not any(replies(c, bot_login) for c in comments[asked + 1 :])


def trusted(author: str, association: str, bot_login: str | None) -> bool:
    """D-16: an OWNER, MEMBER, or COLLABORATOR, or the sessions' own bot"""
    return association in TRUSTED or (bot_login is not None and same_login(author, bot_login))


def vetoes(comment: tuple[str, str, str], bot_login: str | None) -> bool:
    """A veto (spec 030): a comment by an OWNER, MEMBER, or COLLABORATOR other than the
    --bot-login whose first word is "veto" in any case; an outsider's never counts (D-16),
    nor does a "veto" further into a comment"""
    author, association, body = comment
    if bot_login is not None and same_login(author, bot_login):
        return False
    return association in TRUSTED and VETO.match(first_line(body)) is not None


def vetoed(comments: list[tuple[str, str, str]], bot_login: str | None) -> str | None:
    """Who vetoed a decided item and is still unanswered, or None; comments are (login, author
    association, body), oldest first. A veto counts after the first decided marker (its first
    line, by the --bot-login or an OWNER, MEMBER, or COLLABORATOR, as D-29's markers), until a
    newer veto-handled marker by such an author answers it"""
    marks = (
        i
        for i, (author, association, body) in enumerate(comments)
        if DECIDED_MARKER.match(first_line(body)) and trusted(author, association, bot_login)
    )
    decided = next(marks, None)
    if decided is None:
        return None
    veto, handled = None, -1
    for i in range(decided + 1, len(comments)):
        author, association, body = comments[i]
        if VETO_HANDLED_MARKER.match(first_line(body)) and trusted(author, association, bot_login):
            handled = i
        elif vetoes(comments[i], bot_login):
            veto = i
    if veto is None or handled > veto:
        return None
    return comments[veto][0]


def comment_tuples(issue: dict[str, Any]) -> list[tuple[str, str, str]]:
    """An issue's comments as the decision rules read them: (login, author association, body)"""
    return [
        (login(c.get("author")), str(c.get("authorAssociation") or "NONE"), c["body"])
        for c in issue["comments"]["nodes"]
    ]


def closed_vetoed(issue: dict[str, Any], bot_login: str | None) -> tuple[str, str] | None:
    """VETOED for a closed issue labelled decided (the query picks those updated in the veto
    window) that holds an unanswered trusted veto; None otherwise, which reports nothing"""
    who = vetoed(comment_tuples(issue), bot_login)
    return None if who is None else ("VETOED", f"closed, vetoed by @{who}")


def upgrade_id(body: str) -> str | None:
    """The config upgrade an issue proposes, from the marker on its body's first line (not
    past leading blank lines); None without one"""
    found = UPGRADE_MARKER.match(body.replace("\r\n", "\n").split("\n", 1)[0])
    return found.group(1) if found else None


def workflow_upgrade(issue: dict[str, Any]) -> bool:
    """D-30: an issue the release workflow opened for a config upgrade, which an unattended
    session takes up too: authored by the Bot github-actions[bot] (a User of a like name
    never counts), labelled shipmill-upgrade, with the upgrade marker as its body's first
    line. Any other github-actions[bot] issue stays untrusted"""
    author = issue.get("author")
    if not author or author.get("__typename") != "Bot" or not same_login(login(author), WORKFLOW_BOT):
        return False
    labels = {n["name"] for n in issue["labels"]["nodes"]}
    return UPGRADE_LABEL in labels and upgrade_id(issue["body"]) is not None


def direction_issue(issue: dict[str, Any], bot_login: str | None) -> bool:
    """Spec 034: shipmill's question for the product's direction, which github-ship-watch
    asks and takes up: labelled shipmill-direction, the marker as its body's first line
    exactly (not past leading blank lines or whitespace; a CRLF body reads as LF, trailing
    whitespace is dropped), and opened by an OWNER, MEMBER, or COLLABORATOR or the
    --bot-login (D-16). An issue missing any of the three is any issue to triage"""
    labels = {n["name"] for n in issue["labels"]["nodes"]}
    if DIRECTION_LABEL not in labels:
        return False
    if (issue["body"] or "").replace("\r\n", "\n").split("\n", 1)[0].rstrip() != DIRECTION_MARKER:
        return False
    return trusted(login(issue.get("author")), str(issue.get("authorAssociation") or "NONE"), bot_login)


def assignees(issue: dict[str, Any]) -> list[str]:
    """The logins a person's item is assigned to"""
    return [str(n["login"]) for n in issue["assignees"]["nodes"]]


def by_trusted(comment: dict[str, Any], bot_login: str | None) -> bool:
    """A comment by an OWNER, MEMBER, or COLLABORATOR, or by the --bot-login (D-16): the
    only authors whose hand-off or verified marker counts"""
    return trusted(login(comment.get("author")), str(comment.get("authorAssociation") or "NONE"), bot_login)


def done_report(comment: dict[str, Any], people: list[str], bot_login: str | None) -> bool:
    """A comment whose first line starts with "done" in any case, by one of the item's
    assignees or a trusted author: the person says their part is finished"""
    if not first_line(comment["body"]).lower().startswith("done"):
        return False
    author = login(comment.get("author"))
    return any(same_login(author, p) for p in people) or by_trusted(comment, bot_login)


def no_assignee_note(issue: dict[str, Any]) -> str:
    """NO_ASSIGNEE's note: the label that makes it a person's item"""
    names = [str(n["name"]) for n in issue["labels"]["nodes"]]
    if any(n.lower() == HUMAN_LABEL for n in names):
        return "labelled human, no assignee"
    shown = " ".join(n.lower() for n in names if n.lower().startswith(ROLE_PREFIX))
    return f"labelled {shown}, no assignee"


def assign_note(users: tuple[str, ...], roles: list[str], undefined: list[str]) -> str:
    """ASSIGN_DUE's note (spec 036): whom to assign, for which roles, and each role no
    --role flag gives, which fell back to the maintainer"""
    note = " ".join(f"@{u}" for u in users) + " (" + " ".join(f"{ROLE_PREFIX}{r}" for r in roles) + ")"
    return "; ".join([f"assign {note}", *(f"{ROLE_PREFIX}{r} undefined" for r in undefined)])


def person_state(
    comments: list[dict[str, Any]],
    people: list[str],
    bot_login: str | None,
    since: dt.datetime | None,
    shown: str,
    teams: tuple[str, ...] = (),
) -> tuple[str, str]:
    """A person's item with nothing holding it: HANDOFF_DUE until a trusted hand-off comes
    after its newest hold closed (``since``, None when it never had one), then WITH_PERSON
    until a done report follows the newest such hand-off, then VERIFY_DUE. ``teams``, its
    roles' teams (spec 036), are named with its assignees"""
    who = " ".join([*(f"@{p}" for p in people), *teams])
    handoffs = [
        i
        for i, c in enumerate(comments)
        if marked(c["body"], HANDOFF_MARKER)
        and by_trusted(c, bot_login)
        and (since is None or timestamp(c["createdAt"]) > since)
    ]
    if not handoffs:
        return "HANDOFF_DUE", " ".join(part for part in (f"for {who}", shown) if part)
    newest = handoffs[-1]
    for c in reversed(comments[newest + 1 :]):
        if done_report(c, people, bot_login):
            return "VERIFY_DUE", f"done reported by @{login(c.get('author'))}"
    return "WITH_PERSON", f"with {who} since {comments[newest]['createdAt']}"


def parent_check(comments: list[dict[str, Any]], bot_login: str | None, ends: list[str], shown: str) -> tuple[str, str]:
    """A parent with a ## Check whose holds all closed (spec 042): WITH_PERSON while a check
    waits on a person (check_waiting, #740), else CHECK_FAILED when a trusted check-failed
    comment came after the newest close among its holds (``ends``), else VERIFY_DUE.
    ``shown`` is its holds' note, starting with the children's progress"""
    newest = max((timestamp(e) for e in ends), default=None)
    waits = check_waiting(comments, bot_login, newest)
    if waits is not None:
        return "WITH_PERSON", f"check waiting on @{waits[0]} since {waits[1]} {shown}"
    failed = [
        c
        for c in comments
        if marked(c["body"], CHECK_FAILED_MARKER)
        and by_trusted(c, bot_login)
        and (newest is None or timestamp(c["createdAt"]) > newest)
    ]
    if failed:
        return "CHECK_FAILED", f"check failed {failed[-1]['createdAt']} {shown}"
    return "VERIFY_DUE", f"{shown}: run its ## Check"


def check_waiting(
    comments: list[dict[str, Any]], bot_login: str | None, newest: dt.datetime | None
) -> tuple[str, str] | None:
    """Whom a parent's ## Check waits on and since when (#740): the newest check-waiting
    comment after ``newest`` (the newest close among its holds; None reads them all) with no
    check-failed or verified comment after it, each by a trusted author (D-16), as (login,
    createdAt); None when there is none. Its login is the first @login past the comment's
    first line, or its author's when it names none"""
    found: dict[str, Any] | None = None
    for c in comments:  # oldest first
        if not by_trusted(c, bot_login) or (newest is not None and timestamp(c["createdAt"]) <= newest):
            continue
        if marked(c["body"], CHECK_WAITING_MARKER):
            found = c
        elif marked(c["body"], CHECK_FAILED_MARKER) or marked(c["body"], VERIFIED_MARKER):
            found = None
    if found is None:
        return None
    rest = found["body"].lstrip().split("\n", 1)[1:]
    named = MENTION.search(rest[0]) if rest else None
    return (named.group(1) if named else login(found.get("author"))), str(found["createdAt"])


def upstream_note(home: str | None, asks: bool) -> str:
    """UPSTREAM's note (spec 038): who routes the report, and whether its question to the
    maintainer still waits for a reply"""
    note = f"routed by {home}" if home is not None else "no coordinator: waits for the maintainer"
    return f"{note}, asks the maintainer" if asks else note


def home_repo(text: str) -> bool:
    """Whether text is owner/name, each side of letters, digits, '.', '-', or '_' and neither
    "." nor "..", as shipmill reads a repo (app.repo_name and its cache segment rule)"""
    parts = text.split("/")
    return len(parts) == 2 and all(p not in {".", ".."} and SEGMENT.fullmatch(p) for p in parts)


def gated(
    issue: dict[str, Any], bot_login: str | None, trusted_only: bool, home: str | None = None
) -> tuple[str, str] | None:
    """UNTRUSTED (with trusted_only), then UPSTREAM, then NEEDS_DECISION or DECIDED, then
    VETOED, each read before any other state; None when none holds, and the issue reads as
    classify_open says. DECIDED comes first so the reply is acted on, whatever its text links
    (#309). An upstream report waits outside whatever its labels and holds (spec 038); ``home``
    words its note. VETOED is an item labelled decided with an unanswered veto (spec 030)"""
    author, association = login(issue.get("author")), str(issue.get("authorAssociation") or "NONE")
    if trusted_only and not trusted(author, association, bot_login) and not workflow_upgrade(issue):
        return "UNTRUSTED", f"opened by @{author} ({association.lower()})"
    labels = {n["name"] for n in issue["labels"]["nodes"]}
    if UPSTREAM_LABEL in labels or DECISION_LABEL in labels or DECIDED_LABEL in labels:
        comments = comment_tuples(issue)
        if UPSTREAM_LABEL in labels:
            asks = DECISION_LABEL in labels and waits_on_decision(comments, bot_login)
            return "UPSTREAM", upstream_note(home, asks)
        if DECISION_LABEL in labels:
            asked = question(comments, bot_login)
            if waits_on_decision(comments, bot_login):
                return "NEEDS_DECISION", "waits on a reply" if asked is not None else "labelled, no question"
            # it no longer waits, so it has a question and a reply after it: the newest reply
            reply = next(c for c in reversed(comments) if replies(c, bot_login))
            return "DECIDED", f"answered by @{reply[0]}"
        who = vetoed(comments, bot_login)
        if who is not None:
            return "VETOED", f"vetoed by @{who}"
    return None


def verify_closed(issue: dict[str, Any], bot_login: str | None) -> tuple[str, str] | None:
    """VERIFY_CLOSED for a person's item closed as completed by someone other than the
    --bot-login, with a ## Check section and no trusted verified comment after its close;
    None otherwise. Its comments are the ones fetch read back to its close"""
    if not checkable(issue):
        return None
    events = issue["timelineItems"]["nodes"]
    actor = login(events[0].get("actor") if events else None)
    if bot_login is not None and same_login(actor, bot_login):
        return None
    if verified(issue, bot_login):
        return None
    return "VERIFY_CLOSED", f"closed by @{actor}: run its ## Check"


def verified(issue: dict[str, Any], bot_login: str | None) -> bool:
    """Whether a comment after the issue's last close has the verified marker as its first
    line, by an OWNER, MEMBER, or COLLABORATOR or the --bot-login"""
    since = closed_at(issue)
    return any(
        timestamp(c["createdAt"]) > since and marked(c["body"], VERIFIED_MARKER) and by_trusted(c, bot_login)
        for c in issue["comments"]["nodes"]
    )


def parent_closed(issue: dict[str, Any], bot_login: str | None) -> tuple[str, str] | None:
    """VERIFY_CLOSED for a closed parent that owes its check (spec 042, parent_checkable) when
    a pull request or a commit closed it, or the --bot-login, and no trusted verified comment
    came after the close: never SUSPECT_CLOSE. None when it was verified"""
    events = issue["timelineItems"]["nodes"]
    closer = events[0].get("closer") if events else None
    if verified(issue, bot_login):
        return None
    if closer is None:
        return "VERIFY_CLOSED", f"closed by @{login(events[0].get('actor') if events else None)}: run its ## Check"
    if closer["__typename"] == "PullRequest":
        return "VERIFY_CLOSED", f"closed by #{closer['number']}: run its ## Check"
    return "VERIFY_CLOSED", f"closed by commit {closer.get('abbreviatedOid')}: run its ## Check"


def close_confirmed(issue: dict[str, Any], bot_login: str | None) -> bool:
    """Whether a comment after the issue's last close has the close-confirmed marker as its
    first line and comes from an OWNER, MEMBER, or COLLABORATOR or the --bot-login (D-29).
    An outsider's marker never counts, and one before the last close (a reopen and a new
    close) is stale; with no dated close event, no marker can be dated after it"""
    events = issue["timelineItems"]["nodes"]
    if not events or not events[0].get("createdAt"):
        return False
    since = closed_at(issue)
    return any(
        timestamp(c["createdAt"]) > since and marked(c["body"], CLOSE_CONFIRMED_MARKER) and by_trusted(c, bot_login)
        for c in issue["comments"]["nodes"]
    )


def classify_closed(
    issue: dict[str, Any], hold: str, incident: str = INCIDENT_LABEL, bot_login: str | None = None
) -> tuple[str, str] | None:
    labels = {n["name"] for n in issue["labels"]["nodes"]}
    if hold in labels:
        return None
    if person_item(issue) and issue["stateReason"] == "COMPLETED":
        # A person closes their own item by hand by design: never SUSPECT_CLOSE (spec 017)
        return verify_closed(issue, bot_login)
    if UPSTREAM_LABEL in labels:
        return None  # the coordinator, or the maintainer without one, closes a report by hand (spec 038)
    if parent_checkable(issue):
        # Closed by a pull request, a commit, or a session before its check ran (spec 042); a
        # trusted person's own close by hand is their call and reads as before
        event = (issue["timelineItems"]["nodes"] or [{}])[0]
        by_bot = bot_login is not None and same_login(login(event.get("actor")), bot_login)
        if event.get("closer") is not None or by_bot:
            return parent_closed(issue, bot_login)
    if close_confirmed(issue, bot_login):
        return None  # every path below reads None or SUSPECT_CLOSE, which the marker ends (D-29)
    events = issue["timelineItems"]["nodes"]
    closer = events[0].get("closer") if events else None
    number = issue["number"]
    if closer is None:
        # an incident closes by hand once the environment is healthy again; its follow-up is
        # ship-watch's POSTMORTEM_DUE, not triage
        if issue["stateReason"] == "COMPLETED" and incident not in labels and not merged_mentions(issue):
            return "SUSPECT_CLOSE", "closed as completed by hand, and no merged PR mentions it"
        return None
    if closer["__typename"] == "PullRequest":
        return None if closer["merged"] else ("SUSPECT_CLOSE", f"closer PR #{closer['number']} is not merged")
    message: str = closer.get("message", "")
    trailer = re.compile(rf"^\s*(?:[-*]\s*)?{KEYWORDS}:?\s+#{number}\b", re.IGNORECASE | re.MULTILINE)
    # a commit of a merged PR that closes the issue may name it mid-line: the PR is the closer (#363)
    if trailer.search(message) or merged_closers(issue):
        return None
    return "SUSPECT_CLOSE", f"commit {closer.get('abbreviatedOid')} names #{number} only mid-line"


def closed_rows(
    data: dict[str, Any], closed: int, hold: str, incident: str, bot_login: str | None
) -> list[dict[str, Any]]:
    """The lines of closed issues: each closed issue labelled decided in the veto window reads
    VETOED, marked "closed", or nothing (spec 030); VETOED, read right after DECIDED, comes
    before any other state, so such an issue gets no second line. Then the ``closed`` most
    recently updated closed issues as classify_closed reads them"""
    rows: list[dict[str, Any]] = []
    vetoed_closed: set[int] = set()
    for issue in data["vetoable"]["nodes"]:
        verdict = closed_vetoed(issue, bot_login)
        if verdict is not None:
            vetoed_closed.add(issue["number"])
            row = {"number": issue["number"], "state": verdict[0], "title": issue["title"], "note": verdict[1]}
            rows.append({**row, "closed": True})
    for issue in data["closed"]["nodes"][:closed]:
        if issue["number"] in vetoed_closed:
            continue
        verdict = classify_closed(issue, hold, incident, bot_login)
        if verdict is not None:
            rows.append({"number": issue["number"], "state": verdict[0], "title": issue["title"], "note": verdict[1]})
    return rows


def wip_room(
    rows: list[dict[str, Any]], wip: int, people: frozenset[int] = frozenset(), busy: frozenset[int] = frozenset()
) -> dict[str, Any]:
    """How many more issues may start under a WIP limit of ``wip``, counting each issue with
    an open PR as in progress, and the issues ready to start (NEEDS_PR or UNBLOCKED), oldest
    first: build issues are filed in build order. A person's item (one of ``people``) never
    counts: the limit is on agents' work. ``busy`` are issues whose OFF_MILESTONE hides
    IN_PROGRESS: they count as in progress too"""
    agents = [r for r in rows if r["number"] not in people]
    in_progress = sum(1 for r in agents if r["state"] == "IN_PROGRESS" or r["number"] in busy)
    ready = sorted(r["number"] for r in agents if r["state"] in ("NEEDS_PR", "UNBLOCKED"))
    return {"wip": wip, "in_progress": in_progress, "room": max(wip - in_progress, 0), "ready": ready}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog=(
            "States: NEW NEEDS_PR IN_PROGRESS DONE_NOT_CLOSED BLOCKED UNFILLED MALFORMED_DEPENDS CYCLE SPEC_REFUSED "
            "UNBLOCKED POSTPONED REVISIT TRIAGED NEEDS_DECISION DECIDED VETOED UNTRUSTED UPSTREAM OFF_MILESTONE; "
            "for an issue labelled human or role:<name> "
            "(a person's item) NO_ASSIGNEE ASSIGN_DUE HANDOFF_DUE WITH_PERSON VERIFY_DUE; for a closed issue "
            "SUSPECT_CLOSE VERIFY_CLOSED VETOED; for a parent with a ## Check VERIFY_DUE CHECK_FAILED "
            "WITH_PERSON, closed VERIFY_CLOSED. The module docstring defines each."
        ),
    )
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--marker", default="Triage:", help="prefix of a triage comment")
    parser.add_argument("--postponed-label", default="postponed")
    parser.add_argument(
        "--stable-tag-regex",
        default=STABLE.pattern,
        help="tags that count as stable releases, e.g. '^\\d{4}\\.\\d{2}' for CalVer",
    )
    parser.add_argument(
        "--hold-label", default="release-blocker", help="closed issues with this label were closed by hand on purpose"
    )
    parser.add_argument(
        "--incident-label",
        default=INCIDENT_LABEL,
        help="the repo's [operate] incident_label: an incident closed by hand is not SUSPECT_CLOSE",
    )
    parser.add_argument("--closed", type=int, default=20, help="recently closed issues to check")
    parser.add_argument("--json", action="store_true", help="JSON lines instead of a table")
    parser.add_argument("--wip", type=int, help="at most N issues in progress at once: report the room left")
    parser.add_argument(
        "--label",
        action="append",
        default=[],
        help="read only the open issues carrying this label, or any of several (repeatable, spec 046)",
    )
    parser.add_argument("--bot-login", help="the login shipmill's sessions write as, such as <slug>[bot]")
    parser.add_argument(
        "--trusted-only", action="store_true", help="report issues by untrusted authors as UNTRUSTED (D-16)"
    )
    parser.add_argument(
        "--home", metavar="OWNER/NAME", help="the config's [product] home, which routes upstream reports (spec 038)"
    )
    parser.add_argument(
        "--role",
        action="append",
        metavar="NAME=FILLER[,FILLER...]",
        help="a role's resolved fillers (logins or @org/team), one flag per role, maintainer included (spec 036)",
    )
    args = parser.parse_args()
    roles: Roles | None = None
    if args.role is not None:
        try:
            roles = parse_roles(args.role)
        except ValueError as exc:
            parser.error(str(exc))
    if args.home is not None and not home_repo(args.home):
        parser.error(f"--home must be owner/name of letters, digits, '.', '-', or '_', got {args.home!r}")
    if not 0 <= args.closed <= 100:
        parser.error("--closed must be 0..100")
    if args.wip is not None and args.wip < 1:
        parser.error("--wip must be at least 1")
    if args.bot_login is not None and not args.bot_login.strip():
        parser.error("--bot-login must not be empty")
    if any(not label.strip() for label in args.label):
        parser.error("--label must not be empty")
    try:
        stable_pattern = re.compile(args.stable_tag_regex)
    except re.error as exc:
        parser.error(f"--stable-tag-regex: {exc}")

    data = fetch(args.repo, max(args.closed, 1), stable_pattern, labels=args.label)
    owner, _, name = args.repo.partition("/")  # fetch checked it is owner/name
    rows: list[dict[str, Any]] = []
    refs = {r for issue in data["open"]["nodes"] for r in upstream_refs(issue, (owner, name))}
    refs |= {r for issue in data["open"]["nodes"] for r in dependency_refs(issue, (owner, name))}
    # The forge's relations came with their states: ask only for the others
    holds = {r: h for issue in data["open"]["nodes"] for r, h in native_holds(issue).items()}
    native = {r: s for r, (_, s, _) in holds.items()}
    upstream, closes = upstream_states(refs - set(native))
    states = {**upstream, **native}
    # with each one's close time too: a person's hand-off is dated against it
    closes = {**closes, **{r: c for r, (_, _, c) in holds.items() if c is not None}}
    stable = latest_stable(data["tags"]["nodes"], stable_pattern)
    people: set[int] = set()
    busy: set[int] = set()  # OFF_MILESTONE over an open PR: still in progress under --wip
    issues: list[dict[str, Any]] = data["open"]["nodes"]
    gates = {issue["number"]: gated(issue, args.bot_login, args.trusted_only, args.home) for issue in issues}
    untrusted = {n for n, verdict in gates.items() if verdict is not None and verdict[0] == "UNTRUSTED"}
    loops = cycles(issues, (owner, name), args.marker, untrusted)

    def read(issue: dict[str, Any], cycle: Cycle | None = None) -> tuple[str, str]:
        return gates[issue["number"]] or classify_open(
            issue,
            args.marker,
            args.postponed_label,
            states,
            stable,
            (owner, name),
            args.bot_login,
            closes,
            roles=roles,
            cycle=cycle,
        )

    # An issue on a loop that waits on a question, or reads MALFORMED_DEPENDS (read before
    # CYCLE, so it reads so whatever its loop), breaks the loop: the others wait on it (spec 041)
    breakers = {
        issue["number"]
        for issue in issues
        if issue["number"] in loops
        and (DECISION_LABEL in {n["name"] for n in issue["labels"]["nodes"]} or read(issue)[0] == "MALFORMED_DEPENDS")
    }
    for issue in issues:
        if person_item(issue):
            people.add(issue["number"])
        loop = loops.get(issue["number"])
        breaker = None if loop is None else next((r for r in loop if r[2] in breakers - {issue["number"]}), None)
        state, note = read(issue, None if loop is None else (loop, breaker))
        if state == "OFF_MILESTONE":
            usual = classify_open(
                issue, args.marker, args.postponed_label, states, stable, (owner, name), args.bot_login, closes, False
            )
            if usual[0] == "IN_PROGRESS":
                busy.add(issue["number"])
        row: dict[str, Any] = {"number": issue["number"], "state": state, "title": issue["title"], "note": note}
        if direction_issue(issue, args.bot_login):  # spec 034: github-ship-watch's, never in its issue rows
            row["direction"] = True
        if state == "WITH_PERSON":  # whom it waits on, for github-ship-watch's ISSUES_OPEN row
            # a parent's check waits on the person its check-waiting comment names (#740)
            waits = None if person_item(issue) else check_waiting(issue["comments"]["nodes"], args.bot_login, None)
            row["assignees"] = assignees(issue) if waits is None else [waits[0]]
        if roles is not None and state == "ASSIGN_DUE":
            row["assign"] = list(resolve(issue, roles)[0])
        if roles is not None and state in ("HANDOFF_DUE", "WITH_PERSON") and person_item(issue):
            # Spec 036: whom the hand-off mentions, its assignees (maybe none) and its roles' teams
            row["assignees"] = assignees(issue)
            row["teams"] = list(resolve(issue, roles)[1])
        rows.append(row)
    rows += closed_rows(data, args.closed, args.hold_label, args.incident_label, args.bot_login)

    order = [
        "SUSPECT_CLOSE",
        "VERIFY_CLOSED",
        "DONE_NOT_CLOSED",
        "DECIDED",
        "VETOED",
        "OFF_MILESTONE",
        "VERIFY_DUE",
        "CHECK_FAILED",
        "ASSIGN_DUE",
        "HANDOFF_DUE",
        "NO_ASSIGNEE",
        "UNBLOCKED",
        "UNFILLED",
        "MALFORMED_DEPENDS",
        "CYCLE",
        "SPEC_REFUSED",
        "REVISIT",
        "NEW",
        "NEEDS_PR",
        "IN_PROGRESS",
        "WITH_PERSON",
        "BLOCKED",
        "TRIAGED",
        "POSTPONED",
        "UPSTREAM",
        "NEEDS_DECISION",
        "UNTRUSTED",
    ]
    rows.sort(key=lambda r: (order.index(r["state"]), -r["number"]))
    for r in rows:
        if args.json:
            print(json.dumps(r, sort_keys=True))
        else:
            print(f"#{r['number']:<5} {r['state']:<16} {r['title'][:70]}" + (f"  [{r['note']}]" if r["note"] else ""))
    if args.wip is not None:
        room = wip_room(rows, args.wip, frozenset(people), frozenset(busy))
        if args.json:
            print(json.dumps(room, sort_keys=True))
        else:
            ready = " ".join(f"#{n}" for n in room["ready"]) or "none"
            print(f"WIP {room['wip']}: {room['in_progress']} in progress, room for {room['room']}; ready: {ready}")
    return 1 if any(r["state"] in ACTION for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
