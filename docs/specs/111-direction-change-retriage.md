# S-111: A direction change brings the open issues it touches back to triage

status: approved
serves: G-5

## Problem

Triage weighs an issue against the direction, `docs/product.md`, once: on the day it gives
its verdict. The verdict then stays whatever the maintainer later writes there (D-34). Three
kinds of item keep a verdict the direction no longer supports:

- **A feature postponed for no goal.** Its Postpone (no goal) comment carries
  `` Revisit on: `docs/product.md`, `docs/product/**` ``, and spec 061 reads that line against
  stable releases: the issue reads REVISIT only once a stable tag ships after the direction
  changed. A goal the maintainer adds takes effect when its pull request merges, so the
  feature waits for an unrelated release before anyone looks at it again
- **An issue, opportunity, or plan item whose verdict names a goal the direction no longer
  lists**, because the maintainer removed it or recorded it as dropped (spec 106). Its
  `Serves: G-n` line points at nothing, the issue still reads NEEDS_PR or TRIAGED, and an
  implementer may be dispatched for it. Only the pull request gate (`pr_gate.py`, spec 024)
  notices, after the work is done
- **A request declined on a non-goal the maintainer has since removed.** Triage's Won't fix
  (non-goal) closed it as not planned, or the maintainer declined an opportunity citing the
  non-goal. Nothing reads a closed request again, so the decline outlives its reason

This is item W-3 of the accepted plan shipmill/shipmill#751 for G-5, filed as
shipmill/shipmill#1771, after W-2 (shipmill/shipmill#1766), which makes every postpone carry
the triage comment this spec reads. The plan's Notes bound it: W-3 brings issues back to
triage and never changes the direction (N-3), and a declined request is not argued again
(D-10). The plan says W-3 "reopens one only when the non-goal it hit is gone"; this spec keeps
D-10 by reading such a request due and asking the maintainer, never reopening a declined
opportunity on its own.

## Behaviour

### What a direction change is

The direction is what `shipmill product show --json --local` prints in the checkout of the
default branch's head (spec 024; `--local`, so a component reads its own goals and non-goals,
spec 071). An item is touched by it in one of two ways:

- **By time.** The newest commit on the default branch that changed `docs/product.md` or a
  file under `docs/product/` is newer, by its `committedDate`, than the item's verdict. Read
  with one GraphQL query, the default branch ref's `history(first: 1, path: ...)` aliased for
  the two paths, once per run, and only when an item needs it
- **By content.** The verdict names an id the direction no longer lists: a goal `G-n` absent
  from its goals or present with `state` `"dropped"` (spec 106), or a non-goal `N-n` absent
  from its non-goals. No history is read: the ids are compared with the direction as it is

A goal with `state` `"met"` is still listed. Ids of a product home's direction (spec 071,
`<owner/home> G-n` or `<owner/home> N-n`) are not read. A checkout with no `docs/product.md`
reads no direction, runs no extra query, and every output is as before this spec.

### `triage_state.py`

`skills/github-issue-triage/scripts/triage_state.py` reads the direction, as
`intake_state.py --plans` does (`uvx shipmill==<the plugin's version> product show --json
--local`), when the current directory has `docs/product.md`, and gains:

- **A direction path in `Revisit on:`.** In a postponed issue's newest trusted triage comment
  (as W-2 reads it, D-16), the paths `docs/product.md` and `docs/product/**` are read by time,
  against the default branch, not against the stable tags. The issue reads REVISIT,
  `direction changed in <sha7> after the postpone`, when that commit is newer than the
  comment. Any other path on the same line reads by spec 061 as before, and either reading
  REVISIT makes the issue REVISIT. Without a newer commit and with no other path changed, it
  reads POSTPONED, `waits on <paths>`, as today
- **A verdict naming an id the direction no longer lists.** An open issue whose newest trusted
  triage comment names `Serves: G-n` for a goal no longer listed or dropped, or is a Won't fix
  (non-goal) `it hits N-n` for a non-goal no longer listed, reads REVISIT, noted
  `serves G-n, which the direction no longer lists` (or `records as dropped`), or
  `hits N-n, which the direction no longer lists`. It replaces only NEEDS_PR, UNBLOCKED,
  TRIAGED, and POSTPONED; every other state (an open pull request's IN_PROGRESS, BLOCKED,
  NEEDS_DECISION, and the rest) stands, since `pr_gate.py` already refuses a plan serving an
  unlisted goal. A goal-plan or opportunity issue whose newest verdict is product intake's
  own (`plan`, `opportunity`) is a proposal and is not read this way; product intake reads it.
  A plan item is an ordinary issue here: its triage verdict's `Serves:` line is what is read
- **DECLINE_RECHECK**, a new action state (exit 1). A closed issue, closed as not planned,
  whose newest trusted triage comment is `Triage: **won't fix**: it hits N-n` for a non-goal
  the direction no longer lists, noted `N-n is no longer a non-goal`. Found with one GraphQL
  search per run, `repo:<owner/repo> is:issue is:closed reason:"not planned" "it hits"`, at
  most 100 issues, then filtered by its trusted triage comment. Reopened, the issue is open
  and reads REVISIT by the rule above, so the row ends without a marker

### `intake_state.py`

`skills/product-intake/scripts/intake_state.py` reads the direction the same way, when the
current directory has `docs/product.md`, and gains two action states over the opportunity's
own (exit 1):

- **GOAL_GONE**: an open opportunity (OPPORTUNITY_OPEN, ACCEPTED, or ACCEPTED_INTO) whose
  body's `Serves:` line names a goal no longer listed or dropped, noted `serves G-n, which
  the direction no longer lists` (or `records as dropped`). It reads its own state again once
  the body no longer names that goal, or once a comment by the `--bot-login` carries a line
  `<!-- shipmill:direction-recheck G-n -->` (the question below), the note then
  `asked about G-n`. A HANDED_OFF opportunity is triage's and reads REVISIT there
- **DECLINE_RECHECK**: a DECLINED opportunity whose reason (the note intake already reads)
  names `N-n` for a non-goal the direction no longer lists, noted `declined on N-n, which the
  direction no longer lists`. It reads DECLINED again once a comment by the `--bot-login`
  after the close carries `<!-- shipmill:direction-recheck N-n -->`. Its members still read
  as declined and are never proposed again (D-10); only the maintainer reopening it, which
  makes it OPPORTUNITY_OPEN as any reopened opportunity, changes that

`skills/github-ship-watch/scripts/watch_state.py` counts intake's GOAL_GONE and
DECLINE_RECHECK among the direction-and-plans rows of its sweep (tier 7, D-58), so a gate
session is handed them like a plan action; triage_state's REVISIT and DECLINE_RECHECK are
issues triage owes (tier 6) as REVISIT is today.

### What a session does

- **REVISIT with a direction note** (`skills/github-issue-triage/SKILL.md`,
  `skills/github-issue-triage/references/triage-rubric.md`): triage the issue again against
  today's direction and post a new verdict comment: a feature serving a goal now listed, a
  postpone or won't fix as the rubric says, or an opportunity hand-off. The new comment is
  newer than the commit and names listed ids, so the issue stops reading REVISIT
- **DECLINE_RECHECK in triage**: reopen the issue (its won't fix was triage's own verdict, in
  the `triage-verdict` zone, D-48) and triage it again as REVISIT says. A user's request goes
  to product intake as any request does, so the maintainer still accepts or declines it
- **GOAL_GONE in intake**: on an OPPORTUNITY_OPEN, rewrite the body's `Serves:` line against
  today's goals (`Serves no goal.` when none fits), as intake writes it today. On an
  ACCEPTED or ACCEPTED_INTO opportunity, the maintainer chose it for a goal, so ask one
  needs-decision question (`skills/github-issue-triage/references/needs-decision.md`): name
  the goal, the commit that removed or dropped it, and the options (keep it under a listed
  goal, decline it), with the recheck marker line
- **DECLINE_RECHECK in intake**: never reopen it. Ask the maintainer one needs-decision
  question on the opportunity, with the recheck marker line: the non-goal it was declined on
  is gone since `<sha7>`; reopen it to have it proposed again, or keep it declined. Only the
  maintainer reopens it (D-10)

The question's wording goes in `skills/github-issue-triage/references/comments.md` and
`skills/product-intake/references/` (the direction recheck), with the marker line
`<!-- shipmill:direction-recheck <id> -->` on a line of its own.

## Acceptance criteria

- S-111-1: `triage_state.py` reads a postponed issue whose newest trusted triage comment has `` Revisit on: `docs/product.md`, `docs/product/**` `` as REVISIT, noted `direction changed in <sha7> after the postpone`, when the default branch's newest commit changing `docs/product.md` or a file under `docs/product/` has a `committedDate` newer than the comment, with no stable tag after the comment
- S-111-2: The same issue reads POSTPONED, `waits on docs/product.md, docs/product/**`, when that commit is older than the comment and no stable tag after it changed a direction file; a line naming a direction path and another path reads REVISIT when the other path changed by spec 061's reading
- S-111-3: `triage_state.py` reads the default branch's newest direction commit with one GraphQL query per run, for both paths, and runs it only when a postponed issue's `Revisit on:` line names a direction path
- S-111-4: `triage_state.py` reads an open issue whose newest trusted triage comment says `Serves: G-n` as REVISIT, noted `serves G-n, which the direction no longer lists`, when `product show --json --local` lists no G-n, and noted `serves G-n, which the direction records as dropped` when it lists G-n with `state` `"dropped"`; a G-n with `state` `"met"` changes nothing
- S-111-5: `triage_state.py` reads an open issue whose newest trusted triage comment is `Triage: **won't fix**: it hits N-n` as REVISIT, noted `hits N-n, which the direction no longer lists`, when the direction lists no N-n
- S-111-6: The REVISIT of S-111-4 and S-111-5 replaces only NEEDS_PR, UNBLOCKED, TRIAGED, and POSTPONED: an issue with an open pull request still reads IN_PROGRESS, and a goal-plan or opportunity issue whose newest verdict is `plan` or `opportunity` reads as before
- S-111-7: `triage_state.py` reads a closed issue, closed as not planned, whose newest trusted triage comment is `Triage: **won't fix**: it hits N-n` for an N-n the direction no longer lists as DECLINE_RECHECK, noted `N-n is no longer a non-goal`, and exits 1; an untrusted author's comment of that form reads nothing (D-16), and the closed issues are found with one search query per run of at most 100 results
- S-111-8: `intake_state.py` reads an OPPORTUNITY_OPEN, ACCEPTED, or ACCEPTED_INTO opportunity whose body's `Serves:` names a goal not listed or dropped as GOAL_GONE and exits 1, and reads its own state, noted `asked about G-n`, once a comment by the `--bot-login` carries the line `<!-- shipmill:direction-recheck G-n -->`
- S-111-9: `intake_state.py` reads a DECLINED opportunity whose reason names an N-n the direction no longer lists as DECLINE_RECHECK and exits 1, reads it DECLINED again once a comment by the `--bot-login` after its close carries `<!-- shipmill:direction-recheck N-n -->`, and in both states its members read as declined, never NEW_FEEDBACK
- S-111-10: A marker line `<!-- shipmill:direction-recheck <id> -->` by anyone other than the `--bot-login` settles neither GOAL_GONE nor DECLINE_RECHECK
- S-111-11: With no `docs/product.md` in the current directory, `triage_state.py` and `intake_state.py` run no `product show` and no query of this spec, and their output is byte for byte as before
- S-111-12: `watch_state.py` reports intake's GOAL_GONE and DECLINE_RECHECK rows as actions of its direction-and-plans section, so the gate hands them in tier 7
- S-111-13: github-issue-triage's SKILL.md gives REVISIT with a direction note (triage again against today's direction, a new verdict comment) and DECLINE_RECHECK (reopen, then triage again), and product-intake's SKILL.md gives GOAL_GONE (rewrite `Serves:` on an open opportunity, ask on an accepted one) and DECLINE_RECHECK (ask one needs-decision question with the marker line, never reopen)
- S-111-14: `comments.md` and product-intake's references give the direction recheck question, naming the id, the commit that removed it, and the options, with the marker line `<!-- shipmill:direction-recheck <id> -->` on a line of its own

## Out of scope

- Changing the direction: no state here edits `docs/product.md` or proposes a goal (N-3, D-34)
- A product home's goals and non-goals cited in a component (spec 071): the home's
  coordinator re-reads its own items; a component compares only its own ids
- Postpones whose `Revisit on:` names other paths: they stay with spec 061's stable-tag
  reading
- An open pull request serving a goal no longer listed: `pr_gate.py` refuses its plan already
  (spec 024), and W-4 (shipmill/shipmill#1767) compares it with the issue's verdict
- A goal plan whose goal was dropped: spec 106's goal states and spec 097's outcome cover it
- Telling which goal ids a direction commit added: any direction commit after a postpone
  reads REVISIT, and the session's new verdict settles it

## Decisions relied on

- D-10
- D-16
- D-34
- D-48
- D-58
- D-62

## Issues

## Verification
