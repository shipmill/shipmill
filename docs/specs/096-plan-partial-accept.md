# S-096: Accept part of a plan in one reply

status: approved
serves: G-6

## Problem

A goal plan (spec 028) is answered by one reply whose first line decides: `accept` files
every `feature` and `fix` item, a line starting with `decline` closes the plan, and anything
else is an edit the session makes before the plan waits again. That fits a plan the
maintainer takes whole or rejects whole, and not how a plan is usually decided: the triage
line on each plan so far names the items most open to cutting, and the maintainer keeps most
of the work and cuts one or two items. Today cutting one costs a full round trip: an edit
answer, a revision with a higher `rev`, and a second `accept` on the revised body. A reply
such as `accept W-1, W-3` is read as an edit, so the cut is never a one-reply answer.

Plan #752 for G-6 orders this as W-2 (#1681), after W-1 makes a waiting plan visible in
`shipmill status`: "W-2 then makes the answer fit how the maintainer decides a plan". Once it
lands, the maintainer accepts all or part of a plan in one reply, and only the items kept are
filed. W-2 changes only how an answer is read, never who gives it: accepting a plan stays the
maintainer's `scope` decision with the floor `ask` (N-3, D-10, spec 030), answered by a trusted
author (D-16, D-29) or relayed from a session (D-68).

## Behaviour

This spec refines spec 028's sections The maintainer's answer and Accepting files the work; every
rule of 028 not named here holds as it is.

### The answer grammar

The answer is still the newest trusted comment newer than the plan's newest revision, read as
spec 028 reads it (D-16), or the relay a session posts for a maintainer (D-68), read from its
first non-blank line after the relay line. Its first line decides, now with two more accept
forms. `skills/product-intake/scripts/intake_state.py` reads them:

| First line | Answer | Kept | Dropped |
|---|---|---|---|
| `accept` | accept | every item | none |
| `accept W-1, W-3` | accept, keeping the items named | the items named | every other item |
| `accept except W-2` | accept, dropping the items named | every other item | the items named |
| starts with `decline` | decline, as today | | |
| starts with `accept` and is none of the above | unclear accept (below) | | |
| anything else | edit, as today | | |

- `accept` and `except` in any case; each id `W-<n>` in any case, the ids separated by commas,
  spaces, or both; an optional final period. Nothing else on the first line: a reason for the
  cut goes on the lines after it, which are kept with the answer and read by nobody as a rule
- The ids are those of the Work section of the body the answer was given on, which is the body
  as it is: an accept older than the body's last edit reads `edited after accept` (spec 028),
  and a `plan-revised` comment makes an older answer stale (spec 028), whatever the accept kept
- An item of any kind can be kept or dropped: `feature`, `fix`, or `existing`. A kept list that
  names every item is a full accept, and reads as `accept` does
- A first line that starts with the word `accept` and is none of the accept forms is an
  **unclear accept**: an id the Work section doesn't list, an id named twice, a list with no
  id (`accept except`), an `except` list naming every item (which keeps nothing), both forms
  at once (`accept W-1 except W-2`), or words past the ids (`accept W-1, W-3 for now`). It is
  never read as an edit, never as a full accept, and never guessed at. The first line `accept`
  is a whole word: `accepted` and `acceptable` start no accept, and stay edits as today

### The plan rows

`intake_state.py --plans` reads a partial accept as it reads `accept`, and the filing reader
looks at the kept items alone:

- **PLAN_ACCEPTED** while a kept `feature` or `fix` item has no issue carrying its plan-item
  marker, or the Milestone names a title and a kept item of this repository (filed, or
  `existing`) isn't in it. **PLAN_FILED** once neither holds. A dropped item is never "not
  filed" and never "not in milestone", and a dropped item someone filed by hand changes neither
  state
- The note adds `dropped: W-2, W-4` after what it says today, on PLAN_ACCEPTED and PLAN_FILED
  alike, so a report shows the cut. With `--json` each plan issue's row whose answer is an
  accept has `kept` and `dropped`, two lists of ids in Work order (`dropped` empty for a full
  accept); every other row has neither key
- **PLAN_ANSWERED** with the note `unclear accept: <rule>` for an unclear accept, `<rule>` naming
  what is wrong (`W-9 is not in the plan`, `W-2 is named twice`, `no item named`, `drops every
  item`, `both a kept and a dropped list`, `words past the ids`). It is an action (exit 1), as
  the other PLAN_ANSWERED notes are
- **PLAN_OPEN** with the note `unclear accept asked` once a comment by the `--bot-login` whose
  first line is the needs-decision marker `<!-- shipmill:needs-decision -->` is newer than the
  unclear accept: the session asked, and the plan waits for the maintainer again. A trusted
  answer newer than that question is read as any answer is (an accept form, a decline, or an
  edit). A needs-decision marker by anyone else, or older than the unclear accept, changes
  nothing
- **PLAN_DUE** with `--json` gains `dropped`: each item an earlier plan for the same goal
  dropped, as `{"plan": P, "id": "W-n", "text": "<the item's text>"}`, read from every plan
  issue of the goal, open or closed as completed, whose newest answer is a partial accept, the
  text from that plan's body. A plan closed as not planned adds none: its decline already holds
  (spec 028)

### Filing only what was kept

`skills/product-intake/SKILL.md` (Plan a goal, PLAN_ACCEPTED) files from the row's `kept` list:

- Each kept `feature` and `fix` item still unfiled, in Work order, from the filed item template
  of `skills/product-intake/references/plan.md`, as today. A dropped item is never filed, never
  made a sub-issue of the plan, and never put in the milestone; a dropped `existing` item is left
  exactly as it is
- A kept item's `(after W-k)` on a dropped W-k gets no `Depends on` line and no `--blocked-by`
  relation for W-k: the cut item is no longer work to wait for. Its other `after` items link as
  today
- The plan's sub-issues are then the kept items alone, so the plan reads BLOCKED with
  `children K/N closed` over the kept work, and triage closes it once that work closes, like
  any parent
- The filed line on the plan names the cut, from `plan.md`:
  `Triage: **plan**: accepted and filed: W-1 #a, W-3 #b; dropped: W-2, W-4{; W-3 filed without its after W-2}{; milestone <title>}. Triage takes them up within [agents] wip.`

### An unclear accept

On PLAN_ANSWERED `unclear accept`, the session files nothing, revises nothing, and asks once
through the needs-decision protocol on the plan (D-21): the marker comment quoting the answer's
first line and the rule it broke, with the two accept forms as options and the `needs-decision`
label. The plan then reads PLAN_OPEN `unclear accept asked`. An interactive session that hears
the answer in the chat relays it as today (D-68), and the relay is read by the same grammar.
The session never picks the reading it thinks was meant: an accept is the maintainer's, at
floor `ask`.

### Dropped items stay dropped

A dropped item is recorded by the answer that dropped it, on the plan issue, which is never
edited for it. `SKILL.md`'s PLAN_DUE step reads the row's `dropped` list and never proposes one
of those items again for the goal, under any kind or wording that asks for the same outcome,
and names each under the new plan's Notes as left out (`W-2 of #752, dropped by the
maintainer`). It proposes one again only when the maintainer asks for it: a `requested` plan
whose request names it, or an edit answer on the new plan that asks for it. A revision of the
same plan follows the same rule. This is D-10's rule for a declined opportunity, applied to the
item the maintainer cut.

### The triage line, and the views

- `plan.md`'s triage line on a plan names the new forms: `accept` files every feature and fix
  item, `accept W-1, W-3` files only those named and drops the rest, `accept except W-2` files
  all but those named, a line starting with `decline` closes the plan, and anything else is an
  edit. The line keeps naming the items most open to cutting, so the cut is one reply
- `skills/github-ship-watch/scripts/watch_state.py` lists the rows as today: a partially
  accepted plan's PLAN_ACCEPTED and an unclear accept's PLAN_ANSWERED in the PLANS row as
  actions, and PLAN_FILED and PLAN_OPEN `unclear accept asked` in none. `shipmill gate` starts a
  session for the PLANS row as it does today
- `skills/github-ship-watch/scripts/fleet.py queue` lists a partially accepted plan in no row, as
  for a full accept; a plan whose unclear accept was asked is in the QUESTION row while its
  question waits, and in no PLAN row then, as any item with an open question
- `src/shipmill/status.py` reads a partially accepted plan as it reads an accepted one: no new
  state, and no WAITS ON YOU reason beyond what W-1 (#1680) adds for a waiting plan

## Acceptance criteria

- S-096-1: An answer whose first line is `accept W-1, W-3` (any case, ids separated by commas, spaces, or both, an optional final period) reads PLAN_ACCEPTED, and its `--json` row has `kept` `["W-1", "W-3"]` and `dropped` every other item's id in Work order
- S-096-2: An answer whose first line is `accept except W-2` reads PLAN_ACCEPTED with `dropped` `["W-2"]` and `kept` every other item's id in Work order
- S-096-3: An answer whose first line is `accept` alone, or a kept list naming every item, reads PLAN_ACCEPTED with `kept` every item and `dropped` empty, and its note has no `dropped:` part
- S-096-4: A first line that starts with the word `accept` and names an id the plan doesn't list, names an id twice, names no id after `except`, drops every item, holds both a kept and an `except` list, or has words past the ids reads PLAN_ANSWERED with the note `unclear accept: <rule>`, the rule naming the fault, and `intake_state.py` exits 1; a first line starting `accepted` or `acceptable` still reads PLAN_ANSWERED `edit`
- S-096-5: A comment by the `--bot-login` whose first line is `<!-- shipmill:needs-decision -->`, newer than an unclear accept, makes the plan read PLAN_OPEN with the note `unclear accept asked`; a trusted answer newer than that question is read as a new answer; the same marker by any other author, or older than the unclear accept, changes nothing
- S-096-6: A partially accepted plan reads PLAN_ACCEPTED while a kept `feature` or `fix` item has no issue carrying its plan-item marker, or a kept item of this repository is outside the named milestone, and PLAN_FILED once neither holds, however many dropped items are unfiled or outside the milestone; the note of either names `dropped: <ids>`
- S-096-7: A relay by the `--bot-login` naming a maintainer whose answer line is `accept W-1, W-3` or `accept except W-2` reads as the same partial accept, and an unclear one as an unclear accept; a relay naming anyone else changes nothing, as in S-028-18
- S-096-8: A partial accept older than the body's last edit reads PLAN_OPEN `edited after accept`, and a `plan-revised` comment by the `--bot-login` with a higher `rev` makes it stale, as for `accept`
- S-096-9: With `--json`, a PLAN_DUE row lists under `dropped` each item an earlier plan for the same goal, open or closed as completed, dropped by its newest answer, with the plan's number, the item's id, and its text; a plan closed as not planned, or one fully accepted, adds none
- S-096-10: product-intake's SKILL.md files only the kept `feature` and `fix` items of a partially accepted plan, in Work order, never files, links, or milestones a dropped item, writes no `Depends on` line or relation for an `(after W-k)` on a dropped W-k, and names the dropped items in the filed line
- S-096-11: product-intake's SKILL.md answers an unclear accept by asking once through the needs-decision protocol, filing and revising nothing, and its PLAN_DUE step never proposes an item the row's `dropped` lists unless a request or the maintainer's edit asks for it, naming each one under the new plan's Notes
- S-096-12: plan.md's triage line on a plan names the `accept W-1, W-3` and `accept except W-2` forms, and its filed line template names the dropped items
- S-096-13: `watch_state.py` lists a partially accepted plan's PLAN_ACCEPTED and an unclear accept's PLAN_ANSWERED in the PLANS row as actions, and neither PLAN_FILED nor PLAN_OPEN `unclear accept asked`; `fleet.py queue` lists no PLAN row for a partially accepted plan

## Out of scope

- Who answers a plan: the maintainer, at `scope` with the floor `ask` (N-3, D-10, spec 030);
  this spec only reads more answers, and no session accepts any part of a plan for them
- Ranges or kinds in the answer (`accept W-1..W-3`, `accept features`): ids only
- Changing an item's text, kind, or order in the same reply: that is an edit, answered by a
  revision as today
- Re-opening a dropped item on an accepted plan: the maintainer asks for it in a new plan, or
  files it themselves
- Holding a plan until a condition (W-4, #1683) and the check of a finished plan (W-3, #1682)
- Showing waiting plans in `shipmill status` (W-1, #1680)
- A later trusted comment on an already accepted plan, read as a new answer: spec 028's
  behaviour, unchanged here

## Decisions relied on

- D-10: only the maintainer accepts or declines; a cut item, like a declined opportunity, is not proposed again
- D-14: every write is the App's
- D-16: only a trusted author's comment is an answer
- D-21: a gate session asks through the needs-decision protocol
- D-29: a first-line marker counts only from the App or a trusted author
- D-34: the work serves the product's written direction
- D-38: an accepted goal plan may create the milestone it names
- D-62: an agent's text is told by its marker
- D-68: the `--bot-login`'s relay of a maintainer's answer is that answer on a goal plan

## Issues

## Verification
