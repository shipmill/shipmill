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
  AGENT_DRAFT      with --bot-login, every linked open PR is a draft the --bot-login
                   authored (D-67, #914), none labelled needs-decision: no session owns
                   it any more, so one marks it ready (github-pr-triage). The note names
                   each as #N:draft
  AGENT_DRAFT_HELD as AGENT_DRAFT, with one labelled needs-decision, #N:draft(needs-decision):
                   its question may still wait (github-ship-watch's AGENT_DRAFT row reads
                   its comments). A person's draft, or a ready PR beside the drafts, reads
                   IN_PROGRESS
  DONE_NOT_CLOSED  a PR that closes it merged, none open, issue still open. A merged
                   "Part of #N" PR alone doesn't count: the rest of the issue is
                   still owed, so the issue reads as its other state. Nor does a
                   merged #N the --bot-login's comment whose first line is
                   <!-- shipmill:reverted #N by #R --> names (spec 079), while its
                   revert #R stands: open, the issue reads BLOCKED, "revert #R of
                   #N open", read right after IN_PROGRESS; merged, it reads its
                   other state (NEEDS_PR for a triaged implement), #N noted
                   #N:reverted. Once #R closed unmerged, #N counts again. The same
                   marker by anyone else, or without --bot-login, counts for nothing.
                   Nor does a merged closer while a hold BLOCKED reads (a Depends on
                   line, a hold comment, blockedBy, a sub-issue) is still open (#1492):
                   the issue reads as its holds say (BLOCKED, "children K/N closed"
                   for a parent). Once every hold closed, a parent with a "## Check"
                   reads VERIFY_DUE, CHECK_FAILED, or WITH_PERSON as below (spec 042)
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
                   paragraph doesn't hold on a link in another (#309). A status
                   comment (its first line <!-- shipmill:status -->, spec 090)
                   holds nothing. Or,
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
                   body depends on and whatever GitHub records holds it. With --home,
                   holds on other repos of the product are read with the read token,
                   and a hold on an item of the home it still can't read adds the
                   coordinator's note (below). Or, triaged or not, it is a build issue
                   (its body's first line "Builds part of spec S-NNN,
                   `docs/specs/NNN-<slug>.md`", as specs.py split writes it) of a spec
                   approved at notify (spec 067): a merged pull request labelled decided
                   that changed that file carries a decided comment whose first line is
                   <!-- shipmill:decided zone=accepted-spec until=<time> --> by the
                   --bot-login or an OWNER, MEMBER, or COLLABORATOR, and its veto window
                   is open: veto_hours (that comment's until= less its post time) from
                   the merge, never ending before until=. Its note starts "veto window of
                   #<PR> until <time>" (UTC), then the holds. An unanswered veto of that
                   pull request (as VETOED reads one) holds it whenever it came, its note
                   starting "#<PR> vetoed by @<login>": its take-up closes the build
                   issues. Once the window has passed it reads as it would without it.
                   The merged pull requests labelled decided and updated in the last 14
                   days are read in one more query, only when an open issue is a build
                   issue; one whose until= isn't a UTC time within 168 hours after its
                   comment exits 2
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
                   decide whether the issue still makes sense before resuming. A hold
                   that closed before the newest triage comment holds nothing: that
                   comment decided it again (#1493), and the issue reads by its other
                   rules (BLOCKED "labelled blocked", POSTPONED, or its verdict). A
                   sub-issue, a hold whose close time is unknown, one the newest
                   triage comment names, and a person's item's holds count
                   whenever they closed
  POSTPONED        has the postponed label. When its newest triage comment has a line
                   "Revisit on: `<path>`, `<path>`" (spec 061), its note is "waits on
                   <paths>"
  REVISIT          postponed before the newest stable tag: decide again. Stable means
                   the tag matches --stable-tag-regex (default: vX.Y.Z, no pre-release).
                   With a "Revisit on:" line, only when a file one of its paths matches
                   changed between the newest stable tag before the comment and the
                   newest stable tag ("postponed before <tag>; <file> changed"), read from
                   one `gh api repos/<repo>/compare/<base>...<newest>` per base tag, paged
                   with per_page=100. A path's ** matches across "/", * and ? within one
                   segment, anything else itself. No stable tag before the comment, or a
                   compare that lists 300 files (GitHub's cap), reads REVISIT as without
                   the line; a line that isn't backticked paths separated by commas
                   reads REVISIT at once, "revisit line unreadable: <the line>"
  TRIAGED          triaged, nothing pending (clarify, waiting on the reporter, ...). A
                   goal's plan (labelled goal-plan, spec 028) whose newest triage comment
                   is product intake's own, "Triage: **plan**", reads TRIAGED whatever the
                   rest of that comment says: the maintainer's answer moves it, not triage.
                   With --json its line carries "verdict", the bold word of its newest
                   triage comment when it is one the skills write (opportunity, feature,
                   clarify, needs a decision, plan, postponed, won't fix, duplicate,
                   upstream; spec 088), and no "verdict" otherwise
  NEEDS_DECISION   labelled needs-decision and its question has no reply: a headless
                   session asked the user and left it (references/needs-decision.md).
                   The question is the newest comment whose first line is the marker
                   <!-- shipmill:needs-decision --> by an OWNER, MEMBER, or COLLABORATOR,
                   or with --bot-login the newest such comment by that login, unless an
                   OWNER, MEMBER, or COLLABORATOR wrote a newer one (then there is no
                   question); a reply is a newer comment without the marker by an OWNER,
                   MEMBER, or COLLABORATOR (other than the --bot-login) that carries no
                   agent marker, <!-- shipmill:agent --> on any line (spec 050); a
                   deleted account's comment is never one. A marker comment by anyone
                   else never counts. A labelled issue with no question waits too, until
                   the label comes off
  DECIDED          labelled needs-decision and its question has a reply: act on the
                   reply and remove the label (references/needs-decision.md), after
                   which the issue reads its usual state. Read right after
                   NEEDS_DECISION, before any other state, so an answer that links an
                   open issue doesn't read BLOCKED (#309). An issue with the label
                   off reads DECIDED too, its note ending "relayed", where it would
                   read NEW, NEEDS_PR, or TRIAGED, when a relay by the --bot-login
                   came after its question and no triage comment after the relay: a
                   comment whose first line is "Decision by @<login>" or
                   "Decision by `@<login>`" (D-61), an answer given in a session. A
                   relay out of its grammar, as retro.py's parse_relay and
                   relay_refusal read it (D-93), reads RELAY_REFUSED instead
  RELAY_REFUSED    the label is off and a relay by the --bot-login came after its
                   question, no triage comment after it, but the relay is out of its
                   grammar (D-93), so it isn't counted (#1302): ask again by the
                   needs-decision protocol, with the relay-refused marker and its visible
                   line under the zone line. Its note is "relay not counted: <reason>",
                   such as "format", as pr_gate.py words it. Once the new question is
                   posted the relay is older than it, so the item reads NEEDS_DECISION as
                   any asked item does
  VETOED           labelled decided (spec 030, a decision taken at notify) and a veto
                   came after its first decided marker, the comment whose first line is
                   <!-- shipmill:decided ... --> by the --bot-login or an OWNER, MEMBER,
                   or COLLABORATOR, with no newer <!-- shipmill:veto-handled ... -->
                   comment by such an author answering it: take the veto up
                   (references/needs-decision.md). A veto is a comment by an OWNER,
                   MEMBER, or COLLABORATOR other than the --bot-login whose first word is
                   "veto" in any case; an outsider's, a deleted account's, one carrying
                   the agent marker, or a "veto" further into a comment never counts.
                   A relay counts as the veto of the maintainer it names (D-103, #1482):
                   a comment by the --bot-login whose first line is `Decision by @<login>`
                   naming a user the --role maintainer flag gives, in retro.py's relay
                   grammar (D-93), whose answer line is `own: veto [<text>]` or starts with
                   the word veto; its note names that login. Without --role, no relay counts.
                   Read right after DECIDED, before any other state; an
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
  UPSTREAM_UNOWNED an UPSTREAM report without --home that waits on nobody (#1487): no
                   assignee and no link to an issue in another repo (a Depends on line, a
                   blocked-by relation, or a sub-issue naming one; a link in its own repo
                   routes it nowhere). Its note is "no coordinator: waits for the
                   maintainer to report it where it belongs", with "asks the maintainer"
                   as UPSTREAM's. Never an action; fleet.py queue lists it as the
                   maintainer's until it is linked or assigned. With --home the
                   coordinator's ROUTE_DUE takes it up, so it reads UPSTREAM
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
roles to the union of theirs. After UNTRUSTED, UPSTREAM, NEEDS_DECISION, DECIDED, and VETOED,
it reads:
  STALE_HANDOFF    its sub-issue parent (in any repo, read in the same query) is closed:
                   the work it was handed for is done or dropped, so close it, or say why
                   it still waits on its person (#1313). Its note is "parent
                   owner/repo#N closed". A comment created after the parent's close whose
                   first line is <!-- shipmill:still-waits -->, by the --bot-login or an
                   OWNER, MEMBER, or COLLABORATOR without the agent marker (D-62), ends it;
                   a reopen and a new close of the parent re-arm it. Read before
                   OFF_MILESTONE and every state below, and an action
After that and OFF_MILESTONE, it reads NO_ASSIGNEE (without --role) or ASSIGN_DUE (with it), else
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
                   first @login past that line, bare or in a code span (`@login`, D-61),
                   or on its author. Its note is "check waiting
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
                   COLLABORATOR or the --bot-login: run its check. Also any other
                   issue (not a person's item, not labelled upstream) closed as
                   completed with a "## Check" section by a pull request or a commit
                   (D-76), and a parent (an issue with a sub-issue) closed so by the
                   --bot-login too (spec 042), with no such verified comment after its
                   last close: never SUSPECT_CLOSE. One a person closed by hand reads
                   as any issue does

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

With --json, an open issue whose body names a spec file, docs/specs/NNN-<slug>.md (a link
to it included), carries "specs", those paths in the order the body names them, each once,
whatever its state: github-ship-watch's SPEC_UNSPLIT reads it as following the spec (spec
053) without reading the issue again. A line without such a path has no "specs".

With --label LABEL (repeatable), only the open issues carrying any of the labels are read
and classified, the recently closed ones as without it: shipmill gate's tier 4 reads the
items labelled needs-decision or decided this way (spec 046).

With --wip N (a work-in-progress limit, such as the config's [agents] wip), a last
line says how many issues are IN_PROGRESS, AGENT_DRAFT, or AGENT_DRAFT_HELD (counting an
OFF_MILESTONE one with an open PR), the room left under N, and the issues
ready to start (NEEDS_PR or UNBLOCKED), oldest first; with --json, as one JSON object.
A person's item never counts as in progress or ready: the limit is on agents' work. The
issues of an expedite outcome (spec 070: an open opportunity labelled planned and expedite,
the expedite label added by a person and no fixed-date label a person added beside it, and
each open issue whose sub-issue parent it is) come first among the ready ones, and count in
progress like any other; their label events are read in one more query, only when an open
issue carries opportunity, planned, and expedite.

--bot-login names the login shipmill's sessions write as (an App's <slug>[bot]). --home
names the product's home repo, the config's [product] home, as owner/name (letters, digits,
".", "-", or "_" on each side; anything else exits 2). It words UPSTREAM's note, and in a
component (a repo other than the home) it reads the product's other repos (spec 065, D-84):
each hold on an item of another repo that plain gh read no state for is read again through
`shipmill gh --product <repo> api graphql`, run as `uvx shipmill==<the plugin's version>`
(spec 031), one call per owner, its repo the home for the home's owner, else that owner's
first repo among the holds. A hold read so reads as any other: BLOCKED while open, UNBLOCKED
once closed (:not_planned for one closed as not planned). A read that fails (a non-zero exit
without a GraphQL answer, or no node for the item) leaves the hold :unknown, counted as open,
with one stderr note; when such a hold still open is on an item of the home, BLOCKED's note
ends " | the coordinator's hold on the home OWNER/NAME: waits for the coordinator, ask
nobody" (D-60, #773): the session leaves the item and asks nobody, and the state stays
BLOCKED. Without --home, or with --home naming the repo itself, no `shipmill gh` runs. No
uvx, or a broken plugin.json, when a read is due exits 2.

Exit 0 when nothing needs action, 1 when any issue is NEW, NEEDS_PR, UNBLOCKED, UNFILLED,
MALFORMED_DEPENDS, CYCLE, SPEC_REFUSED, REVISIT, DONE_NOT_CLOSED, DECIDED, RELAY_REFUSED, VETOED, SUSPECT_CLOSE,
HANDOFF_DUE, STALE_HANDOFF,
VERIFY_DUE, NO_ASSIGNEE, ASSIGN_DUE, VERIFY_CLOSED, OFF_MILESTONE, or AGENT_DRAFT (never for NEEDS_DECISION,
UNTRUSTED, UPSTREAM, UPSTREAM_UNOWNED, WITH_PERSON, or AGENT_DRAFT_HELD),
1 too when any is CHECK_FAILED (spec 042), 2 on bad input (an issue with more than 100
labels) or a gh failure. It pages past 20 open issues and an issue's 50 comments, 50
cross-references, 50 blocking issues, or 50 sub-issues, and back through tags to the
newest stable one, with one query when nothing is capped. A page GitHub rejects for its
resource limits is asked again at half the size, down to 10 items; one rejected at 10
fails with one error line. When GitHub's schema has no blockedBy, subIssues, or parent (an
undefinedField error naming one, such as a GitHub Enterprise Server without issue
dependencies), it classifies on the text holds alone, with no OFF_MILESTONE or STALE_HANDOFF,
and prints one "note: native relations unavailable: <first error line>" line to stderr; any other gh error, an error
on one issue's relations too, still exits 2. Needs the gh
CLI, authenticated. Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
import threading
from collections.abc import Callable, Container, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn
from urllib.parse import quote

# An open PR's isDraft, author, and labels tell the App's own draft (D-67, #914) from other work
PR_DRAFT = "isDraft author { __typename login } labels(first: 10) { nodes { name } }"
OPEN_TIMELINE = (
    """
          nodes {
            ... on CrossReferencedEvent {
              willCloseTarget isCrossRepository
              source { ... on PullRequest { number state title body """
    + PR_DRAFT
    + """ } }
            }
            ... on ConnectedEvent { subject { ... on PullRequest { number state """
    + PR_DRAFT
    + """ } } }
          }
"""
)
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
# A build issue's feature issue is its sub-issue parent, whose milestone it should share; a
# person's item reads STALE_HANDOFF once its parent closed (#1313), from the same field
# (spec 022): one field of the same query, never a call per issue
PARENT = "\n        parent { number state closedAt repository { nameWithOwner } milestone { title } }"
# The fields only a forge with sub-issues and dependencies has: refusing one falls back
NATIVE_SCHEMA = (*NATIVE_FIELDS, "parent")
# A decision taken at notify carries this label (spec 030); a veto comment updates the item, so
# a closed one is read back over VETO_WINDOW, in the first query, never with a call per issue
DECIDED_LABEL = "decided"
VETO_WINDOW = dt.timedelta(days=14)
UTC = dt.timezone.utc  # noqa: UP017 (dt.UTC needs 3.11)
# The first query's page of them; more are paged with VETOABLE_PAGE. GitHub charges a request
# for each one's comments, so a page of 50 alone would tip the first query to 3 points (#1459)
VETOABLE_FIRST = 20
VETOABLE_LATER = 50  # VETOABLE_PAGE's page, a query of its own that costs 1 point at 50
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

# Spec 067: the merged pull requests labelled decided, most recently updated first, with the
# files each changed and its comments, read only when an open issue is a spec's build issue:
# one query for them all, never a call per issue
DECIDED_PRS_PAGE = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    decided: pullRequests(states: MERGED, labels: [\""""
    + DECIDED_LABEL
    + """\"], first: $size, after: $cursor,
                          orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number mergedAt updatedAt
        files(first: 100) { pageInfo { hasNextPage endCursor } nodes { path } }
        comments(last: 50) { nodes { """
    + COMMENT
    + """ } }
      }
    }
  }
}
"""
)
PR_FILES_PAGE = """
query($owner: String!, $name: String!, $size: Int!, $number: Int!, $cursor: String!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      files(first: $size, after: $cursor) { pageInfo { hasNextPage endCursor } nodes { path } }
    }
  }
}
"""
PR_COMMENTS_PAGE = (
    """
query($owner: String!, $name: String!, $size: Int!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      comments(last: $size, before: $cursor) { pageInfo { hasPreviousPage startCursor } nodes { """
    + COMMENT
    + """ } }
    }
  }
}
"""
)

COMMENTS_CAP = 50  # comments(last: 50) in OPEN_ISSUE
CLOSED_COMMENTS_CAP = 5  # comments(last: 5) of a closed issue in CLOSED_AND_TAGS
# Each query's first page size, and what a page holds, for the error line. GitHub's rate limit
# charges a query by its worst case, not what it returns: a request for each connection per
# node of the connections it sits in, a point per 100 requests (#1459). An open issue's six
# connections cost 6 requests each, so a page of 100 cost 8 points a run even with 64 open
# issues; a page of 20 costs 2 in the first query and 1 in each later one. Older open issues
# carry more history too: a page of 100 tripped GitHub's resource limits on astral-sh/uv
OPEN_ISSUES_PAGE = 20
SIZES = {
    QUERY: OPEN_ISSUES_PAGE,
    TEXT_QUERY: OPEN_ISSUES_PAGE,
    OPEN_PAGE: OPEN_ISSUES_PAGE,
    TEXT_OPEN_PAGE: OPEN_ISSUES_PAGE,
    COMMENTS_PAGE: 100,
    TIMELINE_PAGE: 100,
    REFS_PAGE: 100,
    TAGS_PAGE: 100,
    VETOABLE_PAGE: VETOABLE_LATER,
    DECIDED_PRS_PAGE: 50,
    PR_FILES_PAGE: 100,
    PR_COMMENTS_PAGE: 100,
    **{query: 100 for query in NATIVE_PAGES.values()},
}
# A rejected page halves down to this floor; one that fails at the floor ends the run.
# At 10 open issues a page asks for a tenth of what a page of 100 did, so a page still
# rejected there holds an issue too heavy for any size, and pypa/pip's 957 issues would
# already take some 100 calls
MIN_PAGE = 10
RESOURCE_LIMITS = "RESOURCE_LIMITS_EXCEEDED"
Variables = dict[str, str | int]
# Runs one GraphQL query with its variables and returns the parsed JSON response
Runner = Callable[[str, Variables], dict[str, Any]]
Sizes = dict[str, int]
# Runs one command, such as `shipmill gh --product ... api graphql`, and returns its result
Execute = Callable[[list[str]], subprocess.CompletedProcess[str]]
# Where how a skill script runs the CLI is read from (spec 031): github-ship-watch's script
WATCH_STATE = Path(__file__).resolve().parents[2] / "github-ship-watch" / "scripts" / "watch_state.py"
# github-ship-watch's retro.py: the relay grammar's one reading (D-93), parse_relay and relay_refusal
RETRO = Path(__file__).resolve().parents[2] / "github-ship-watch" / "scripts" / "retro.py"
RELAY_NOT_COUNTED = "relay not counted: {reason}"  # as pr_gate.py words a relay out of its grammar


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
STATUS_MARKER = "<!-- shipmill:status -->"  # the first line of a session's status comment (spec 090)
# Spec 030's notify level: a decided comment's first line, `<!-- shipmill:decided zone=<id>
# until=<time> -->`, and the take-up of a veto's, `<!-- shipmill:veto-handled zone=<id> -->`
DECIDED_MARKER = re.compile(r"^<!-- shipmill:decided(?:\s[^>]*)?-->$")
VETO_HANDLED_MARKER = re.compile(r"^<!-- shipmill:veto-handled(?:\s[^>]*)?-->$")
VETO = re.compile(r"veto\b", re.IGNORECASE)  # a veto's first word, in any case
# An agent's record (spec 050, D-62): `shipmill gh` adds this line to every body it writes, so
# a body carrying it on any line, stripped, is never a person's reply or veto
AGENT_MARKER = re.compile(r"<!-- shipmill:agent(?:\s[^>]*)?-->")
GHOST = "ghost"  # the login GitHub gives a deleted account, and login() a null author
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
# A spec file an issue's body names (spec 053), specs.py's NAME under docs/specs/: a link to
# it reads too, a longer word around it doesn't
SPEC_FILE = re.compile(r"(?<![\w.-])docs/specs/\d{3,}-[a-z0-9]+(?:-[a-z0-9]+)*\.md(?![\w-]|\.\w)")
# A build issue specs.py split filed: its body's first line names the spec it builds part of
BUILDS = re.compile(r"\ABuilds part of spec S-\d{3,}, `(docs/specs/\d{3,}-[a-z0-9]+(?:-[a-z0-9]+)*\.md)`")
# Spec 067: a spec approved at notify carries this decided marker on its merged pull request
ACCEPTED_SPEC = re.compile(r"^<!-- shipmill:decided zone=accepted-spec until=(\S+) -->$")
LONGEST_WINDOW = dt.timedelta(hours=168)  # veto_hours' ceiling (spec 030)
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
# The --bot-login's comment on an issue `shipmill revert open` reopened (spec 079): merged #N,
# which closed it, is being reverted in #R
REVERTED_MARKER = re.compile(r"<!-- shipmill:reverted #(?P<pr>\d+) by #(?P<revert>\d+) -->")
# A trusted comment saying a parent's ## Check failed: it reads CHECK_FAILED until a hold closes after it (spec 042)
CHECK_FAILED_MARKER = "<!-- shipmill:check-failed -->"
# A trusted comment saying a person runs a parent's ## Check by hand, on the needs-decision answer
# "leave it open" (#740): it reads WITH_PERSON until a hold closes or a check-failed or verified comment follows
CHECK_WAITING_MARKER = "<!-- shipmill:check-waiting -->"
# A comment after a person's item's parent closed saying the item still waits on its person: it
# stops reading STALE_HANDOFF (#1313); by the --bot-login, or a trusted person without the agent marker (D-62)
STILL_WAITS_MARKER = "<!-- shipmill:still-waits -->"
# An @login, not an @org/team, bare or in a code span (`@login`, D-61): a backtick is no word character
MENTION = re.compile(r"(?<![\w@/-])@(" + LOGIN_PATTERN + r")(?![\w/-])")
# A relayed answer's first line (needs-decision.md, Answered in the session), the login bare or
# in a code span (D-61), as shipmill's credit.DECISION_BY reads it
DECISION_BY = re.compile(
    r"Decision by (?:@(" + LOGIN_PATTERN + r")(?=$|\s|[,;:)]|[.!?](?:\s|$))|`@(" + LOGIN_PATTERN + r")`(?![\w`-]))"
)
RELAYED = "relayed"  # the end of a DECIDED note read from a relay, which tier 6 of the watch keeps
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
    "RELAY_REFUSED",  # #1302: a relay out of its grammar with the label off: a session asks again
    "VETOED",
    "SUSPECT_CLOSE",
    "HANDOFF_DUE",
    "VERIFY_DUE",
    "CHECK_FAILED",
    "NO_ASSIGNEE",
    "ASSIGN_DUE",
    "VERIFY_CLOSED",
    "OFF_MILESTONE",
    "STALE_HANDOFF",  # #1313: a person's item whose sub-issue parent closed: close it or say why it waits
    "AGENT_DRAFT",  # D-67 (#914): the App's own draft, nothing open on it: a session resumes it
}
# Spec 088: the bold words a triage comment the skills write starts with, past the marker
# (references/comments.md), as a TRIAGED line's verdict; a word outside them names none, so no
# comment text reaches a line (D-16). shipmill's status.TRIAGE_VERDICTS keeps the same set
TRIAGE_VERDICTS = (
    "opportunity",
    "feature",
    "clarify",
    "needs a decision",
    "plan",
    "postponed",
    "won't fix",
    "duplicate",
    "upstream",
)
VERDICT_WORD = re.compile(r"\*\*([^*\n]{1,60})\*\*")
IN_FLIGHT = ("IN_PROGRESS", "AGENT_DRAFT", "AGENT_DRAFT_HELD")  # an open PR does its work: in progress under --wip
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


def graphql_cmd(query: str, variables: Variables) -> list[str]:
    """The ``gh api graphql`` command that runs one query with its variables"""
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        # -F sends an int as a number; -f keeps a string a string (a cursor, a numeric repo name)
        cmd += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    return cmd


def gh_graphql(query: str, variables: Variables, execute: Execute | None = None) -> dict[str, Any]:
    """The default runner: one ``gh api graphql`` call, run by ``execute`` (default: capture)"""
    proc = (execute or capture)(graphql_cmd(query, variables))
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
    native query asks), and is check_closable"""
    return (issue.get("subIssues") or {}).get("totalCount", 0) > 0 and check_closable(issue)


def check_closable(issue: dict[str, Any]) -> bool:
    """A closed issue whose close by a pull request or a commit owes its check (D-76), a parent
    or not: no person's item and no upstream report, closed as completed, with a ## Check section"""
    labels = {n["name"] for n in issue["labels"]["nodes"]}
    return (
        not person_item(issue)
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
    if checkable(issue) or check_closable(issue):
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
    ahead: Ahead | None = None,
) -> dict[str, Any]:
    """One query, plus follow-up pages only for the connections it reports as capped. When
    the forge refuses blockedBy or subIssues, one stderr note, then the text holds alone.
    ``now`` (default: the clock) dates the window of closed decided issues it reads back;
    ``labels`` (--label, spec 046) narrows the open issues to those carrying any of them.
    With ``ahead``, whose ``graphql`` is ``run``, each page's follow-up pages start at once,
    on its threads, while the open issues are still paged (#1469)"""
    owner, _, name = repo.partition("/")
    if not owner or not name or "/" in name:
        fail(f"repo must be owner/name, got {repo!r}")
    moment = now if now is not None else dt.datetime.now(UTC)
    since = (moment - VETO_WINDOW).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        return fetch_pages(
            owner, name, closed, stable_pattern, run, native=True, since=since, labels=labels, ahead=ahead
        )
    except NativeUnavailable as refused:
        sys.stderr.write(f"note: native relations unavailable: {refused}\n")
    return fetch_pages(owner, name, closed, stable_pattern, run, native=False, since=since, labels=labels, ahead=ahead)


def fetch_pages(
    owner: str,
    name: str,
    closed: int,
    stable_pattern: re.Pattern[str],
    run: Runner,
    native: bool,
    since: str,
    labels: Sequence[str] = (),
    ahead: Ahead | None = None,
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
    if ahead is not None:
        ahead.follow_ups(base, sizes, dig(issues, "nodes"), dig(data, "closed", "nodes"), dig(data, "vetoable"), since)
    seen: set[str] = set()
    while issues["pageInfo"]["hasNextPage"]:
        cursor = advance(issues["pageInfo"]["endCursor"], seen, "open issues")
        what = f"the open issues after the first {len(issues['nodes'])}"
        page = sized(run, later, {**base, "cursor": cursor}, sizes, what)["open"]
        if ahead is not None:
            ahead.follow_ups(base, sizes, dig(page, "nodes"), None, None, since)
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


def build_spec(issue: dict[str, Any]) -> str | None:
    """The spec file a build issue builds part of: its body's first line as specs.py split
    writes it, "Builds part of spec S-NNN, `docs/specs/NNN-<slug>.md`: ..."; None for any
    other issue, one that merely names a spec included"""
    found = BUILDS.match((issue.get("body") or "").lstrip())
    return found.group(1) if found else None


def pr_page(
    run: Runner, query: str, base: Variables, sizes: Sizes, number: int, field: str, cursor: str | None
) -> dict[str, Any]:
    """One page of a pull request's files or comments; with no cursor, its first (for comments,
    the newest)"""
    variables: Variables = {**base, "number": number}
    if cursor is not None:
        variables["cursor"] = cursor
    pull = sized(run, query, variables, sizes, f"the {field} of pull request #{number}").get("pullRequest")
    if pull is None:
        fail(f"pull request #{number} vanished while paging its {field}")
    page: dict[str, Any] = pull[field]
    return page


def accepted_spec_marks(pull: dict[str, Any], bot_login: str | None) -> list[tuple[dict[str, Any], str]]:
    """A pull request's decided comments for the zone accepted-spec (spec 067), oldest first,
    each with its until= text: the first line is the marker, by the --bot-login or an OWNER,
    MEMBER, or COLLABORATOR (D-16); anyone else's never counts"""
    marks = []
    for comment in pull["comments"]["nodes"]:
        found = ACCEPTED_SPEC.match(first_line(comment["body"]))
        author, association = login(comment.get("author")), str(comment.get("authorAssociation") or "NONE")
        if found is not None and trusted(author, association, bot_login):
            marks.append((comment, found.group(1)))
    return marks


def fetch_decided_prs(
    repo: str, bot_login: str | None, now: dt.datetime, run: Runner = gh_graphql
) -> list[dict[str, Any]]:
    """Spec 067: the merged pull requests labelled decided and updated in the last VETO_WINDOW
    (a merged pull request whose window is still open was updated in its last 168 hours), with
    every comment, and every file of one that carries an accepted-spec decided comment"""
    owner, _, name = repo.partition("/")
    base: Variables = {"owner": owner, "name": name}
    sizes = dict(SIZES)
    since = now - VETO_WINDOW
    pulls: list[dict[str, Any]] = []
    seen: set[str] = set()
    variables: Variables = dict(base)
    while True:
        page = sized(run, DECIDED_PRS_PAGE, variables, sizes, "the merged decided pull requests")["decided"]
        recent = [p for p in page["nodes"] if timestamp(p["updatedAt"]) >= since]
        pulls += recent
        if len(recent) < len(page["nodes"]) or not page["pageInfo"]["hasNextPage"]:
            break
        variables = {**base, "cursor": advance(page["pageInfo"]["endCursor"], seen, "merged decided pull requests")}
    for pull in pulls:
        number = pull["number"]
        if len(pull["comments"]["nodes"]) >= COMMENTS_CAP:
            comments = pr_page(run, PR_COMMENTS_PAGE, base, sizes, number, "comments", None)
            seen = set()
            while comments["pageInfo"]["hasPreviousPage"]:
                cursor = advance(comments["pageInfo"]["startCursor"], seen, f"comments on pull request #{number}")
                page = pr_page(run, PR_COMMENTS_PAGE, base, sizes, number, "comments", cursor)
                comments["nodes"] = page["nodes"] + comments["nodes"]
                comments["pageInfo"] = page["pageInfo"]
            pull["comments"] = comments
        if not accepted_spec_marks(pull, bot_login):
            continue
        files = pull["files"]
        seen = set()
        while files["pageInfo"]["hasNextPage"]:
            cursor = advance(files["pageInfo"]["endCursor"], seen, f"files of pull request #{number}")
            page = pr_page(run, PR_FILES_PAGE, base, sizes, number, "files", cursor)
            files["nodes"] = files["nodes"] + page["nodes"]
            files["pageInfo"] = page["pageInfo"]
    return pulls


def until_time(text: str, number: int) -> dt.datetime:
    """A decided comment's until=, a UTC time such as 2026-10-20T14:00:00Z, its seconds optional
    as the release's veto.py reads it (spec 030, spec 059)"""
    for shape in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%MZ"):
        try:
            return dt.datetime.strptime(text, shape).replace(tzinfo=UTC)
        except ValueError:
            continue
    fail(f"pull request #{number}'s decided comment has until={text}, not a UTC time such as 2026-10-20T14:00:00Z")


def window_hold(
    pull: dict[str, Any], bot_login: str | None, now: dt.datetime, maintainers: Container[str] = frozenset()
) -> str | None:
    """What a merged spec pull request approved at notify (an accepted-spec decided comment,
    spec 067) holds its build issues on, or None once nothing does. An unanswered trusted veto
    (a maintainer's relayed one too, D-103) holds them whenever it came: a veto never releases
    them, its take-up closes them. Else its veto window holds them, veto_hours from its merge:
    the newest such comment's until= less its post time is veto_hours, run from the merge, and
    never ending before until= itself"""
    marks = accepted_spec_marks(pull, bot_login)
    if not marks:
        return None  # approved at ask or by a person's merge: nothing to wait for
    number = pull["number"]
    who = vetoed(comment_tuples(pull), bot_login, maintainers)
    if who is not None:
        return f"#{number} vetoed by @{who}"
    comment, text = marks[-1]
    until = until_time(text, number)
    span = until - timestamp(comment["createdAt"])
    if not dt.timedelta(0) < span <= LONGEST_WINDOW:
        fail(f"pull request #{number}'s decided comment has until={text}, not within 168 hours after the comment")
    end = max(until, timestamp(pull["mergedAt"]) + span)
    if now >= end:
        return None
    return f"veto window of #{number} until {end.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}"


def veto_windows(
    repo: str,
    issues: list[dict[str, Any]],
    bot_login: str | None,
    now: dt.datetime | None = None,
    run: Runner = gh_graphql,
    maintainers: Container[str] = frozenset(),
) -> dict[int, str]:
    """Spec 067 (S-067-9): each open build issue held by its spec's approval at notify, as its
    BLOCKED note. The decided pull requests are read once, and only when an open issue is a
    build issue; ``now`` (default: the clock) is when the windows are read; ``maintainers``,
    whom a relayed veto may name (D-103)"""
    builds = {issue["number"]: build_spec(issue) for issue in issues}
    if not any(builds.values()):
        return {}
    moment = now if now is not None else dt.datetime.now(UTC)
    holds: dict[str, list[str]] = {}
    pulls = fetch_decided_prs(repo, bot_login, moment, run)
    for pull in sorted(pulls, key=lambda p: (p["mergedAt"], p["number"])):
        hold = window_hold(pull, bot_login, moment, maintainers)
        if hold is None:
            continue
        for path in dict.fromkeys(str(f["path"]) for f in pull["files"]["nodes"]):
            holds.setdefault(path, []).append(hold)
    return {n: " | ".join(holds[path]) for n, path in builds.items() if path is not None and path in holds}


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


def own_drafts(issue: dict[str, Any], bot_login: str | None) -> dict[int, bool]:
    """D-67 (#914): the linked open PRs that are drafts the --bot-login authored, each with
    whether it is labelled needs-decision (its question may still wait); none without
    --bot-login. A PR read without isDraft is no draft"""
    if bot_login is None:
        return {}
    found: dict[int, bool] = {}
    for node in issue["timelineItems"]["nodes"]:
        pr = (node.get("subject") if "subject" in node else node.get("source")) or {}
        if node.get("isCrossRepository") or pr.get("state") != "OPEN" or pr.get("isDraft") is not True:
            continue
        if not same_login(login(pr["author"]), bot_login):
            continue
        found[int(pr["number"])] = DECISION_LABEL in {n["name"] for n in pr["labels"]["nodes"]}
    return found


def merged_mentions(issue: dict[str, Any]) -> list[int]:
    """Same-repo merged PRs that mention the issue at all"""
    return sorted(
        n["source"]["number"]
        for n in issue["refs"]["nodes"]
        if not n.get("isCrossRepository") and n.get("source", {}).get("state") == "MERGED"
    )


def reverts(issue: dict[str, Any], bot_login: str | None) -> dict[int, int]:
    """Spec 079: each merged pull request #N that `shipmill revert open` reopened the issue
    over, with its revert #R, read from the --bot-login's comments whose first line is
    `<!-- shipmill:reverted #N by #R -->`, the newest per #N. None without --bot-login: the
    same marker by anyone else counts for nothing"""
    if bot_login is None:
        return {}
    found: dict[int, int] = {}
    for c in issue["comments"]["nodes"]:
        mark = REVERTED_MARKER.fullmatch(first_line(c["body"]))
        if mark is not None and same_login(login(c.get("author")), bot_login):
            found[int(mark["pr"])] = int(mark["revert"])
    return found


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
    #N right after one, which is one of repo's own (owner, name). The issue itself is never
    one, in any spelling (#1005): "#126 keeps waiting on #125" on #125 says what waits on it.
    A status comment, its first line STATUS_MARKER, holds nothing: its "waits on #12" is a
    session's progress, never a hold (spec 090)"""
    refs: dict[tuple[str, str, int], int] = {}
    for i, c in enumerate(issue["comments"]["nodes"]):
        if first_line(c["body"]) == STATUS_MARKER:
            continue
        for line in c["body"].splitlines():
            for sentence in SENTENCE.split(line):
                if HOLD.search(sentence):
                    refs.update(((m["owner"], m["name"], int(m["num"])), i) for m in UPSTREAM.finditer(sentence))
                    refs.update(((*repo, int(m["num"])), i) for m in SAME_REPO.finditer(sentence))
    own = fold((*repo, int(issue["number"])))
    return {r: i for r, i in refs.items() if fold(r) != own}


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
    proc = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={states_query(ordered)}"], capture_output=True, text=True, check=False
    )
    return read_states(json.loads(proc.stdout or "{}").get("data") or {}, ordered)


def states_query(ordered: list[Ref]) -> str:
    """One query reading each ref's state, the i-th under alias r<i>"""
    parts = [
        f'r{i}: repository(owner: "{o}", name: "{n}") {{ issueOrPullRequest(number: {k}) '
        "{ __typename ... on Issue { state stateReason closedAt } ... on PullRequest { state closedAt } } }"
        for i, (o, n, k) in enumerate(ordered)
    ]
    return "{" + " ".join(parts) + "}"


def read_states(data: dict[str, Any], ordered: list[Ref]) -> tuple[dict[Ref, str], dict[Ref, str]]:
    """states_query's answer: each ref's state (UNKNOWN when no node came back) and when it closed"""
    states = {}
    closes = {}
    for i, ref in enumerate(ordered):
        node = (data.get(f"r{i}") or {}).get("issueOrPullRequest") or {}
        states[ref] = ref_state(node)
        if node.get("closedAt"):
            closes[ref] = str(node["closedAt"])
    return states, closes


def product_reads(states: dict[Ref, str], repo: tuple[str, str], home: str | None) -> list[Ref]:
    """The holds a component reads again through `shipmill gh --product` (spec 065): those on
    another repo's item that plain gh read no state for. None without --home, or with --home
    naming the checkout's own repo: there nothing changes (S-065-10)"""
    if home is None or home.lower() == "/".join(repo).lower():
        return []
    own = (repo[0].lower(), repo[1].lower())
    return sorted(r for r, state in states.items() if fold(r)[:2] != own and state == "UNKNOWN")


def product_states(
    refs: list[Ref], home: str, gh: Sequence[str], execute: Execute
) -> tuple[dict[Ref, str], dict[Ref, str]]:
    """The states of holds on other repos' items, read with the read token (spec 065, D-84):
    one `<gh> --product <repo> api graphql` per owner, its repo the home when the owner is the
    home's, else the owner's first repo among the refs. A read that fails (a non-zero exit
    without a GraphQL answer, such as `shipmill gh`'s exit 2 for a repo outside the product)
    leaves its holds UNKNOWN, as before (S-065-9), with one stderr note; a node GitHub doesn't
    return stays UNKNOWN too"""
    owners: dict[str, list[Ref]] = {}
    for ref in sorted(refs):
        owners.setdefault(ref[0].lower(), []).append(ref)
    states: dict[Ref, str] = {}
    closes: dict[Ref, str] = {}
    for owner, group in owners.items():
        via = home if owner == home.partition("/")[0].lower() else f"{group[0][0]}/{group[0][1]}"
        proc = execute([*gh, "--product", via, "api", "graphql", "-f", f"query={states_query(group)}"])
        try:
            response = json.loads(proc.stdout or "")
        except ValueError:
            response = None
        answered = isinstance(response, dict) and (proc.returncode == 0 or bool(response.get("errors")))
        if not answered or not isinstance(response, dict):
            said = (proc.stderr or "").strip().splitlines()
            sys.stderr.write(
                f"note: shipmill gh --product {via} exited {proc.returncode}"
                + (f": {said[0]}" if said else "")
                + f"; {len(group)} hold(s) of {owner} read unknown\n"
            )
            continue
        found, closed = read_states(response.get("data") or {}, group)
        states.update(found)
        closes.update(closed)
    return states, closes


def watch_module() -> ModuleType:
    """github-ship-watch's watch_state.py, loaded once, for how a skill script runs the CLI"""
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


def retro_module() -> ModuleType:
    """github-ship-watch's retro.py, loaded once, which imports metrics from its own folder, as
    when it runs from there (pr_gate.py's retro())"""
    loaded = sys.modules.get("shipmill_retro")
    if loaded is not None:
        return loaded
    spec = importlib.util.spec_from_file_location("shipmill_retro", RETRO)
    if spec is None or spec.loader is None:
        fail(f"can't load {RETRO}")
    rt = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = rt  # its dataclasses look their module up by name
    folder = str(RETRO.parent)
    sys.path.insert(0, folder)
    try:
        spec.loader.exec_module(rt)
    finally:
        sys.path.remove(folder)
    return rt


def capture(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


AHEAD_WORKERS = 8  # gh calls in flight at once: well under GitHub's limit on concurrent requests


def dig(value: Any, *keys: str) -> Any:
    """``value[k1][k2]...``, or None where a step isn't a dict holding the key"""
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def moment_or_none(text: Any) -> dt.datetime | None:
    """``timestamp`` that never fails: None for a time it would refuse"""
    if not isinstance(text, str):
        return None
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def ahead_key(cmd: list[str]) -> tuple[object, ...]:
    """A command's key among the started ones: a GraphQL call's variables in any order"""
    if cmd[:3] != ["gh", "api", "graphql"]:
        return tuple(cmd)
    rest = cmd[5:]  # graphql_cmd's flag and name=value pairs
    return (*cmd[:5], *sorted(zip(rest[0::2], rest[1::2], strict=True)))


class Ahead:
    """Calls started early on worker threads (#1469), whose answers the run takes in its own
    order, as an Execute: a command started ahead returns its started call's result, any other
    runs then. A worker only runs the command, so every error, stderr line, and exit code comes
    from the run's own reading of the answer, in the order it reads them; a call started ahead
    that the run never asks for changes nothing it prints"""

    def __init__(self, execute: Execute = capture, workers: int = AHEAD_WORKERS) -> None:
        self.execute = execute
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.lock = threading.Lock()
        self.started: dict[tuple[object, ...], Future[subprocess.CompletedProcess[str]]] = {}

    def start(self, cmd: list[str], then: Callable[[subprocess.CompletedProcess[str]], None] | None = None) -> None:
        """Start ``cmd`` unless it is started; ``then`` reads its result on the worker, to start more"""

        def work() -> subprocess.CompletedProcess[str]:
            proc = self.execute(cmd)
            if then is not None:
                then(proc)
            return proc

        key = ahead_key(cmd)
        with self.lock:
            if key not in self.started:
                self.started[key] = self.pool.submit(work)

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        with self.lock:
            future = self.started.pop(ahead_key(cmd), None)
        return self.execute(cmd) if future is None else future.result()

    def graphql(self, query: str, variables: Variables) -> dict[str, Any]:
        """A Runner: gh_graphql through the calls started ahead"""
        return gh_graphql(query, variables, self)

    def start_graphql(self, query: str, variables: Variables) -> None:
        self.start(graphql_cmd(query, variables))

    def next_page(self, query: str, base: Variables, sizes: Sizes, issue: Any, field: str) -> None:
        """complete_refs' first call for an issue's connection, when its page says there is more"""
        info = dig(issue, field, "pageInfo")
        cursor = dig(info, "endCursor")
        if dig(info, "hasNextPage") is True and isinstance(cursor, str) and cursor:
            self.start_graphql(query, {**base, "number": issue["number"], "cursor": cursor, "size": sizes[query]})

    def newest_comments(self, base: Variables, sizes: Sizes, issue: Any) -> None:
        """issue_page's first call for an issue's comments, the newest"""
        self.start_graphql(COMMENTS_PAGE, {**base, "number": issue["number"], "size": sizes[COMMENTS_PAGE]})

    def follow_ups(self, base: Variables, sizes: Sizes, opened: Any, closed: Any, vetoable: Any, since: str) -> None:
        """Start the first follow-up call fetch_pages makes for each connection a page reports
        as capped, by the rules it reads them by: an open issue's comments, cross-references,
        and native relations, a closed issue's cross-references and comments since its close,
        and the closed decided issues' next page and comments"""
        for issue in numbered(opened):
            if len(dig(issue, "comments", "nodes") or ()) >= COMMENTS_CAP:
                self.newest_comments(base, sizes, issue)
            self.next_page(TIMELINE_PAGE, base, sizes, issue, "timelineItems")
            for field, query in NATIVE_PAGES.items():
                self.next_page(query, base, sizes, issue, field)
        for issue in numbered(closed):
            self.next_page(REFS_PAGE, base, sizes, issue, "refs")
            if closed_comments_due(issue):
                self.newest_comments(base, sizes, issue)
        for issue in numbered(dig(vetoable, "nodes")):
            if len(dig(issue, "comments", "nodes") or ()) >= COMMENTS_CAP:
                self.newest_comments(base, sizes, issue)
        cursor = dig(vetoable, "pageInfo", "endCursor")
        if dig(vetoable, "pageInfo", "hasNextPage") is True and isinstance(cursor, str) and cursor:
            self.start_graphql(VETOABLE_PAGE, {**base, "cursor": cursor, "since": since, "size": sizes[VETOABLE_PAGE]})


def numbered(nodes: Any) -> list[dict[str, Any]]:
    """The nodes of a page that are issues with a number, for the calls started ahead"""
    if not isinstance(nodes, list):
        return []
    return [n for n in nodes if isinstance(n, dict) and type(n.get("number")) is int]


def closed_comments_due(issue: dict[str, Any]) -> bool:
    """Whether complete_closed_comments reads a closed issue's comments again, read without
    failing: False where it would fail first, or on an answer of another shape"""
    labels = dig(issue, "labels", "nodes")
    if not isinstance(labels, list) or not all(isinstance(n, dict) and "name" in n for n in labels):
        return False
    if "stateReason" not in issue or not isinstance(issue.get("body"), (str, type(None))):
        return False
    if checkable(issue) or check_closable(issue):
        return True
    nodes = dig(issue, "comments", "nodes")
    events = dig(issue, "timelineItems", "nodes")
    if not isinstance(nodes, list) or len(nodes) < CLOSED_COMMENTS_CAP or not isinstance(events, list) or not events:
        return False
    newest, closed = moment_or_none(dig(nodes[0], "createdAt")), moment_or_none(dig(events[0], "createdAt"))
    return newest is not None and closed is not None and newest > closed


def product_gh(here: Path, execute: Execute = capture) -> tuple[list[str], Execute]:
    """`shipmill gh` as upstream_state.py runs it: `uvx shipmill==<the plugin's version>
    --repo <the checkout> gh` (spec 031), each call run once more with uv's index refreshed
    when uv found no such version (#597). A broken plugin.json, or no uvx, exits 2"""
    ws = watch_module()
    try:
        cli: list[str] = ws.shipmill_cli()
    except ws.Refused as refused:
        fail(str(refused).removeprefix("error: "))
    top = next((folder for folder in (here, *here.parents) if (folder / ".git").exists()), here)

    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            proc: subprocess.CompletedProcess[str] = ws.pinned(cmd, execute)
        except FileNotFoundError:
            fail("uvx is not on PATH: --home in a component reads its product's holds with `shipmill gh --product`")
        return proc

    return [*cli, "--repo", str(top), "gh"], run


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


# A postpone comment's line naming the paths its decision depends on (spec 061):
# Revisit on: `src/shipmill/gate.py`, `skills/github-ship-watch/**`
REVISIT_LINE = re.compile(r"^[ \t]*Revisit on:(?P<paths>.*)$")
REVISIT_PATHS = re.compile(r"[ \t]*`[^`]+`(?:[ \t]*,[ \t]*`[^`]+`)*[ \t]*")
BACKTICKED = re.compile(r"`([^`]+)`")
UNREADABLE_CUT = 100  # the unreadable line, as its note quotes it
COMPARE_PAGE = 100  # per_page of GitHub's compare
COMPARE_FILES_CAP = 300  # GitHub's compare lists at most this many changed files


def revisit_line(body: str) -> tuple[list[str] | None, str] | None:
    """The paths a triage comment's ``Revisit on:`` lines name, outside a ``` or ~~~ fence,
    with the first line, or None with no such line. A line that isn't backticked paths
    separated by commas reads unreadable: (None, that line)"""
    paths: list[str] = []
    first = ""
    fenced = False
    for line in body.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        found = None if fenced else REVISIT_LINE.match(line)
        if found is None:
            continue
        first = first or line.strip()
        if not REVISIT_PATHS.fullmatch(found["paths"]):
            return None, line.strip()
        paths += [p for p in BACKTICKED.findall(found["paths"]) if p not in paths]
    return (paths, first) if first else None


def glob_regex(path: str) -> re.Pattern[str]:
    """A ``Revisit on:`` path as a regex (S-061-18): ``**`` any run of characters, ``/``
    included, ``*`` any run without ``/``, ``?`` one character other than ``/``, anything else
    itself. fnmatch's ``*`` crosses ``/`` and its ``[...]`` is a class, so it isn't used"""
    parts = []
    i = 0
    while i < len(path):
        if path.startswith("**", i):
            parts.append(".*")
            i += 2
        elif path[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif path[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(path[i]))
            i += 1
    return re.compile("".join(parts), re.DOTALL)


def glob_match(path: str, filename: str) -> bool:
    return glob_regex(path).fullmatch(filename) is not None


class Revisits:
    """What a postponed issue's ``Revisit on:`` line is read against (spec 061): the newest
    stable tag created before its comment, paging back through older tags only when none is in
    hand, and the files changed from that tag to the newest stable one, one compare per base
    tag in a run, whatever the number of issues that share it"""

    def __init__(
        self,
        owner: str,
        name: str,
        tags: dict[str, Any],
        pattern: re.Pattern[str] = STABLE,
        run: Runner = gh_graphql,
        execute: Execute = capture,
    ) -> None:
        self.owner = owner
        self.name = name
        self.tags = tags  # the first query's tags connection, oldest first; paged further back here
        self.pattern = pattern
        self.run = run
        self.execute = execute
        self.sizes = dict(SIZES)
        self.seen: set[str] = set()
        self.compares: dict[tuple[str, str], list[str] | None] = {}

    def base(self, moment: dt.datetime) -> str | None:
        """The newest stable tag created before ``moment``, or None when there is none"""
        while True:
            before = latest_stable([t for t in self.tags["nodes"] if tag_date(t, moment)], self.pattern)
            if before is not None or not self.tags["pageInfo"]["hasPreviousPage"]:
                return None if before is None else before[1]
            cursor = advance(self.tags["pageInfo"]["startCursor"], self.seen, "tags")
            variables: Variables = {"owner": self.owner, "name": self.name, "cursor": cursor}
            page = sized(self.run, TAGS_PAGE, variables, self.sizes, "older tags")["tags"]
            self.tags["nodes"] = page["nodes"] + self.tags["nodes"]
            self.tags["pageInfo"] = page["pageInfo"]

    def changed(self, base: str, newest: str) -> list[str] | None:
        """The files changed from ``base`` to ``newest``, a renamed file under both names, or
        None when GitHub's compare can't list every one (it lists at most 300)"""
        key = (base, newest)
        if key not in self.compares:
            self.compares[key] = self.compare(base, newest)
        return self.compares[key]

    def compare_url(self, base: str, newest: str, page: int) -> str:
        where = f"{quote(base, safe='')}...{quote(newest, safe='')}"
        return f"repos/{self.owner}/{self.name}/compare/{where}?per_page={COMPARE_PAGE}&page={page}"

    def compare(self, base: str, newest: str) -> list[str] | None:
        files: list[str] = []
        listed = 0
        page = 1
        while True:
            url = self.compare_url(base, newest, page)
            proc = self.execute(["gh", "api", url])
            if proc.returncode != 0:
                sys.stderr.write(proc.stderr)
                fail(f"gh api {url} exited {proc.returncode}")
            try:
                answer = json.loads(proc.stdout)
            except ValueError:
                answer = None
            nodes = answer.get("files", []) if isinstance(answer, dict) else None
            if not isinstance(nodes, list) or not all(isinstance(f, dict) and f.get("filename") for f in nodes):
                fail(f"gh api {url} answered no compare with a list of files")
            listed += len(nodes)
            for f in nodes:
                files += [str(f["filename"])] + ([str(f["previous_filename"])] if f.get("previous_filename") else [])
            if listed >= COMPARE_FILES_CAP:
                return None
            # GitHub lists the files on the first page; a full page may still have more after it
            if len(nodes) < COMPARE_PAGE:
                return files
            page += 1

    def start(self, ahead: Ahead, issues: list[dict[str, Any]], marker: str, postponed: str) -> None:
        """Start, on ``ahead``'s threads, the compares postponed_state is likely to read (#1469):
        each postponed issue's whose newest triage comment has a readable ``Revisit on:`` line
        and is older than the newest stable tag, from the newest stable tag in hand before it.
        Read without failing: an issue whose answer postponed_state would fail on, or whose base
        tag needs older tags paged, starts none, and is read as before"""
        stable = stable_in_hand(dig(self.tags, "nodes"), self.pattern)
        if stable is None:
            return
        for issue in issues:
            labels = dig(issue, "labels", "nodes")
            if not isinstance(labels, list) or postponed not in {dig(n, "name") for n in labels}:
                continue
            comments = dig(issue, "comments", "nodes")
            triaged = [
                c
                for c in (comments if isinstance(comments, list) else [])
                if isinstance(dig(c, "body"), str) and c["body"].lstrip().startswith(marker)
            ]
            recorded = revisit_line(triaged[-1]["body"]) if triaged else None
            when = moment_or_none(dig(triaged[-1], "createdAt")) if triaged else None
            if recorded is None or recorded[0] is None or when is None or not when < stable[0]:
                continue
            nodes = dig(self.tags, "nodes")
            before = stable_in_hand([t for t in nodes if (tag_moment(t) or when) < when], self.pattern)
            if before is not None:
                self.start_compare(ahead, before[1], stable[1], 1)

    def start_compare(self, ahead: Ahead, base: str, newest: str, page: int) -> None:
        """Start one page of a compare, and its next page once this one is full, as compare reads them"""

        def more(proc: subprocess.CompletedProcess[str]) -> None:
            if proc.returncode != 0:
                return
            try:
                answer = json.loads(proc.stdout)
            except ValueError:
                return
            nodes = dig(answer, "files")
            if isinstance(nodes, list) and len(nodes) >= COMPARE_PAGE and page * COMPARE_PAGE < COMPARE_FILES_CAP:
                self.start_compare(ahead, base, newest, page + 1)

        ahead.start(["gh", "api", self.compare_url(base, newest, page)], then=more)


def tag_moment(tag: Any) -> dt.datetime | None:
    """When a tag was created, as tag_date reads it, or None where it reads no time"""
    target = dig(tag, "target")
    if not isinstance(target, dict):
        return None
    tagger = target.get("tagger")
    date = (tagger.get("date") if isinstance(tagger, dict) else None) or target.get("committedDate")
    return moment_or_none(date)


def stable_in_hand(tags: Any, pattern: re.Pattern[str]) -> tuple[dt.datetime, str] | None:
    """latest_stable read without failing: None also where a stable tag's time doesn't read"""
    if not isinstance(tags, list):
        return None
    stable = []
    for tag in tags:
        name = dig(tag, "name")
        if not isinstance(name, str) or not pattern.match(name):
            continue
        moment = tag_moment(tag)
        if moment is None:
            return None
        stable.append((moment, name))
    return max(stable) if stable else None


def tag_date(tag: dict[str, Any], moment: dt.datetime) -> bool:
    """Whether a tag was created before ``moment``; an undated tag never is"""
    target = tag["target"] or {}
    date = (target.get("tagger") or {}).get("date") or target.get("committedDate")
    return bool(date) and timestamp(date) < moment


def postponed_state(
    triaged: list[dict[str, Any]], stable: tuple[dt.datetime, str] | None, note: str, revisits: Revisits | None
) -> tuple[str, str]:
    """A postponed issue's REVISIT or POSTPONED (spec 061). Without a ``Revisit on:`` line in
    its newest triage comment, REVISIT once that comment is older than the newest stable tag;
    with one, only when a file it names changed between the newest stable tag before the
    comment and the newest one. No such base tag, a compare that can't list every file, or no
    ``revisits`` to read it with, reads REVISIT as without the line; an unreadable line reads
    REVISIT so a session rewrites it"""
    recorded = revisit_line(triaged[-1]["body"]) if triaged else None
    if recorded is not None and recorded[0] is None:
        return "REVISIT", f"revisit line unreadable: {recorded[1][:UNREADABLE_CUT]}"
    # Comments come oldest first: a re-decision after the tag clears REVISIT
    when = timestamp(triaged[-1]["createdAt"]) if triaged else None
    if stable is not None and when is not None and when < stable[0]:
        said = f"postponed before {stable[1]}"
        if recorded is None or revisits is None:
            return "REVISIT", said
        base = revisits.base(when)
        files = None if base is None else revisits.changed(base, stable[1])
        if files is None:
            return "REVISIT", said
        paths = recorded[0] or []
        hit = next((f for f in files if any(glob_match(p, f) for p in paths)), None)
        if hit is not None:
            return "REVISIT", f"{said}; {hit} changed"
    if recorded is not None:
        waits = f"waits on {', '.join(recorded[0] or [])}"
        return "POSTPONED", f"{waits} {note}" if note else waits
    return "POSTPONED", note


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
    home: str | None = None,
    revisits: Revisits | None = None,
    window: str | None = None,
) -> tuple[str, str]:
    """An open issue's state once gated found none; ``closes`` says when each closed hold
    closed, which a person's item (labelled human or role:<name>) reads its hand-off against,
    and before which any other issue's newest triage comment takes a hold up (#1493).
    Without ``milestone``, the state OFF_MILESTONE hides (--wip counts one hiding IN_PROGRESS).
    ``roles``, the --role flags (None without them), turns NO_ASSIGNEE into ASSIGN_DUE.
    ``cycle`` is the issue's loop when it is on a cycle (cycles), with the issue on it that
    breaks the loop, if any: it reads CYCLE, or BLOCKED waiting on that issue (spec 041).
    ``home``, the --home, adds the coordinator's note to a BLOCKED one held on an item of the
    home this session can't read (home_hold_note, D-60). ``revisits`` reads a postponed
    issue's ``Revisit on:`` line against the tags' changes (spec 061); without it, such an
    issue reads REVISIT on every stable tag, as one without the line does. ``window``, a build
    issue's hold by its spec's approval at notify (veto_windows, spec 067), reads BLOCKED, its
    note first, whether triaged or not; without it the issue reads as before. A person's item
    whose sub-issue parent closed reads STALE_HANDOFF before any of these (stale_handoff, #1313)"""
    stale = stale_handoff(issue, bot_login)
    if stale is not None:
        return stale
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
    # Spec 079: a merged #N whose revert #R the --bot-login reopened the issue over closes it
    # no more while #R stands (open or merged); once #R closed unmerged, #N counts again
    standing = {
        n: (r, states.get((*repo, r), "UNKNOWN"))
        for n, r in reverts(issue, bot_login).items()
        if states.get((*repo, r)) != "CLOSED_UNMERGED"
    }
    # #R, titled Revert "<#N's title>", carries any closing keyword #N's title had: it is no
    # work on the issue, open or merged
    undoing = {r for r, _ in standing.values()}
    prs = [p for p in linked_prs(issue) if p[0] not in undoing]
    open_prs = [n for n, s, _ in prs if s == "OPEN"]
    merged = [n for n, s, whole in prs if s == "MERGED" and whole and n not in standing]
    note = " ".join(
        f"#{n}:{'reverted' if s == 'MERGED' and n in standing else s.lower()}" + ("" if whole else "(part)")
        for n, s, whole in prs
    )
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
    drafts = own_drafts(issue, bot_login) if open_prs and not human else {}
    if open_prs and not human and set(open_prs) <= set(drafts):
        # D-67 (#914): only the App's own drafts are open, and no session owns them any more
        shown = " ".join(f"#{n}:draft" + ("(needs-decision)" if drafts[n] else "") for n in sorted(open_prs))
        return ("AGENT_DRAFT_HELD" if any(drafts[n] for n in open_prs) else "AGENT_DRAFT"), shown
    if open_prs and not human:
        return "IN_PROGRESS", note
    pending = [f"revert #{r} of #{n} {s.lower()}" for n, (r, s) in sorted(standing.items()) if s != "MERGED"]
    if pending and not human:
        # Spec 079: nothing builds the fix again until the revert lands
        return "BLOCKED", " | ".join(pending)
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
    # A refused PR named before the newest triage comment was decided again: it holds nothing.
    # So does a hold that closed before that comment (#1493), save a sub-issue, which always
    # counts, a person's item's, whose hand-off starts at its newest hold's close, and one that
    # comment or a later one names, which put the hold on rather than took it up
    decided = timestamp(comments[verdict]["createdAt"]) if verdict >= 0 and not human else None
    taken = {
        r
        for r, i in named.items()
        if decided is not None
        and i < verdict
        and marks.get(r) != "(child)"
        and states.get(r) in CLOSED_STATES
        and r in closes
        and timestamp(closes[r]) < decided
    }
    waits = sorted(
        r for r, i in named.items() if (states.get(r) != "CLOSED_UNMERGED" or i >= verdict) and r not in taken
    )
    shown = " ".join(f"{o}/{n}#{k}:{states.get((o, n, k), '?').lower()}{marks.get((o, n, k), '')}" for o, n, k in waits)
    if children:
        closed = sum(1 for s in children if s in ("CLOSED", "NOT_PLANNED"))
        shown = f"children {closed}/{len(children)} closed {shown}"
    if merged and not human and all(states.get(r) in (*CLOSED_STATES, "CLOSED_UNMERGED") for r in waits):
        # #1492: a merged closer finishes the issue only once no hold is still open; a parent
        # with a ## Check runs it first (spec 042), with a hold open it reads as its holds say
        if children and CHECK.search(issue.get("body") or ""):
            return parent_check(comments, bot_login, [closes[r] for r in waits if r in closes], shown)
        return "DONE_NOT_CLOSED", note
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
    if window is not None:
        # Spec 067: no implementer starts while a veto of its spec's approval can still stop it
        return "BLOCKED", " | ".join([window, shown] if shown else [window])
    if waits or "blocked" in labels:
        if any(states.get(r) == "CLOSED_UNMERGED" for r in waits):
            return "SPEC_REFUSED", shown
        still = [r for r in waits if states.get(r) not in CLOSED_STATES]
        if still or not waits:
            coordinator = home_hold_note(still, states, repo, home)
            return "BLOCKED", " | ".join([shown, coordinator]) if coordinator else (shown or "labelled blocked")
        if not human and children and CHECK.search(issue.get("body") or ""):
            return parent_check(comments, bot_login, [closes[r] for r in waits if r in closes], shown)
        if not human:
            return "UNBLOCKED", shown
    if postponed in labels:
        return postponed_state(triaged, stable, note, revisits)
    if human:
        # Every hold has closed: the person's turn starts at the newest close
        ends = [timestamp(closes[r]) for r in waits if r in closes and states.get(r) in CLOSED_STATES]
        since = max(ends, default=None)
        return person_state(issue["comments"]["nodes"], people, bot_login, since, shown, teams)
    # An answer relayed from a session after the label came off, no triage comment after it: it
    # still waits to be taken up, as a reply does while the label is on; one out of the relay
    # grammar is not counted (D-93), and with the label off nobody else asks again (#1302)
    relay = relayed(comment_tuples(issue), bot_login)
    if relay is not None and relay[0] > verdict:
        refused = relay_refused(comment_tuples(issue), bot_login, relay[0])
        if refused is not None:
            return "RELAY_REFUSED", RELAY_NOT_COUNTED.format(reason=refused)
        return "DECIDED", f"answered by @{relay[1]}, {RELAYED}"
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
        return GHOST
    name = str(author.get("login") or GHOST)
    if author.get("__typename") == "Bot" and not name.endswith("[bot]"):
        name += "[bot]"
    return name


def same_login(a: str, b: str) -> bool:
    return a.lower() == b.lower()  # GitHub logins ignore case


def first_line(body: str) -> str:
    """A comment's first line, past any leading blank lines"""
    return body.lstrip().split("\n", 1)[0].strip()


def triage_verdict(issue: dict[str, Any], marker: str) -> str | None:
    """Spec 088: the verdict of the issue's newest triage comment, its bold word right after
    the marker when it is one of TRIAGE_VERDICTS, or one of them followed by more words (as
    "postponed to 1.1" reads postponed); None otherwise"""
    triage = [c["body"].lstrip() for c in issue["comments"]["nodes"] if c["body"].lstrip().startswith(marker)]
    if not triage:
        return None
    found = VERDICT_WORD.match(triage[-1][len(marker) :].lstrip())
    if found is None:
        return None
    word = " ".join(found.group(1).split()).lower().replace("\u2019", "'")
    return next((v for v in TRIAGE_VERDICTS if word == v or word.startswith(v + " ")), None)


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


def by_agent(body: str) -> bool:
    """Whether a body carries the agent marker (spec 050): any line, stripped, is
    <!-- shipmill:agent --> or the marker with attributes after a space"""
    return any(AGENT_MARKER.fullmatch(line.strip()) for line in body.splitlines())


def by_person(author: str, association: str, body: str, bot_login: str | None) -> bool:
    """Whether a comment can be a person's decision (D-62): by an OWNER, MEMBER, or
    COLLABORATOR other than the --bot-login, with a readable author (a deleted account's
    counts as an agent's) and no agent marker"""
    if same_login(author, GHOST) or (bot_login is not None and same_login(author, bot_login)):
        return False
    return association in TRUSTED and not by_agent(body)


def replies(comment: tuple[str, str, str], bot_login: str | None) -> bool:
    """A reply: a comment without the needs-decision marker by a person, as by_person reads
    one: an OWNER, MEMBER, or COLLABORATOR other than the --bot-login, without the agent marker"""
    author, association, body = comment
    return by_person(author, association, body, bot_login) and not marked(body)


def waits_on_decision(comments: list[tuple[str, str, str]], bot_login: str | None) -> bool:
    """Whether a needs-decision item still waits; comments are (login, author association,
    body), oldest first. It waits until a reply comes after its question; with no question
    at all, a person parked it, so it waits too"""
    asked = question(comments, bot_login)
    if asked is None:
        return True
    return not any(replies(c, bot_login) for c in comments[asked + 1 :])


def relayed(comments: list[tuple[str, str, str]], bot_login: str | None) -> tuple[int, str] | None:
    """The newest relay after an item's question, as (its index, who answered), or None;
    comments are (login, author association, body), oldest first. A relay is a comment by the
    --bot-login whose first line is `Decision by @<login>` or ``Decision by `@<login>` ``
    (D-61): an answer given in a session, which carries the agent marker, so it is no reply,
    and the session that posts it removes the label (needs-decision.md). Without --bot-login
    nothing is a relay"""
    asked = question(comments, bot_login)
    if asked is None or bot_login is None:
        return None
    return relayed_after(comments, bot_login, asked)


def relayed_after(comments: list[tuple[str, str, str]], bot_login: str, asked: int) -> tuple[int, str] | None:
    """The newest relay after the question at index asked, as (its index, who answered), or
    None: relayed's reading for a question its caller found, such as a person's asked after the
    bot (#1340); comments are (login, author association, body), oldest first"""
    if not 0 <= asked < len(comments):
        fail(f"relayed_after wants a question's index, got {asked} for {len(comments)} comments")
    for i in range(len(comments) - 1, asked, -1):
        author, _, body = comments[i]
        found = DECISION_BY.match(first_line(body)) if same_login(author, bot_login) else None
        if found is not None:
            return i, found[1] or found[2]
    return None


def relay_refused(comments: list[tuple[str, str, str]], bot_login: str | None, at: int) -> str | None:
    """Why the relay at index at isn't counted against its question, as pr_gate.py's acceptance
    reads it (D-93): retro.py's relay_refusal of its parse_relay, a reason such as "format", or
    None when it counts; comments are (login, author association, body), oldest first, and at
    is relayed's index, so the item has a question"""
    asked = question(comments, bot_login)
    if asked is None:
        fail(f"relay_refused wants a relay after a question, got index {at} with none")
    return relay_refused_to(comments, asked, at)


def relay_refused_to(comments: list[tuple[str, str, str]], asked: int, at: int) -> str | None:
    """Why the relay at index at isn't counted against the question at index asked, as
    relay_refused reads it (D-93), for a question its caller found, such as a person's asked
    after the bot (#1340); at is relayed_after's index"""
    if not 0 <= asked < at < len(comments):
        fail(f"relay_refused_to wants a relay after its question, got question {asked} and relay {at}")
    rt = retro_module()
    refused: str | None = rt.relay_refusal(comments[asked][2], rt.parse_relay(comments[at][2]))
    return refused


def trusted(author: str, association: str, bot_login: str | None) -> bool:
    """D-16: an OWNER, MEMBER, or COLLABORATOR, or the sessions' own bot"""
    return association in TRUSTED or (bot_login is not None and same_login(author, bot_login))


def vetoes(comment: tuple[str, str, str], bot_login: str | None) -> bool:
    """A veto (spec 030): a comment by an OWNER, MEMBER, or COLLABORATOR other than the
    --bot-login whose first word is "veto" in any case; an outsider's never counts (D-16),
    nor does a "veto" further into a comment, one carrying the agent marker, or a deleted
    account's (spec 050)"""
    author, association, body = comment
    return by_person(author, association, body, bot_login) and VETO.match(first_line(body)) is not None


def relayed_veto(comment: tuple[str, str, str], bot_login: str | None, maintainers: Container[str]) -> str | None:
    """D-103 (#1482): the maintainer a relayed veto names, or None. A relayed veto is a comment by
    the --bot-login whose first line is the relay `Decision by @<login>` (D-61) naming a login in
    maintainers (lowercased), read by retro.py's parse_relay (D-93) as counted, whose answer line is
    `own: veto` or `own: veto <text>`, or starts with the word veto; a relay out of the grammar,
    naming anyone else, or without --bot-login is none"""
    author, _, body = comment
    if bot_login is None or not same_login(author, bot_login):
        return None
    found = DECISION_BY.match(first_line(body))
    if found is None:
        return None
    relay = retro_module().parse_relay(body)
    if relay.refused is not None or VETO.match(relay.answer) is None:
        return None
    named = str(found[1] or found[2])
    # asked last: pr_gate.py's maintainers may read a permission from GitHub (spec 055)
    return named if named.lower() in maintainers else None


def maintainers_of(roles: Roles | None) -> frozenset[str]:
    """The maintainer's users the --role flags give, lowercased, as relayed_veto reads them; none
    without the flags, so no relay is a veto then"""
    return frozenset() if roles is None else frozenset(u.lower() for u in roles[MAINTAINER][0])


def vetoed(
    comments: list[tuple[str, str, str]], bot_login: str | None, maintainers: Container[str] = frozenset()
) -> str | None:
    """Who vetoed a decided item and is still unanswered, or None; comments are (login, author
    association, body), oldest first, as unhandled_veto reads them. A relayed veto's is the
    maintainer it names, not the bot (D-103)"""
    veto = unhandled_veto(comments, bot_login, maintainers)
    if veto is None:
        return None
    return relayed_veto(comments[veto], bot_login, maintainers) or comments[veto][0]


def vetoes_or_relays(comment: tuple[str, str, str], bot_login: str | None, maintainers: Container[str]) -> bool:
    """A veto (vetoes) or a maintainer's relayed veto (relayed_veto, D-103)"""
    return vetoes(comment, bot_login) or relayed_veto(comment, bot_login, maintainers) is not None


def unhandled_veto(
    comments: list[tuple[str, str, str]], bot_login: str | None, maintainers: Container[str] = frozenset()
) -> int | None:
    """The index of the newest veto of a decided item still unanswered, or None; comments are
    (login, author association, body), oldest first. A veto counts after the first decided marker
    (its first line, by the --bot-login or an OWNER, MEMBER, or COLLABORATOR, as D-29's markers),
    until a newer veto-handled marker by such an author answers it; a relay of a maintainer's veto
    counts as theirs (relayed_veto, D-103). pr_gate.py reads it too (#1309)"""
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
        elif vetoes_or_relays(comments[i], bot_login, maintainers):
            veto = i
    if veto is None or handled > veto:
        return None
    return veto


def comment_tuples(issue: dict[str, Any]) -> list[tuple[str, str, str]]:
    """An issue's comments as the decision rules read them: (login, author association, body)"""
    return [
        (login(c.get("author")), str(c.get("authorAssociation") or "NONE"), c["body"])
        for c in issue["comments"]["nodes"]
    ]


def closed_vetoed(
    issue: dict[str, Any], bot_login: str | None, maintainers: Container[str] = frozenset()
) -> tuple[str, str] | None:
    """VETOED for a closed issue labelled decided (the query picks those updated in the veto
    window) that holds an unanswered trusted veto, a maintainer's relayed one too (D-103); None
    otherwise, which reports nothing"""
    who = vetoed(comment_tuples(issue), bot_login, maintainers)
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


def spec_files(body: str) -> list[str]:
    """The spec files an issue's body names, each once, in its order (spec 053)"""
    return list(dict.fromkeys(SPEC_FILE.findall(body)))


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


def stale_handoff(issue: dict[str, Any], bot_login: str | None) -> tuple[str, str] | None:
    """STALE_HANDOFF (#1313): an open person's item (labelled human or role:<name>) whose
    sub-issue parent, in any repo, is closed, its note "parent owner/repo#N closed": the work
    it was handed for is done or dropped, so a session closes it or says why it still waits.
    None when it has no parent (or the forge reads none), the parent is open, or a comment
    created after the parent's close has <!-- shipmill:still-waits --> as its first line, by the
    --bot-login or an OWNER, MEMBER, or COLLABORATOR without the agent marker (D-62); with no
    close time, no comment can be dated after it"""
    parent = issue.get("parent")
    if not parent or parent.get("state") != "CLOSED" or not person_item(issue):
        return None
    closed = parent.get("closedAt")
    if closed:
        since = timestamp(closed)
        for c in issue["comments"]["nodes"]:
            if timestamp(c["createdAt"]) <= since or not marked(c["body"], STILL_WAITS_MARKER):
                continue
            author, association = login(c.get("author")), str(c.get("authorAssociation") or "NONE")
            if (bot_login is not None and same_login(author, bot_login)) or by_person(
                author, association, c["body"], bot_login
            ):
                return None
    return "STALE_HANDOFF", f"parent {parent['repository']['nameWithOwner']}#{parent['number']} closed"


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


UNOWNED_NOTE = "no coordinator: waits for the maintainer to report it where it belongs"


def unowned(issue: dict[str, Any], repo: tuple[str, str], home: str | None) -> bool:
    """Whether an upstream report waits on nobody (#1487): no coordinator (no --home), no
    assignee, and no link to an issue in another repo, by a Depends on line, a blocked-by
    relation, or a sub-issue. A link in its own repo routes it nowhere"""
    if home is not None or assignees(issue):
        return False
    here = fold((*repo, 0))[:2]
    return all(fold(ref)[:2] == here for ref in [*dependency_refs(issue, repo), *native_holds(issue)])


def owned_upstream(
    verdict: tuple[str, str] | None, issue: dict[str, Any], repo: tuple[str, str], home: str | None
) -> tuple[str, str] | None:
    """gated's verdict, with an UPSTREAM report nobody linked or took read as UPSTREAM_UNOWNED
    (#1487), its note keeping whether it asks the maintainer"""
    if verdict is None or verdict[0] != "UPSTREAM" or not unowned(issue, repo, home):
        return verdict
    asks = verdict[1].endswith(", asks the maintainer")
    return "UPSTREAM_UNOWNED", f"{UNOWNED_NOTE}, asks the maintainer" if asks else UNOWNED_NOTE


def home_hold_note(still: list[Ref], states: dict[Ref, str], repo: tuple[str, str], home: str | None) -> str | None:
    """BLOCKED's added note in a component (D-60, #773): a hold still open on an item of the
    product's home that this session can't read (no state came back, even through the read
    token, spec 065) is the coordinator's, so the session asks nobody about it and leaves the
    item. None without --home, in the home repo itself, or when every such hold was read"""
    if home is None or home.lower() == "/".join(repo).lower():
        return None
    owner, _, name = home.lower().partition("/")
    unread = [r for r in still if fold(r)[:2] == (owner, name) and states.get(r, "UNKNOWN") == "UNKNOWN"]
    return f"the coordinator's hold on the home {home}: waits for the coordinator, ask nobody" if unread else None


def home_repo(text: str) -> bool:
    """Whether text is owner/name, each side of letters, digits, '.', '-', or '_' and neither
    "." nor "..", as shipmill reads a repo (app.repo_name and its cache segment rule)"""
    parts = text.split("/")
    return len(parts) == 2 and all(p not in {".", ".."} and SEGMENT.fullmatch(p) for p in parts)


def gated(
    issue: dict[str, Any],
    bot_login: str | None,
    trusted_only: bool,
    home: str | None = None,
    maintainers: Container[str] = frozenset(),
) -> tuple[str, str] | None:
    """UNTRUSTED (with trusted_only), then UPSTREAM, then NEEDS_DECISION or DECIDED, then
    VETOED, each read before any other state; None when none holds, and the issue reads as
    classify_open says. DECIDED comes first so the reply is acted on, whatever its text links
    (#309). An upstream report waits outside whatever its labels and holds (spec 038); ``home``
    words its note. VETOED is an item labelled decided with an unanswered veto (spec 030), a
    relayed one naming one of ``maintainers`` too (D-103)"""
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
        who = vetoed(comments, bot_login, maintainers)
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
    """VERIFY_CLOSED for a closed issue that owes its check (check_closable) when a pull request
    or a commit closed it (D-76), or, for a parent (spec 042), the --bot-login, and no trusted
    verified comment came after the close: never SUSPECT_CLOSE. None when it was verified"""
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
    if check_closable(issue):
        # Closed by a pull request or a commit before its check ran, any issue (D-76), or a
        # parent by a session (spec 042); a trusted person's own close by hand is their call and
        # reads as before
        event = (issue["timelineItems"]["nodes"] or [{}])[0]
        by_bot = bot_login is not None and same_login(login(event.get("actor")), bot_login)
        if event.get("closer") is not None or (by_bot and parent_checkable(issue)):
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
    data: dict[str, Any],
    closed: int,
    hold: str,
    incident: str,
    bot_login: str | None,
    maintainers: Container[str] = frozenset(),
) -> list[dict[str, Any]]:
    """The lines of closed issues: each closed issue labelled decided in the veto window reads
    VETOED, marked "closed", or nothing (spec 030); VETOED, read right after DECIDED, comes
    before any other state, so such an issue gets no second line. Then the ``closed`` most
    recently updated closed issues as classify_closed reads them"""
    rows: list[dict[str, Any]] = []
    vetoed_closed: set[int] = set()
    for issue in data["vetoable"]["nodes"]:
        verdict = closed_vetoed(issue, bot_login, maintainers)
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


# Spec 070: an accepted opportunity (D-10) has a class of service, a label a person adds to it
OPPORTUNITY_LABEL = "opportunity"
PLANNED_LABEL = "planned"
EXPEDITE_LABEL = "expedite"
FIXED_DATE_LABEL = "fixed-date"
CLASS_LABELS = (EXPEDITE_LABEL, FIXED_DATE_LABEL)
LABELED_EVENTS = 100  # an opportunity's newest label events read, for who added its class label
CLASS_CHUNK = 50  # opportunities one label-event query reads


def added_by_person(events: list[Any], label: str, bot_login: str | None) -> bool:
    """Whether the newest labeled event adding label names a person as its actor: a User, never
    a Bot (the App) or the --bot-login; an event whose actor can't be read, or no such event in
    those read, counts as no label, so choosing a class stays the maintainer's (N-3, D-10;
    github-ship-watch's watch_state.py reads the class by this rule too)"""
    adding = [e for e in events if isinstance(e, dict) and (e.get("label") or {}).get("name") == label]
    if not adding:
        return False
    actor = adding[-1].get("actor")
    if not isinstance(actor, dict) or actor.get("__typename") != "User":
        return False
    name = actor.get("login")
    if not isinstance(name, str) or not name or name.endswith("[bot]"):
        return False
    bot = (bot_login or "").removesuffix("[bot]")
    return name.lower() != bot.lower()


def expedite_outcomes(
    repo: str, issues: list[dict[str, Any]], bot_login: str | None, run: Runner = gh_graphql
) -> frozenset[int]:
    """Spec 070: the open accepted opportunities of class expedite, an `expedite` label a person
    added (added_by_person) and no counted `fixed-date` beside it (both read as standard). Their
    label events are read in one query per CLASS_CHUNK, and only for the open issues labelled
    opportunity, planned, and expedite; none, no read"""
    wanted = sorted(
        issue["number"]
        for issue in issues
        if {OPPORTUNITY_LABEL, PLANNED_LABEL, EXPEDITE_LABEL} <= {n["name"] for n in issue["labels"]["nodes"]}
    )
    named = {issue["number"]: {n["name"] for n in issue["labels"]["nodes"]} for issue in issues}
    owner, _, name = repo.partition("/")
    events = (
        f"timelineItems(itemTypes: [LABELED_EVENT], last: {LABELED_EVENTS})"
        " { nodes { ... on LabeledEvent { label { name } actor { __typename login } } } }"
    )
    found: set[int] = set()
    for start in range(0, len(wanted), CLASS_CHUNK):
        chunk = wanted[start : start + CLASS_CHUNK]
        parts = " ".join(f"n{n}: issue(number: {n}) {{ {events} }}" for n in chunk)
        query = f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {parts} }} }}"
        data = repository(run, query, {"owner": owner, "name": name})
        for n in chunk:
            nodes = ((data.get(f"n{n}") or {}).get("timelineItems") or {}).get("nodes")
            if not isinstance(nodes, list):
                fail(f"no label events for {repo}#{n} in the GraphQL response")
            counted = {x for x in CLASS_LABELS if x in named[n] and added_by_person(nodes, x, bot_login)}
            if counted == {EXPEDITE_LABEL}:
                found.add(n)
    return frozenset(found)


def expedite_issues(issues: list[dict[str, Any]], outcomes: frozenset[int], repo: str) -> frozenset[int]:
    """The open issues of an expedite outcome: each opportunity of outcomes, and each open issue
    whose sub-issue parent, in this repo, is one"""
    found = set(outcomes)
    for issue in issues:
        parent = issue.get("parent")
        if parent and parent["repository"]["nameWithOwner"].lower() == repo.lower() and parent["number"] in outcomes:
            found.add(issue["number"])
    return frozenset(found)


def wip_room(
    rows: list[dict[str, Any]],
    wip: int,
    people: frozenset[int] = frozenset(),
    busy: frozenset[int] = frozenset(),
    expedite: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    """How many more issues may start under a WIP limit of ``wip``, counting each issue with
    an open PR as in progress, and the issues ready to start (NEEDS_PR or UNBLOCKED), oldest
    first: build issues are filed in build order. The ``expedite`` ones (spec 070) come first,
    oldest first among them, and count in progress like any other, so they take the next free
    slot and never one past the limit. A person's item (one of ``people``) never counts: the
    limit is on agents' work. ``busy`` are issues whose OFF_MILESTONE hides IN_PROGRESS: they
    count as in progress too"""
    agents = [r for r in rows if r["number"] not in people]
    in_progress = sum(1 for r in agents if r["state"] in IN_FLIGHT or r["number"] in busy)
    ready = sorted(
        (r["number"] for r in agents if r["state"] in ("NEEDS_PR", "UNBLOCKED")), key=lambda n: (n not in expedite, n)
    )
    return {"wip": wip, "in_progress": in_progress, "room": max(wip - in_progress, 0), "ready": ready}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog=(
            "States: NEW NEEDS_PR IN_PROGRESS AGENT_DRAFT AGENT_DRAFT_HELD DONE_NOT_CLOSED BLOCKED UNFILLED "
            "MALFORMED_DEPENDS CYCLE SPEC_REFUSED "
            "UNBLOCKED POSTPONED REVISIT TRIAGED NEEDS_DECISION DECIDED RELAY_REFUSED VETOED UNTRUSTED UPSTREAM "
            "UPSTREAM_UNOWNED OFF_MILESTONE; "
            "for an issue labelled human or role:<name> "
            "(a person's item) STALE_HANDOFF NO_ASSIGNEE ASSIGN_DUE HANDOFF_DUE WITH_PERSON VERIFY_DUE; "
            "for a closed issue "
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
        "--home",
        metavar="OWNER/NAME",
        help=(
            "the config's [product] home, which routes upstream reports (spec 038) and clears its own holds"
            " (D-60); in a component, holds on the product's other repos are read with `shipmill gh --product`"
        ),
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

    # #1469: the follow-up calls each answer makes start on threads as soon as it is in hand;
    # the run still reads every answer in its own order
    ahead = Ahead()
    data = fetch(args.repo, max(args.closed, 1), stable_pattern, labels=args.label, run=ahead.graphql, ahead=ahead)
    owner, _, name = args.repo.partition("/")  # fetch checked it is owner/name
    revisits = Revisits(owner, name, data["tags"], stable_pattern, execute=ahead)
    revisits.start(ahead, data["open"]["nodes"], args.marker, args.postponed_label)
    if any(isinstance(dig(issue, "body"), str) and build_spec(issue) for issue in data["open"]["nodes"]):
        # veto_windows' first call (fetch_decided_prs), made only when an open issue is a build issue
        ahead.start_graphql(DECIDED_PRS_PAGE, {"owner": owner, "name": name, "size": SIZES[DECIDED_PRS_PAGE]})
    rows: list[dict[str, Any]] = []
    refs = {r for issue in data["open"]["nodes"] for r in upstream_refs(issue, (owner, name))}
    refs |= {r for issue in data["open"]["nodes"] for r in dependency_refs(issue, (owner, name))}
    # Spec 079: the reverts the --bot-login reopened an issue over, whose state decides its reading
    refs |= {(owner, name, r) for issue in data["open"]["nodes"] for r in reverts(issue, args.bot_login).values()}
    # The forge's relations came with their states: ask only for the others
    holds = {r: h for issue in data["open"]["nodes"] for r, h in native_holds(issue).items()}
    native = {r: s for r, (_, s, _) in holds.items()}
    upstream, closes = upstream_states(refs - set(native))
    # A component reads again, with the read token, the holds on other repos' items plain gh
    # couldn't (spec 065); without --home, or in the home, no `shipmill gh` runs
    unread = product_reads(upstream, (owner, name), args.home)
    if unread:
        gh, execute = product_gh(Path.cwd().resolve())
        read, read_closes = product_states(unread, args.home, gh, execute)
        upstream.update(read)
        closes.update(read_closes)
    states = {**upstream, **native}
    # with each one's close time too: a person's hand-off is dated against it
    closes = {**closes, **{r: c for r, (_, _, c) in holds.items() if c is not None}}
    stable = latest_stable(data["tags"]["nodes"], stable_pattern)
    people: set[int] = set()
    busy: set[int] = set()  # OFF_MILESTONE over an open PR: still in progress under --wip
    issues: list[dict[str, Any]] = data["open"]["nodes"]
    maintainers = maintainers_of(roles)  # whom a relayed veto may name (D-103)
    gates = {
        issue["number"]: owned_upstream(
            gated(issue, args.bot_login, args.trusted_only, args.home, maintainers), issue, (owner, name), args.home
        )
        for issue in issues
    }
    untrusted = {n for n, verdict in gates.items() if verdict is not None and verdict[0] == "UNTRUSTED"}
    loops = cycles(issues, (owner, name), args.marker, untrusted)
    # Spec 067: the build issues of a spec approved at notify wait out its veto window
    windows = veto_windows(args.repo, issues, args.bot_login, run=ahead.graphql, maintainers=maintainers)

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
            home=args.home,
            revisits=revisits,
            window=windows.get(issue["number"]),
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
                issue,
                args.marker,
                args.postponed_label,
                states,
                stable,
                (owner, name),
                args.bot_login,
                closes,
                False,
                revisits=revisits,
            )
            if usual[0] in IN_FLIGHT:
                busy.add(issue["number"])
        row: dict[str, Any] = {"number": issue["number"], "state": state, "title": issue["title"], "note": note}
        if state == "TRIAGED":  # spec 088: what it was triaged as, for shipmill status
            verdict = triage_verdict(issue, args.marker)
            if verdict is not None:
                row["verdict"] = verdict
        if direction_issue(issue, args.bot_login):  # spec 034: github-ship-watch's, never in its issue rows
            row["direction"] = True
        linked = spec_files(issue["body"] or "")
        if linked:  # spec 053: the specs it follows, for github-ship-watch's SPEC_UNSPLIT
            row["specs"] = linked
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
    rows += closed_rows(data, args.closed, args.hold_label, args.incident_label, args.bot_login, maintainers)

    order = [
        "SUSPECT_CLOSE",
        "VERIFY_CLOSED",
        "DONE_NOT_CLOSED",
        "DECIDED",
        "RELAY_REFUSED",
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
        "AGENT_DRAFT",
        "IN_PROGRESS",
        "AGENT_DRAFT_HELD",
        "WITH_PERSON",
        "BLOCKED",
        "TRIAGED",
        "POSTPONED",
        "UPSTREAM_UNOWNED",
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
        # spec 070: the expedite outcomes' issues go first among the ready ones
        expedite = expedite_issues(issues, expedite_outcomes(args.repo, issues, args.bot_login), args.repo)
        room = wip_room(rows, args.wip, frozenset(people), frozenset(busy), expedite)
        if args.json:
            print(json.dumps(room, sort_keys=True))
        else:
            ready = " ".join(f"#{n}" for n in room["ready"]) or "none"
            print(f"WIP {room['wip']}: {room['in_progress']} in progress, room for {room['room']}; ready: {ready}")
    return 1 if any(r["state"] in ACTION for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
