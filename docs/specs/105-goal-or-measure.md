# S-105: The direction tells a goal from a standing measure

status: approved
serves: G-7

## Problem

The maintainer decided on 2026-11-26 that every project has one of two parents: a goal,
which ends when its check passes and is written with a check and a horizon (a date or a
release), and a standing measure, held at a threshold for good and written with its
threshold and the source it is read from (shipmill/shipmill#1691). A goal that must stay true
is rewritten as a measure, and a met goal leaves a measure behind.

The direction's grammar (spec 024, spec 027) holds neither kind. Under a goal it takes one
`  measure:` line, from a forge-only registry, and nothing else. So this repository's
direction (shipmill/shipmill#1690) and three other gated repositories' were rewritten the
same day with each kind's fields inside the goal's text:

- a goal: `- G-n: <outcome>. Check: <check>. By: <date or release>`
- a measure: `- G-n: Held: <statement>. Threshold: <value>. Source: <where it is read>`, with
  a `  measure:` line where a registry metric fits

Every reader of the direction still accepts these lines, since they are item text, but none
reads their fields: `shipmill product show --json` gives a goal only `id`, `text`,
`measure`, and `serves`, so no code can tell a goal from a measure, read a check, or see a
horizon pass. The goal states of shipmill/shipmill#1688, the weekly round of G-7, and product
intake's plans all need them. Today intake even proposes a `no-work` plan for a standing
measure (spec 028), which by the decision gets projects only when the maintainer asks.

## Behaviour

### The two forms

The inline form above becomes the grammar: the item line keeps its shape (`- G-<n>:
<text>`), and `src/shipmill/product.py` reads the text of each item of `## Goals` as one of
three kinds.

| Kind | The item's text | Fields |
|---|---|---|
| goal | `<outcome>. Check: <check>. By: <horizon>` | outcome, check, horizon |
| measure | `Held: <statement>. Threshold: <threshold>. Source: <source>` | statement, threshold, source |
| none | any text with neither form's labels | none: a goal written before this spec |

- **A goal** is read by splitting at the first `. Check: ` and the last `. By: `. The
  outcome, the check, and the horizon are each non-empty. The horizon is a date,
  `YYYY-MM-DD` and a valid calendar date, or a release, a version `X.Y.Z` with an optional
  `v` (`0.7.0`, `v1.2.0`), and nothing else follows it: no final period, no further
  sentence
- **A measure** is read by its text starting `Held: `, then splitting at the first
  `. Threshold: ` and the last `. Source: `. Each part is non-empty. The threshold and the
  source are prose; where a registry metric fits, the item's `  measure:` line (spec 027) is
  the threshold code reads, and the threshold sentence may say so
- **None** is any other text. A direction written before this spec keeps checking, and every
  consumer reads such a goal as it does today

Labels are case-sensitive and spaced as written. A goal's text that holds `. Check: ` with no
`. By: ` after it, or `. By: ` with no `. Check: ` before it, or a horizon that is neither a
date nor a version, is malformed; so is a text starting `Held: ` that lacks `. Threshold: `
or `. Source: ` in that order, or any text holding both forms' labels. A `  measure:` line
under a goal of kind goal is malformed too: a goal ends on its check, and a metric held for
good is a measure. `shipmill product check` refuses each malformed goal with exit 1 and one
line naming the file, the line, the goal, and the form it should take, as it refuses any
other line today (Q-1). The item lines of `## Users`, `## Non-goals`, and `## Quality bar`
are not read for kinds.

Nothing migrates: the four directions rewritten on 2026-11-26 already have this form, and a
goal of kind none keeps today's meaning. The item line, the `  measure:` line, and the
`  serves:` line keep their shapes, so the readers that hold their own copy of the item grammar
(`skills/github-pr-triage/scripts/pr_gate.py`, `skills/github-issue-triage/scripts/specs.py`,
`skills/product-intake/scripts/plans.py`, `skills/github-ship-watch/scripts/fleet.py`,
`skills/github-ship-watch/scripts/retro.py`) need no change.

### What `product show --json` returns

Each goal's record (`shipmill product show --json`, `src/shipmill/product.py`) keeps `id`,
`text`, `measure`, and `serves` as today and gains, on every goal:

- `kind`: `"goal"`, `"measure"`, or null
- `outcome`, `check`: the goal's outcome and check, null unless kind is goal
- `by`: `{"date": "2026-12-31"}` or `{"release": "0.7.0"}` (the version as written, `v`
  included), null unless kind is goal
- `past`: for a date horizon, true once that date has ended in UTC (the day after it has
  begun), else false; null for a release horizon and unless kind is goal. Whether a release
  horizon has passed is read from the forge's tags by the consumer, never by `product`, which
  reads no forge
- `held`, `threshold`, `source`: the measure's statement, threshold, and source, null unless
  kind is measure

The text output (`shipmill product show`) prints each item line as written, as today.

### The commands that write them

Beside `product add`, `product edit`, and `product measure` (spec 024, spec 027), two
commands rewrite one goal's line in the working tree, never a commit, and print the line
they wrote:

- `shipmill product goal G-<n> --check <check> --by <horizon>` writes the goal form, keeping
  the goal's outcome: the text before its `. Check: ` for a goal, the whole text for a goal of
  kind none, and refused with exit 2 for a measure (rewrite it with `product edit`). It
  refuses a horizon that is neither a date nor a version, and a goal with a `  measure:` line,
  naming `product measure G-<n> --clear`
- `shipmill product held G-<n> --threshold <threshold> --source <source>` writes the measure
  form, keeping the statement: the text after `Held: ` and before its `. Threshold: ` for a
  measure, the whole text for a goal of kind none, and refused with exit 2 for a goal
  (rewrite it with `product edit`)

`product add goals` and `product edit` take the whole text and refuse a malformed one with
the same message `product check` gives. A component's direction (spec 071) is written and
read the same way.

### The plan reads the kind

A goal plan's Goal section (spec 028, `skills/product-intake/references/plan.md`) carries the
goal's fields in place of today's lone `Measure:` line:

- for a goal: `Check: <check>` and `By: <horizon>`, on their own lines after `Trigger:`
- for a measure: `Threshold: <threshold>` and `Source: <source>`, then `Measure: <the measure
  line, or "none">`
- for a goal of kind none: `Measure: <the measure line, or "none yet">`, as today

`skills/product-intake/scripts/plans.py check` reads the goal's kind from the direction and
exits 2, naming the line, for a Goal section missing a line its kind needs, holding a line of
the other kind, or holding a line twice; it reads the horizon as the direction does. Plans
opened before this spec keep their answer: `check` runs on a plan when it is written or
revised, never on one already answered.

### Intake reads the kind

`skills/product-intake/scripts/intake_state.py --plans` reads a goal's `kind` from
`product show --json`:

- a measure reads no `no-work` PLAN_DUE or PLAN_WAITS: its children are findings, incidents,
  and routine fixes, and it gets a plan only when the maintainer asks for one, so only the
  `requested in #N` trigger holds for it
- a goal and a goal of kind none read every trigger as today

`skills/product-intake/SKILL.md` (Plan a goal) and `references/plan.md` give the Goal
section's lines for each kind, and `docs/flow.md` says a measure is planned only on request.

## Acceptance criteria

- S-105-1: `shipmill product check` exits 0 on a direction whose goals are written in the goal form (`<outcome>. Check: <check>. By: 2026-12-31` and `By: 0.7.0`), in the measure form with and without a `  measure:` line, and with no form, and on this repository's `docs/product.md` as merged on 2026-11-26
- S-105-2: `shipmill product check` exits 1 with one line naming the file, the line, and the goal for each of: `. Check: ` without `. By: `, `. By: ` without `. Check: `, an empty outcome, check, or horizon, a horizon that is neither a valid `YYYY-MM-DD` nor `X.Y.Z` with an optional `v` (`2026-13-01`, `Q4`, `2026-12-31.`), a text starting `Held: ` without `. Threshold: ` and `. Source: ` in that order, a text with both forms' labels, and a `  measure:` line under a goal of kind goal
- S-105-3: a goal's check or outcome that holds a period and a space reads whole: `A. B. Check: C. D. By: 2026-12-31` has the outcome `A. B` and the check `C. D`
- S-105-4: `shipmill product show --json` gives every goal `kind`, `outcome`, `check`, `by`, `past`, `held`, `threshold`, and `source`, with the fields of the other kinds null, and keeps `id`, `text`, `measure`, and `serves` as before
- S-105-5: `past` is true for a date horizon once that date has ended in UTC and false on the date itself, and null for a release horizon, a measure, and a goal of kind none
- S-105-6: `shipmill product goal G-n --check C --by 2026-12-31` rewrites a goal of kind none or goal into the goal form keeping its outcome, prints the line, and exits 2 on a measure, a malformed horizon, or a goal with a `  measure:` line
- S-105-7: `shipmill product held G-n --threshold T --source S` rewrites a goal of kind none or measure into the measure form keeping its statement, keeps its `  measure:` line, prints the line, and exits 2 on a goal of kind goal
- S-105-8: `shipmill product add goals` and `shipmill product edit` refuse a malformed goal text with exit 2 and the message `product check` gives, writing nothing
- S-105-9: `plans.py check` exits 0 on a plan for a goal with `Check:` and `By:` lines, for a measure with `Threshold:`, `Source:`, and `Measure:` lines, and for a goal of kind none with `Measure:` alone, and exits 2 naming the line for a missing line, a line of the other kind, or a line given twice
- S-105-10: `intake_state.py --plans` reads no `no-work` PLAN_DUE or PLAN_WAITS for a goal of kind measure, reads `requested in #N` for it as before, and reads every trigger for a goal of kind goal or none as before
- S-105-11: `skills/product-intake/SKILL.md`, `skills/product-intake/references/plan.md`, and `docs/flow.md` give the two forms, the Goal section's lines for each kind, and that a measure is planned only on request

## Out of scope

- A goal's states (proposed, written, planned, met, dropped), a met goal's record, and the question at a passed horizon: shipmill/shipmill#1688, whose spec reads the fields this one returns
- Reading a measure's value from its source, or from a value the repository publishes: shipmill/shipmill#1446; only registry metrics are read by code, as spec 027 reads them
- A separate section or id prefix for standing measures: a measure keeps its `G-n` id, so every spec's `serves:` line, every plan's marker, and every triage `Serves:` keep naming it
- Writing the direction: only the maintainer merges it (D-34); the commands write the working tree, never a commit
- Rewriting a goal of kind none into a kind: the maintainer chooses its kind with `product goal` or `product held`

## Decisions relied on

- D-34: only the maintainer changes the direction; the commands write the working tree
- D-10: intake proposes plans and the maintainer answers them; a measure's plan only on request

## Issues

## Verification
