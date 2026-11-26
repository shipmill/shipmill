# S-098: The maintainer holds a goal plan until a condition they name

status: approved
serves: G-6

## Problem

A goal plan (spec 028) waits for the maintainer's answer, and the maintainer can give only
three: accept, decline, or an edit. Often the right answer is "not now": the plan is sound,
but it should be decided after a release ships, after another piece of work lands, or after a
date. Today there is no such answer. The plan reads PLAN_OPEN and stays in `fleet.py queue`
(spec 069, a `PLAN` row) and, once shipmill/shipmill#1680 lands, among the WAITS ON YOU
reasons of `shipmill status`, so a plan the maintainer has already put aside nags in every
view until they decline it (which closes it, and stops the `no-work` trigger for its goal) or
answer it early. A reply such as "hold until the next release" is read as an edit, so a
session rewrites the plan around words that asked for no change.

This is item W-4 of the accepted plan shipmill/shipmill#752 for G-6, filed as
shipmill/shipmill#1683, and it builds on W-1 (shipmill/shipmill#1680), which adds the PLAN_OPEN
reason to `shipmill status` that a held plan must leave. The plan's Notes bound it: holding
changes only when a plan is asked about, never who answers it. Accepting a plan stays the
maintainer's `scope` decision (N-3, D-10, spec 030), only a trusted author's reply counts,
the hold included (D-16, D-29), and an agent never changes a plan while it waits (spec 028).

## Behaviour

### The hold answer

A hold is a fourth kind of answer to a plan, read where spec 028 reads every answer
(`plan_answer` in `skills/product-intake/scripts/intake_state.py`): the newest trusted
comment newer than the plan's newest revision, from an OWNER, MEMBER, or COLLABORATOR other
than the `--bot-login`, or the `--bot-login`'s relay naming a maintainer (D-68). Its first
line, matched case-insensitively and with an optional final period, is:

    hold until <condition>

where `<condition>` is exactly one of:

| Condition | Written | Met when |
|---|---|---|
| A date | `YYYY-MM-DD`, a valid calendar date | 00:00 UTC on that date has passed |
| An item closing | `#N` (this repository) or `owner/repo#N` | that issue or pull request is closed (a pull request merged or closed unmerged) |
| A release | `release` | a tag matching `--stable-tag-regex` (default `vX.Y.Z`, no pre-release, the same flag and default as `triage_state.py`'s, spec 061) was created after the hold's comment, its time read as `triage_state.py` reads a stable tag's |

The lines after the first are the maintainer's reason; nothing reads them. A first line that
starts `hold until` is always read as a hold, never as an edit, so no session rewrites a plan
because it was held.

### The state a held plan reads

`intake_state.py --plans` reads a plan whose answer is a hold:

- **PLAN_HELD** while the condition is not met, its note `until <condition>` as written
  (`until 2026-12-15`, `until shipmill/shipmill#1680`, `until release`). PLAN_HELD is not an
  action state: it adds nothing to the exit code, so a run whose only plan is held exits 0
- **PLAN_HOLD_MET** once the condition is met and the plan has not been re-checked since (A
  held plan's re-check, below), its note saying what met it and that the re-check is due:
  `hold met: 2026-12-15; re-check due`, `hold met: <ref> closed; re-check due`, or
  `hold met: <tag>; re-check due`. PLAN_HOLD_MET is an action state (exit 1). A hold whose
  condition is already met when it is posted (a past date, a closed item) reads
  PLAN_HOLD_MET at once
- **PLAN_OPEN** once the plan has been re-checked after its hold was met, as a plan with no
  answer reads, its note saying what met the hold: `hold met: 2026-12-15`,
  `hold met: <ref> closed`, or `hold met: <tag>`

With `--json`, a PLAN_HELD row, a PLAN_HOLD_MET row, and a PLAN_OPEN row whose hold was met, carry a `hold` object:
`until` (the condition as written) and `met_at` (ISO 8601 UTC: the date's 00:00, the item's
`closedAt`, or the tag's creation time; null while not met). Every other row carries no
`hold` key. The help text lists PLAN_HELD and PLAN_HOLD_MET among the plan rows.

### A held plan's re-check

A held plan goes stale while it waits: work it proposes may land through other items, and
what it builds on may change. So when its hold is met, a session checks the plan against the
default branch before it returns to the maintainer.

- On PLAN_HOLD_MET, product intake's session reads each Work item of the plan's body against
  the default branch and the repository's issues, reading trusted text only (D-16), and posts
  one comment on the plan, as the App, whose first line is
  `<!-- shipmill:plan-recheck -->`. Under it, the comment lists each item that is already
  done (what it asks for is on the default branch, or an issue that does it closed as
  completed) and each item that has gone stale (a file, command, spec, or item it names is
  gone or changed so the item no longer reads as written), each with what shows it; with
  neither, it says `Nothing in this plan is done or stale.`
- The re-check is a report: the session never edits the plan's body (spec 028), files
  nothing, and changes no answer. The maintainer decides on the plan as before, with the
  re-check in front of them
- `intake_state.py` counts a `plan-recheck` comment only from the `--bot-login` and only when
  it is newer than the hold's `met_at`; then the plan reads PLAN_OPEN `hold met: ...`. Any
  other author's comment with that first line, or one older than `met_at`, counts for nothing
- A newer trusted answer replaces the hold as before (S-098-9), so a plan answered while it
  reads PLAN_HOLD_MET reads by that answer, and needs no re-check

The newest trusted answer still decides (S-028-9): an accept, a decline, an edit, or another
hold newer than the hold replaces it, so the maintainer lifts a hold by answering the plan.
A hand edit of the plan's body leaves a hold as it is (only an accept goes stale on an edit,
S-028-10). A held plan is an open plan, so its goal reads no PLAN_DUE (S-028-5), and no
plan-item marker is read and nothing is filed for it.

### A hold that counts for nothing

- **Untrusted**: a `hold until` comment by anyone but an OWNER, MEMBER, or COLLABORATOR, a
  comment by the `--bot-login` that is not a relay naming a maintainer, or a relay naming
  anyone else, is no answer (D-16, D-68), so the plan reads as it would without it
- **Malformed**: a first line that starts `hold until` but whose rest is not exactly one
  condition above (an invalid date such as `2026-13-01`, two conditions, `next week`, an empty
  condition) holds nothing. The plan reads PLAN_OPEN with the note `hold not read: <the first
  line>`, so it stays in front of the maintainer, who sees why
- **Unreadable item**: an item condition GitHub answers null for (gone, or a repository the
  token can't read) holds nothing either: PLAN_OPEN with the note `hold not read: <ref> can't
  be read`. A failed GitHub read is a failure (exit 2), as any other

### Where a held plan leaves and comes back

- `skills/github-ship-watch/scripts/watch_state.py`: PLAN_HELD is not in `PLAN_ACTION`, so the
  PLANS row never lists it and `shipmill gate` (`src/shipmill/gate.py`, `src/shipmill/walk.py`)
  starts no session for it; no agent touches a held plan (spec 028). PLAN_HOLD_MET is in
  `PLAN_ACTION`, so the PLANS row lists it and the gate starts a session for the re-check
- `skills/github-ship-watch/scripts/fleet.py queue`: `INTAKE_KINDS` maps only PLAN_OPEN to
  `PLAN`, so a held plan, and one whose re-check is due, is no row. A plan re-checked after
  its hold was met is a `PLAN` row again, waiting since the later of its newest revision and
  the hold's `met_at`, so a plan held for a month does not come back as the oldest item of
  the queue
- `src/shipmill/status.py`: the WAITS ON YOU reason shipmill/shipmill#1680 adds for a
  PLAN_OPEN plan is not added for a PLAN_HELD or PLAN_HOLD_MET one, and is added again once
  the plan is re-checked after its hold was met
- `src/shipmill/item_status.py` and `src/shipmill/queue.py` (`shipmill status --item N`, the
  records of spec 094 and the summary of spec 091): a held plan's holder is `postponed`, not
  the maintainer, with one condition `held until <condition>` whose who is an event and whose
  clear is the condition met; once met, until it is re-checked, its holder is the agent;
  once re-checked it reads as an unanswered plan reads today

### Docs

- `skills/product-intake/SKILL.md`: the hold answer, PLAN_HELD, that a session never acts
  on a held plan, and PLAN_HOLD_MET's re-check comment
- `skills/product-intake/references/plan.md`: the plan's triage comment names the fourth
  answer, `hold until <a date, #N, or release>`, beside accept, decline, and an edit
- `skills/github-ship-watch/SKILL.md`'s Fleet section: a held plan is no `PLAN` row until its
  condition is met

## Acceptance criteria

- S-098-1: A plan whose newest trusted answer's first line is `hold until 2026-12-15`, `hold until #12`, `hold until o/r#12`, or `hold until release` (any case, an optional final period) reads PLAN_HELD with the note `until <condition>`, and `intake_state.py --plans` exits 0 when PLAN_HELD is its only plan row
- S-098-2: A plan held `until 2026-12-15` reads PLAN_HELD before 2026-12-15T00:00Z and, until it is re-checked, PLAN_HOLD_MET with the note `hold met: 2026-12-15; re-check due` from then on; a hold naming a date already past reads PLAN_HOLD_MET at once
- S-098-3: A plan held until an issue or pull request, in this repository or another, reads PLAN_HELD while that item is open and, until it is re-checked, PLAN_HOLD_MET with the note `hold met: <ref> closed; re-check due` once it is closed, merged or not
- S-098-4: A plan held `until release` reads PLAN_HELD while no tag matching `--stable-tag-regex` (default `vX.Y.Z`) was created after the hold's comment (a pre-release or an older tag counts for nothing), and, until it is re-checked, PLAN_HOLD_MET with the note `hold met: <tag>; re-check due` once one was
- S-098-5: With `--json`, a PLAN_HELD row has `hold` with `until` and a null `met_at`, a PLAN_HOLD_MET row and a PLAN_OPEN row whose hold was met have `hold` with `met_at` the date's 00:00 UTC, the item's `closedAt`, or the tag's creation time, and no other row has a `hold` key
- S-098-6: A `hold until` comment by an author who is not an OWNER, MEMBER, or COLLABORATOR, or by the `--bot-login` without a relay naming a maintainer, changes nothing: the plan reads as it does without that comment; a relay by the `--bot-login` naming a maintainer whose answer line is a hold reads PLAN_HELD
- S-098-7: A trusted first line starting `hold until` whose rest is not one condition (an invalid date, two conditions, other text, nothing) reads PLAN_OPEN with the note `hold not read: <the first line>`, and never PLAN_ANSWERED
- S-098-8: A hold naming an item GitHub answers null for reads PLAN_OPEN with the note `hold not read: <ref> can't be read`
- S-098-9: A trusted accept, decline, edit, or hold newer than a hold replaces it as the newest answer, and a hand edit of the plan's body after a hold leaves the plan PLAN_HELD
- S-098-10: A goal whose only open plan is PLAN_HELD reads no PLAN_DUE, and `watch_state.py`'s PLANS row does not list a PLAN_HELD plan, so `shipmill gate` starts no session for it
- S-098-11: `fleet.py queue` lists no row for a PLAN_HELD or PLAN_HOLD_MET plan, and lists a plan re-checked after its hold was met as a `PLAN` row waiting since the later of its newest revision and the hold's `met_at`
- S-098-12: `shipmill status` adds no WAITS ON YOU reason for a PLAN_HELD or PLAN_HOLD_MET plan, and adds the PLAN_OPEN reason of shipmill/shipmill#1680 for the same plan once it is re-checked after its hold was met
- S-098-13: `shipmill status --item N` and its record for a PLAN_HELD plan give the holder `postponed` with the condition `held until <condition>` cleared by an event, for a PLAN_HOLD_MET plan the agent, and for the same plan re-checked after its hold was met the maintainer as for an unanswered plan
- S-098-14: `skills/product-intake/SKILL.md`, `skills/product-intake/references/plan.md`, and `skills/github-ship-watch/SKILL.md` say what the Docs section lists
- S-098-15: A plan whose hold was met reads PLAN_HOLD_MET, an action (exit 1), until a comment by the `--bot-login` whose first line is `<!-- shipmill:plan-recheck -->` is newer than the hold's `met_at`, and PLAN_OPEN with the note `hold met: ...` after it; the same first line by any other author, or older than `met_at`, changes nothing, and `watch_state.py`'s PLANS row lists PLAN_HOLD_MET as an action
- S-098-16: product-intake's SKILL.md gives PLAN_HOLD_MET's step: read each Work item against the default branch and the repository's issues from trusted text only, post one `plan-recheck` comment listing the items already done and the items gone stale, each with what shows it, or `Nothing in this plan is done or stale.`, and never edit the plan's body, file anything, or change its answer

## Out of scope

- Who decides a plan: a hold only changes when a plan is asked about; accepting or declining
  stays the maintainer's `scope` decision at floor `ask` (N-3, D-10, spec 030), and no hold
  accepts, declines, or files anything
- Holding any other item (an opportunity, a spec pull request, a needs-decision question):
  only goal plans, as W-4 asks; a postponed issue already has its `Revisit on:` line (spec 061)
- Reminding the maintainer when a hold is met: the plan returns to the queue and to `shipmill
  status`, and a notification is a later request (spec 069's Out of scope)
- A session rewriting a plan when its hold is met: spec 028 keeps an open plan changed only
  by the maintainer's answer, so the re-check is one comment and never edits the body
- Conditions beyond the three, or several in one hold (a path changing, a milestone closing,
  "or"): one condition per hold; a later request may add more
- Listing held plans as a report-only row in the watch: `intake_state.py` and `shipmill status
  --item` already name them

## Decisions relied on

- D-10: only the maintainer accepts or declines a plan; a hold decides neither
- D-16: only a trusted author's reply is an answer, a hold included
- D-29: a marker or first line counts only from a trusted author or the App
- D-55: `shipmill status` reports what waits on whom in the pipeline
- D-68: the `--bot-login`'s relay of a maintainer's answer is that answer, a hold included

## Issues

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
