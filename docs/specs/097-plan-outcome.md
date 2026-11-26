# S-097: A finished plan says whether the goal moved, and the next plan starts from what is missing

status: approved
serves: G-6

## Problem

Spec 028 turns a goal of `docs/product.md` into a plan the maintainer accepts, and files its
items as sub-issues of the plan. Its Order section says why the work runs in that order and
what reaching the goal looks like once the work is done. Nothing reads that end state again.
When the last item closes, `triage_state.py` reads the plan UNBLOCKED like any parent, triage
closes it with the parent's close comment, a list of its children and how they closed, and
`intake_state.py --plans` reads the goal `no-work` again at once, since nothing open serves it.
The next plan is written from a blank page: it neither knows nor says whether the last one
worked, and the maintainer never hears whether the end state the plan promised now holds.

This is item W-3 of the accepted plan shipmill/shipmill#752 for G-6, filed as
shipmill/shipmill#1682: when an accepted plan's work has all closed, the maintainer hears
whether what the plan's Order said reaching the goal looks like now holds, and the goal's next
plan starts from what is still missing. It refines spec 028 and keeps every decision where
that spec put it: the outcome is a report, and the next plan is still proposed by intake and
accepted or declined by the maintainer (D-10, N-3).

## Behaviour

### Where it lives

- `skills/product-intake/scripts/intake_state.py`: the PLAN_DONE row, the `follows` note and
  fields on a goal's PLAN_DUE and PLAN_WAITS rows, and reading the comments of a goal's
  newest plan closed as completed
- `skills/product-intake/scripts/plans.py`: the optional `Follows:` line of the plan
  grammar (`check`)
- `skills/product-intake/SKILL.md` (step 6, Plan a goal, and the Report) and
  `skills/product-intake/references/plan.md`: the outcome comment and how the next plan reads
  it
- `skills/github-issue-triage/scripts/triage_state.py`,
  `skills/github-issue-triage/references/triage-rubric.md`, and
  `skills/github-issue-triage/references/comments.md` (A parent's close): a plan whose work
  has closed is product intake's to close, not triage's
- `skills/github-ship-watch/scripts/watch_state.py`: PLAN_DONE is an action of the PLANS row,
  so `src/shipmill/gate.py` starts a session for it as for any PLANS action

### When the work has closed

`intake_state.py --plans` reads a plan issue PLAN_DONE, an action (exit 1), when either holds:

- **Open, its work closed:** the plan reads as PLAN_FILED would today (accepted, every item
  filed and in the named milestone), and every item's issue is closed: each filed `feature`
  and `fix` item's carrier and each `existing` item of this repository, whatever the reason
  it closed. Its note reads `work closed: W-1 #a completed, W-2 #b not planned, ...`
- **Closed as completed without an outcome:** the plan is its goal's newest plan, closed as
  completed, and no outcome comment (below) came after its last close. Its note reads
  `closed without an outcome`. A plan closed as completed that is not its goal's newest
  reads nothing, as today, so plans closed before this spec give one outcome at most per
  goal

An `existing` item of another repository is not read and does not hold the plan open. An
open plan with an item still open reads PLAN_FILED, as today.

`triage_state.py` reads a plan issue (labelled `goal-plan`, its newest triage comment
intake's `Triage: **plan**`) whose holds have all closed as TRIAGED, never UNBLOCKED, with
the note `work closed; product intake reports the outcome`, so triage never closes a plan
with the parent's close comment. While a hold is open it reads BLOCKED, as today.

### The outcome

On PLAN_DONE, product intake's session reads the plan's Order, the end state it names, and
checks it against the default branch and the plan's items: the code, the specs the items
link and their status, how each item closed. It reads only trusted text: the plan's body,
the App's and trusted authors' comments, and the merged code and specs (D-16). Then, for an
open plan, it closes the plan as completed (`shipmill gh issue close <P> --reason
completed`) and posts the outcome comment after the close, so `intake_state.py` dates it
there; on a plan closed already it posts the comment alone. From plan.md:

    <!-- shipmill:plan-outcome -->
    @<maintainer> The work of this plan has closed: W-1 #a completed, W-2 #b not planned.

    The Order said reaching the goal looks like: <the end state, quoted from the Order>

    Holds:
    - <a part of the end state that holds, and what shows it>

    Still missing:
    - <a part of the end state that doesn't hold, and why>

- The marker is the first line. An outcome comment counts only from the `--bot-login` or an
  OWNER, MEMBER, or COLLABORATOR (D-29), and a trusted author's comment carrying the agent
  marker counts only from the `--bot-login` (D-62)
- `@<maintainer>` is each user the `--role maintainer=` flag gives, so the maintainer hears it;
  without the flag the line starts at `The work`
- `Holds:` and `Still missing:` are each followed by list items; a part that has none says
  `- nothing`. An Order that names no end state is `Still missing:` with
  `- the Order named no end state`
- The outcome is a report, never a decision: it changes no goal, adds no measure (D-34), and
  never declares the goal met (G-7's plan, #566)

### The next plan

When a goal's newest plan is closed as completed with a trusted outcome comment after its
last close, the goal's PLAN_DUE and PLAN_WAITS rows add `; follows #P` to their note, and with
`--json` carry `follows` (P) and `missing`, the outcome's `Still missing:` list items as
written, empty for `- nothing`. A goal whose newest plan reads PLAN_DONE never reads PLAN_DUE
for the `no-work` trigger: the outcome comes first. Every trigger reads as spec 028 says;
this spec changes only the note and the fields.

The session that proposes the plan for such a row:

- Adds `Follows: #P` to the Goal section, on its own line after the `Measure:` line.
  `plans.py check` accepts at most one such line there, of the form `Follows: #<n>`, and
  exits 2 naming the line for any other `Follows:` line
- Answers each `missing` line in the new plan: a Work item that reaches it, or a line under
  Notes saying why this plan leaves it out
- Says in the Order what the last plan left missing and how this one reaches it

A plan without a `Follows:` line still checks, so plans before this spec and a goal's first
plan read as today.

### Report

Intake's report lists each outcome posted this pass with the plan, how many parts hold, and
the still-missing lines, after the plans filed.

## Acceptance criteria

- S-097-1: `intake_state.py --plans` reads an open accepted plan whose filed items and `existing` items of this repository are all closed as PLAN_DONE, an action, its note naming each item, its issue, and how it closed; with an item still open it reads PLAN_FILED
- S-097-2: An `existing` item of another repository neither holds a plan in PLAN_FILED nor is read
- S-097-3: A goal's newest plan closed as completed with no trusted outcome comment after its last close reads PLAN_DONE with the note `closed without an outcome`, and an older completed plan of the same goal reads nothing
- S-097-4: A comment whose first line is `<!-- shipmill:plan-outcome -->` counts as the outcome only from the `--bot-login` or an OWNER, MEMBER, or COLLABORATOR, one by a trusted author other than the `--bot-login` carrying the agent marker counts for nothing, and one posted before the plan's last close counts for nothing
- S-097-5: `triage_state.py` reads a plan issue with intake's `Triage: **plan**` comment whose holds have all closed as TRIAGED with the note `work closed; product intake reports the outcome`, never UNBLOCKED, and reads any other parent whose holds closed as UNBLOCKED as before
- S-097-6: No `no-work` PLAN_DUE or PLAN_WAITS is read for a goal whose newest plan reads PLAN_DONE
- S-097-7: For a goal whose newest plan closed as completed with a trusted outcome, PLAN_DUE and PLAN_WAITS notes end `; follows #P`, and with `--json` the row carries `follows` and `missing`, the outcome's `Still missing:` list items in order, empty when the list is `- nothing`
- S-097-8: `plans.py check` exits 0 on a plan whose Goal section has one `Follows: #<n>` line after `Measure:` and on one with none, and 2 naming the line for a `Follows:` line not of that form, a second one, or one outside the Goal section
- S-097-9: `watch_state.py` lists PLAN_DONE in the PLANS row as an action, and `shipmill gate` starts a session for it
- S-097-10: product-intake's SKILL.md and plan.md give PLAN_DONE's step: check the Order's end state against trusted text only, close an open plan as completed and then post the outcome comment, with the marker first, the maintainer named, and the `Holds:` and `Still missing:` lists; and they never let it change a goal, add a measure, or call the goal met
- S-097-11: product-intake's SKILL.md tells the session proposing a plan for a row with `follows` to write `Follows: #P`, to answer each `missing` line with a Work item or a Notes line saying why it is left out, and to say in the Order what the last plan left missing
- S-097-12: github-issue-triage's comments.md (A parent's close) and triage-rubric.md say a goal plan whose work has closed is product intake's to close with its outcome, never closed with the parent's close comment

## Out of scope

- A goal that is met, and a met goal still getting a `no-work` plan: G-7's plan, shipmill/shipmill#566, with the `stalled` trigger
- A measure for G-6 or any goal, or a count of plans proposed, accepted, or finished: the maintainer's (D-34), and spec 027's registry
- A plan changed by an agent while it waits for the maintainer's answer: spec 028 keeps an open plan changed only by the answer; the outcome is posted only once the plan's work has closed, and never edits its body
- A `## Check` on a plan: the plan grammar has no such section, an Order's end state is prose rather than a command, and a body edit after the accept reads `edited after accept`
- Reopening a plan, or filing new items on it, when something is still missing: the next plan proposes that work, and the maintainer accepts or declines it (D-10)
- Plans across repositories (D-46, D-47): an `existing` item of another repository is left unread

## Decisions relied on

- D-10: intake proposes and reports; the maintainer accepts or declines the next plan
- D-14: every write is the App's
- D-16: the outcome is read from trusted text only
- D-29: a first-line marker counts only from the App or a trusted author
- D-34: the outcome adds no measure and changes no goal
- D-46: a plan across repos is the product home's, left out here
- D-58: PLANS is a timed section the gate reads on a sweep
- D-62: a trusted author's text carrying the agent marker is an agent's

## Issues

- shipmill/shipmill#1710: S-097-1, S-097-2, S-097-3, S-097-4, S-097-6, S-097-7
- shipmill/shipmill#1711: S-097-5, S-097-12
- shipmill/shipmill#1712: S-097-8, S-097-9, S-097-10, S-097-11

## Verification

- S-097-1: read `gh_filing` in `intake_state.py`: once no item is unfiled or outside the milestone, `closed_states` reads each filed carrier and each `existing` issue of this repository in one batched query, and every one closed reads PLAN_DONE `work closed: W-n #a <how>`, any open one PLAN_FILED; after a partial accept (spec 096) only the kept items are read and the note ends `dropped: <ids>`; PLAN_DONE is in `PLAN_ACTION`; holds
- S-097-2: an `existing` item naming another repository adds no number to the state read nor to the note; holds
- S-097-3: `plan_state` reads a plan closed as completed only when `newest_plans` names it its goal's newest and `plan_outcome` finds no outcome at or after its `closedAt`; any other completed plan reads nothing; holds
- S-097-4: `plan_outcome` takes a comment whose first line is the marker from a `PLANS.trusted` author, drops a non-`--bot-login` author's comment carrying the agent marker, and drops one created before `closedAt`; holds
- S-097-5: read `classify_open` in `skills/github-issue-triage/scripts/triage_state.py`: once every hold of an issue closed, `goal_plan` (labelled `goal-plan`, its newest triage comment by an OWNER, MEMBER, or COLLABORATOR or the `--bot-login` starting `Triage: **plan**`) returns TRIAGED `work closed; product intake reports the outcome` before the `## Check` and UNBLOCKED branches, and a hold still open returns BLOCKED before it; any other parent reaches UNBLOCKED as before; holds
- S-097-6: `plan_rows` skips the `no-work` trigger for a goal in `finished` before reading the room, so neither PLAN_DUE nor PLAN_WAITS is read for it; a request still is; holds
- S-097-7: `plan_rows` builds each goal's row through `row()`, which appends `; follows #P` and sets `follows` and `missing` (`still_missing` of the outcome, empty for `- nothing`), and `plan_json` prints both; holds
- S-097-8: `plans.py` `follows_line` accepts one `Follows: #<n>` line in Goal after `Measure:` and reports any other `Follows:` line, a second one, or one in another section, with its line; `check` exits 2 on any; holds
- S-097-9: `watch_state.py`'s `PLAN_ACTION` holds PLAN_DONE, so `plans_rows` lists it in the PLANS row and `plan_line` accepts it, and `plans_waiting` keeps reading PLAN_OPEN alone; `shipmill gate`'s `decide` launches for the PLANS row with no change to `gate.py`; holds
- S-097-10: product-intake's SKILL.md lists PLAN_DONE and gives its step, and plan.md its outcome template with the marker first, the maintainer named, and the two lists; holds
- S-097-11: product-intake's SKILL.md and plan.md tell the session proposing a plan for a `follows` row to write `Follows: #P` after `Measure:`, answer each `missing` line, and say in the Order what was left missing; holds
- S-097-12: read `skills/github-issue-triage/references/comments.md` (A parent's close) and `triage-rubric.md` (the UNBLOCKED row): both say such a plan reads TRIAGED with that note, is product intake's to close with its outcome, and is never closed with the parent's close comment; holds
