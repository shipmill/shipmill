# S-046: A gate tick checks for change first, then walks the work tiers to the next untaken item

status: draft
serves: G-1

## Problem

Every `shipmill gate` tick that gets past the hold, busy, and still-working checks reads the
whole pipeline report: `watch()` in `src/shipmill/gate.py` runs
`skills/github-ship-watch/scripts/watch_state.py --json` (spec 008), and `decide()` keeps the
rows marked `agent: true`, `PRS_OPEN`, and `NEEDS_DECISION`, fingerprints the whole set,
reads UNCHANGED when the fingerprint matches the last launch's within `retry_hours`, and
otherwise starts one session with the full list (spec 005). Two things follow:

- **A quiet tick costs as much as a busy one.** Measured on 2026-10-27 on shipmill/shipmill
  with logging shims, one `watch_state.py` run took about 90 s and 93 `gh` calls, strictly one
  after another, even when nothing had changed since the last tick. About 35 s of it is the
  UNANNOUNCED check (`skills/github-pr-triage/scripts/shipped.py`: one GraphQL query per
  commit in the release range, 31 that day, then one `gh issue view` per issue, 20), and more
  goes to rows the gate never reads: the report-only sections, the host's rows, and
  `shipmill plan --dry-run` in a temporary worktree. The gate decides from a handful of rows
  and pays for all of them, 96 times a day at the default 15-minute interval
- **One stuck finding holds back the rest.** The fingerprint covers the whole set, so a
  finding a session could not clear keeps the set UNCHANGED, and a new finding beside it
  launches a session that is handed the stuck one again, first or last, in no order. The
  maintainer asked for the gate to simply take the next item from a queue and put it to work

## Behaviour

A tick keeps its order up to and including the still-working check (spec 045 moved the prune
after the decision). After it, the tick checks for change; on a change it walks the work
tiers in order and stops at the first item no session has taken, and hands a session that one
item. It never reads the whole work queue to sort it: the order of the checks is the queue.
The full picture stays in `shipmill status`.

### The change check

The tick first asks GitHub whether anything changed since the last walk it recorded, in two
reads:

- one GraphQL query (`src/shipmill/github.py`): the default branch's head SHA; the newest
  release's tag; the open issues and pull requests updated at or after the cursor
  (`issues(filterBy: {since})`, which counts comments and label changes) with their labels;
  the open pull requests' number, labels, draft state, whether the head is in the repo, head
  SHA, and head commit's check rollup state; and the open issues labelled `[operate]
  incident_label`. At most 100 of each, paged past that
- one `gh api repos/<repo>/actions/runs` read of the newest runs: the id, status, conclusion,
  and URL of each run of the policy's release workflow and of an `[operate]` workflow

A change is any of: an issue or pull request updated at or after the cursor; a different
default head, newest release tag, open pull request set, head SHA, draft state, check rollup
state, or open incident set; a release or operate run that finished or failed since the last
walk. Three things on the gate's side count as a change too: no `cursor.json`, a
`handed.json` entry whose `retry_hours` ran out, and a last session that ended dead
(`ended_dead`, `listed_dead`).

The signature (everything but the updated issues) and the cursor go in `cursor.json` in the
gate's state directory (next to `gate.json`): `{"at": <when the last walk started>,
"signature": <digest>}`. The cursor is the walk's start minus `CURSOR_OVERLAP` (5 minutes), so
an update GitHub indexed late is seen on the next tick; an item seen twice costs one more
walk, never a missed one. The check need not be exact: a false change costs one walk, and a
missed one waits for the next sweep. The gate's own sessions' writes are changes; the handed
rule below keeps them from relaunching the same item.

With no change and no sweep due, the tick reads nothing else from GitHub and decides QUIET,
`no change since <cursor>`. A quiet tick takes the hold read, the session list, and the two
change reads: a few seconds.

### The tiers

On a change the tick reads tier 1, and only when that tier holds no item outside
`retry_hours` does it read tier 2, and so on down the list. A tier whose data the change
check already holds costs no further read.

| Tier | Items | Read |
|---|---|---|
| 1 | INCIDENT_OPEN, OPERATE_FAILED: production is broken | none: the change check's incidents and runs |
| 2 | BOT_FAILED, NOT_PUBLISHED, WORK_BRANCH_STALE, BOT_STALLED: the release lane is broken | BOT_FAILED none (the runs); NOT_PUBLISHED one PyPI read for the newest tag; WORK_BRANCH_STALE the work branches; BOT_STALLED from the last sweep |
| 3 | PRS_OPEN (unless `[autonomy] land` is observe, S-040-9): finished work waits to land | none: the change check's open pull requests, except one batched read of the comments of those labelled `needs-decision` or `decided` |
| 4 | VETOED and triage's `DECIDED`: the maintainer answered, and the work waits on the agents | the open items labelled `needs-decision` or `decided`, and the closed pull requests labelled `decided`, with their comments |
| 5 | UPGRADE_PENDING, UPSTREAM_DUE | from the last sweep |
| 6 | triage's other action states (`NEW`, `UNBLOCKED`, `NEEDS_PR`, and the rest) | the triage read of the open issues (`triage_state.py`) |
| 7 | DIRECTION_PENDING, PLANS | from the last sweep |
| 8 | UNANNOUNCED | from the last sweep, or a new release tag's check |

The gate reads a tier with `watch_state.py --json --tier <n>`, a new flag that runs only that
tier's sections and prints only their rows, given the change check's data so it reads none of
it again. A tier's rows keep today's fields (state, subject, detail, and a PRS_OPEN row's
heads), and are its items, except that tier 4 and tier 6 hold one item per triage state, so a
`DECIDED` item never waits behind `NEW` ones. Within a tier, items go in a fixed order: the
order of the table's list, then the subject. A state that `watch_state.py` marks `agent: true`
and this table doesn't name is read in tier 6 until a spec places it.

The trust rules hold in every tier: with `--trusted-only`, an untrusted author's issue or a
pull request whose head is not in the repo is never an item (D-16, S-005-10), and an item that
waits on a reply is never one (S-005-9).

### The sweep

The timed sections run only on a sweep: BOT_STALLED (`shipmill plan --dry-run`),
UPGRADE_PENDING, UPSTREAM_DUE, DIRECTION_PENDING, PLANS, and UNANNOUNCED. A tick sweeps when
there is no `sweep.json`, or its last sweep started `sweep_hours` or more ago, with a change
or not. A sweep runs `watch_state.py --json --sweep` and stores its rows in `sweep.json`
(`{"at": <when it started>, "rows": [...]}`); tiers 2, 5, 7, and 8 read those rows until the
next sweep. A new release tag in the change check runs UNANNOUNCED for that tag alone and puts
its row in `sweep.json`, beside the sweep's.

A new `[agents]` key, `sweep_hours` (`src/shipmill/agents.py`), an integer from 1 to 168,
defaults to 6.

A failed read writes no `cursor.json` or `sweep.json`, so the next tick walks again; the tick
fails as today (S-008-11).

### What a session gets, and UNCHANGED

The first item of the walk that no session was handed within `retry_hours` with the same
fingerprint is the tick's item. The fingerprint is today's (`fingerprint()`, heads included),
over that one item. `handed.json` in the state directory maps each handed fingerprint to the
session and when; an entry drops once `retry_hours` has passed.

- an item is found: LAUNCH, and the prompt names that item alone, with its fix line and its
  tier; the prompt's other paragraphs (roles, levels, identity, headless) are unchanged.
  `gate.json`'s launch records the item's fingerprint, as it records the set's today
- the walk reached the end and every item was handed within `retry_hours`: UNCHANGED, naming
  the first item and when it is retried
- the walk reached the end and found no item: QUIET, as today

The dead-session rules (S-005-20, `ended_dead`, `listed_dead`, `DEAD_STREAK`, SESSION_DEAD)
apply to the item the dead session was handed: its handing doesn't count, so the next tick
hands it again, until `DEAD_STREAK` dead sessions in a row hold that item for `retry_hours`,
and the walk goes on past it.

### Needs-decision notifications

A headless tick (spec 005) records and notifies the items waiting on a decision
(`needs-decision.json`, S-005-12) from tier 4's read. When a walk stops above tier 4, the tick
still runs tier 4's read if the change check shows an updated item labelled `needs-decision`;
otherwise it keeps `needs-decision.json` as it is and sends the reminders due from it
(`remind_hours`) without reading.

### Output

The decision line names how far the walk went: `no change since <cursor>`, or `read tiers
1-3` with the tier of the item it found. `shipmill gate --json` adds `"walk": {"change":
<bool>, "tiers": [<n>, ...], "sweep": <bool>}` and `"item": <state> <subject> | null`.
`shipmill gate --dry-run` runs the change check and the walk the tick would run, and writes no
`cursor.json`, `sweep.json`, or `handed.json`; `--walk` walks with or without a change, and
`--sweep` sweeps whether or not one is due, for a run by hand.

### shipmill status

`shipmill status` (specs 008, 009, 011, 044) keeps the full report: it runs `watch_state.py`
without `--tier` or `--sweep`, every section, and is not changed by this spec.
`watch_command()` (S-008-7) takes the tier or sweep as an argument, and status passes none.

### Docs

- `skills/shipmill-setup/SKILL.md`, The gate: a tick checks for change first, walks the tiers
  to the first untaken item, sweeps every `sweep_hours`, and hands a session that one item
- `skills/github-ship-watch/SKILL.md`: `--tier` and `--sweep`, and that a gate session is
  handed one finding
- `docs/install.md`, where it lists the `[agents]` keys: `sweep_hours`
- Specs 005 and 008, under S-005-9 and S-008-7, and spec 021 under S-021-4: a line saying
  spec 046 changed what the gate reads and when it reads UNANNOUNCED

## Acceptance criteria

- S-046-1: a tick with a `cursor.json` whose signature matches, no issue or pull request
  updated since its cursor, no `handed.json` entry past `retry_hours`, no dead last session,
  and no sweep due runs no `watch_state.py` and reads QUIET `no change since <cursor>`
- S-046-2: each of an updated issue, a new pull request head, a changed check rollup, a moved
  default head, a new release tag, a new open incident, a finished release or operate run, a
  handed item past `retry_hours`, and a dead last session counts as a change and makes the
  tick walk
- S-046-3: the change check is one GraphQL query and one `gh api .../actions/runs` read, paged
  only past 100 open issues or pull requests
- S-046-4: a walk reads the tiers in order and reads no tier below the one where it finds an
  item not handed within `retry_hours`
- S-046-5: with an untaken item in tier 3, a tick reads no `triage_state.py` and runs no
  `shipped.py`
- S-046-6: tiers 1 and 3 run no `gh` read beyond the change check, except tier 3's one batched
  comment read for pull requests labelled `needs-decision` or `decided`
- S-046-7: `watch_state.py --tier <n>` prints only that tier's rows, and neither it nor
  `--sweep` prints a host row or a report-only row
- S-046-8: a tick sweeps when `sweep.json` records none or one `sweep_hours` or more ago, with
  or without a change; tiers 2, 5, 7, and 8 read the sweep's stored rows between sweeps
- S-046-9: a new release tag in the change check runs UNANNOUNCED for that tag alone and stores
  its row with the sweep's
- S-046-10: `[agents] sweep_hours` defaults to 6 and the config refuses a value that is not an
  integer from 1 to 168
- S-046-11: the cursor written is the walk's start minus 5 minutes; a failed read writes no
  `cursor.json` or `sweep.json`
- S-046-12: tiers 4 and 6 hold one item per triage state, and an unlisted `agent: true` state
  is read in tier 6
- S-046-13: a LAUNCH's prompt names exactly one item, the walk's first not handed within
  `retry_hours` with the same fingerprint, with its tier, and `handed.json` records it
- S-046-14: with tier 1's only item handed within `retry_hours` and an item in tier 2, the tick
  launches tier 2's; with every item handed, it reads UNCHANGED naming the first
- S-046-15: a dead session's item is handed again on the next tick, and after `DEAD_STREAK`
  dead sessions in a row the walk goes past it
- S-046-16: with `--trusted-only`, an untrusted author's issue and a pull request whose head is
  not in the repo are never items, and an item waiting on a reply is never one
- S-046-17: a headless walk that stops above tier 4 runs tier 4's read when the change check
  shows an updated `needs-decision` item, and otherwise sends the reminders due from
  `needs-decision.json` without reading
- S-046-18: `shipmill gate --json` prints `walk` and `item`, and the decision line names how
  far the walk went
- S-046-19: `shipmill gate --dry-run` writes no `cursor.json`, `sweep.json`, or `handed.json`,
  and `--walk` and `--sweep` force a walk and a sweep
- S-046-20: `shipmill status` runs `watch_state.py` without `--tier` or `--sweep` and prints
  every section it printed before this spec

## Out of scope

- Batching `shipped.py`'s reads (one GraphQL query per commit and one `gh issue view` per
  issue) into one aliased query each, as #709 did for branches: shipmill/shipmill#754. With
  this spec it leaves the gate's per-tick path anyway
- Lowering the launchd interval (`shipmill launchd --every`, default 15 minutes): cheap quiet
  ticks make a shorter one affordable, which the maintainer can set; the default is its own
  change
- GitHub webhooks or a hosted listener in place of the change check: a gate runs on the
  maintainer's host and polls; the change check is the poll made cheap
- A session that works several items: one item per session; a session may still fix what it
  finds on the way, as today
- What each row means and how `watch_state.py` reads it (specs 008, 011, 021): the gate reads
  fewer sections, in an order, not different ones

## Decisions relied on

- D-15: a hold starts nothing, and a session waiting on the user is stopped after
  `max_wait_minutes`
- D-16: unattended agent sessions work only on trusted authors' items
- D-55: `shipmill status` reports the pipeline; the host's machinery is `shipmill factory`'s
- D-56: the gate's prune runs after the tick's decision
- D-57: a gate tick checks for change before it reads the state, then walks the work tiers in
  order and hands a session the first item no session has taken

## Issues

- shipmill/shipmill#756: S-046-7, S-046-20
- shipmill/shipmill#757: S-046-1, S-046-2, S-046-3, S-046-4, S-046-5, S-046-6, S-046-8, S-046-9, S-046-10, S-046-11, S-046-12, S-046-13, S-046-14, S-046-15, S-046-16, S-046-17, S-046-18, S-046-19

## Verification
