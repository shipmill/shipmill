# S-046: A gate tick checks for change first, then hands a session the next item of a work queue

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
after the decision). After it, the tick reads in one of three depths, decides from a work
queue, and hands a session one item.

### The change check

The tick first asks GitHub whether anything changed since the last read it recorded, in two
reads:

- one GraphQL query (`src/shipmill/github.py`): the default branch's head SHA, the newest
  release's tag, the open issues and pull requests updated at or after the cursor
  (`issues(filterBy: {since})`, which counts comments and label changes), and the open pull
  requests' number, draft state, head SHA, and head commit's check rollup state, at most 100
  of each, paged past that
- one `gh api repos/<repo>/actions/runs` read of the newest runs: the id, status, and
  conclusion of each run of the policy's release workflow and of an `[operate]` workflow

A change is any of: an issue or pull request updated at or after the cursor; a different
default head, newest release tag, open pull request set, head SHA, draft state, or check
rollup state; a release or operate run that finished or failed since the last read. The
signature (everything but the updated issues) and the cursor go in `cursor.json` in the
gate's state directory (next to `gate.json`): `{"at": <when the last work read started>,
"signature": <digest>, "read": "work" | "sweep"}`. The cursor is the last read's start minus
`CURSOR_OVERLAP` (5 minutes), so an update GitHub indexed late is seen on the next tick; an
item seen twice costs one more read, never a missed one.

The check need not be exact. A false change costs one work read; a missed change waits for
the next sweep. The gate's own sessions' writes are changes: they move the work, and the
UNCHANGED rule below keeps them from relaunching the same item.

### Three depths

- **none**: no change and no sweep due. The tick reads
  nothing else from GitHub and decides from the queue stored in `queue.json`. A quiet tick
  takes the hold read, the session list, and the two change reads: a few seconds
- **work**: a change. The tick runs `watch_state.py --json --work`, a new flag that reads only
  the sections whose rows can be work for the gate: the release bot's runs (BOT_FAILED,
  NOT_PUBLISHED, WORK_BRANCH_STALE), the operate runs and incidents (OPERATE_FAILED,
  INCIDENT_OPEN), the triage and pull request read (ISSUES, VETOED, PRS_OPEN,
  NEEDS_DECISION, UNTRUSTED), and the hold. It reads no report-only section and no host
  row, and leaves out the sweep's sections below
- **sweep**: no `cursor.json`, or the last sweep started `sweep_hours` or more ago, or a
  change names a new release tag or default head (for the sections those move). The tick
  runs `watch_state.py --json --work --sweep`: the work sections plus UNANNOUNCED (shipped.py),
  BOT_STALLED (`shipmill plan --dry-run`), UPGRADE_PENDING, UPSTREAM_DUE, PLANS, and
  DIRECTION_PENDING. A new release tag runs UNANNOUNCED for that tag only; the timed sections
  run on the sweep alone

A new `[agents]` key, `sweep_hours` (`src/shipmill/agents.py`), an integer from 1 to 168,
defaults to 6. `sweep.json` in the state directory records the last sweep's start, as
`prune.json` does for the prune (spec 045). A failed read writes no cursor, so the next tick
reads again; the tick fails as today (S-008-11).

Every read's rows replace `queue.json`'s, except that a work read keeps the sweep sections'
rows from the last sweep, so a timed finding stays queued until the next sweep clears it.
`shipmill gate --dry-run` runs the change check and the read the tick would run, and writes
no `cursor.json`, `sweep.json`, or `queue.json`; `--read work` and `--read sweep` force a
depth for a run by hand.

### The work queue

`queue.json` holds the gate's work: the rows `decide()` reads, one item per row, except that
an ISSUES row becomes one item per triage state it lists (its `DECIDED #n` part, its `NEW #n
#m` part, and so on), so a decided item never waits behind new ones. An item keeps today's
row fields: state, subject, detail, and a PRS_OPEN row's heads.

Items rank by tier, then within a tier by the order the queue first saw them (oldest first):

1. INCIDENT_OPEN, OPERATE_FAILED: production is broken
2. BOT_FAILED, NOT_PUBLISHED, BOT_STALLED, WORK_BRANCH_STALE: the release lane is broken
3. PRS_OPEN (unless `[autonomy] land` is observe, S-040-9): finished work waits to land
4. VETOED and ISSUES' `DECIDED`: the maintainer answered, and the work waits on the agents
5. UPGRADE_PENDING, UPSTREAM_DUE
6. ISSUES' other states (`NEW`, `UNBLOCKED`, `NEEDS_PR`, and the rest of triage's action
   states)
7. DIRECTION_PENDING, PLANS
8. UNANNOUNCED

NEEDS_DECISION and UNTRUSTED are never items: they wait on a person (S-005-9, D-16), and a
NEEDS_DECISION row still feeds `needs-decision.json` and its notifications (S-005-12) on every
tick, from the stored queue on a tick that reads nothing. A new state that `watch_state.py`
marks `agent: true` and this list doesn't name ranks in tier 6 until a spec places it.

### What a session gets, and UNCHANGED

`decide()` takes the first item, in rank order, that no session was handed within
`retry_hours` with the same fingerprint. The fingerprint is today's (`fingerprint()`, heads
included), over that one item. `handed.json` in the state directory maps each handed
fingerprint to the session and when; an entry drops once its item leaves the queue.

- an item is found: LAUNCH, and the prompt names that item alone, with its fix line and the
  rank it came from; the prompt's other paragraphs (roles, levels, identity, headless) are
  unchanged. `gate.json`'s launch records the item's fingerprint, as it records the set's
  today
- every item was handed within `retry_hours`: UNCHANGED, naming the first item and when it is
  retried
- the queue is empty: QUIET, as today

The dead-session rules (S-005-20, `ended_dead`, `listed_dead`, `DEAD_STREAK`, SESSION_DEAD)
apply to the item the dead session was handed: its handing doesn't count, so the next tick
hands it again, until `DEAD_STREAK` dead sessions in a row hold that item for `retry_hours`.
The next item is not held by it.

The decision line names its depth: `read none (no change since <cursor>)`, `read work`, or
`read sweep`, and `shipmill gate --json` adds `"read": "none" | "work" | "sweep"` and
`"queue": [<state> <subject>, ...]` in rank order.

### shipmill status

`shipmill status` (specs 008, 009, 011, 044) keeps the full report: it runs `watch_state.py`
without `--work`, every section, and is not changed by this spec. `--work` and `--sweep` are
the gate's; `watch_command()` (S-008-7) takes the depth as an argument, and status passes
none.

### Docs

- `skills/shipmill-setup/SKILL.md`, The gate: a tick checks for change first, sweeps every
  `sweep_hours`, and hands a session one item, ranked
- `skills/github-ship-watch/SKILL.md`: `--work` and `--sweep`, and that a gate session is
  handed one finding
- `docs/install.md`, where it lists the `[agents]` keys: `sweep_hours`
- Specs 005 and 008, under S-005-9 and S-008-7, and spec 021 under S-021-4: a line saying
  spec 046 changed what the gate reads and when it reads UNANNOUNCED

## Acceptance criteria

- S-046-1: a tick with a `cursor.json` whose signature matches and no issue or pull request
  updated since its cursor, and no sweep due, runs no `watch_state.py` and decides from
  `queue.json`
- S-046-2: each of an updated issue, a new pull request head, a changed check rollup, a moved
  default head, a new release tag, and a finished release or operate run counts as a change
  and makes the tick read
- S-046-3: the change check is one GraphQL query and one `gh api .../actions/runs` read, paged
  only past 100 open issues or pull requests
- S-046-4: a work read runs `watch_state.py --work`, whose rows come only from the work
  sections; a sweep read adds the sweep sections; neither prints a host row or a report-only
  row
- S-046-5: a tick sweeps when `cursor.json` is missing, when `sweep.json` records none or one
  `sweep_hours` or more ago, and when a new release tag or default head is seen; a new tag
  runs UNANNOUNCED for that tag
- S-046-6: `[agents] sweep_hours` defaults to 6 and the config refuses a value that is not an
  integer from 1 to 168
- S-046-7: a work read keeps the last sweep's rows of the sweep sections in `queue.json`
- S-046-8: the cursor written is the read's start minus 5 minutes; a failed read writes no
  `cursor.json`, `sweep.json`, or `queue.json`
- S-046-9: an ISSUES row becomes one queue item per triage state it lists
- S-046-10: the queue ranks items by the tiers in Behaviour, oldest first within a tier, and an
  unlisted `agent: true` state ranks in tier 6
- S-046-11: a LAUNCH's prompt names exactly one item, the first in rank order not handed
  within `retry_hours` with the same fingerprint, and `handed.json` records it
- S-046-12: with the first item handed within `retry_hours` and a second not, the tick
  launches the second; with every item handed, it reads UNCHANGED naming the first
- S-046-13: a dead session's item is handed again on the next tick, and after `DEAD_STREAK`
  dead sessions in a row it waits `retry_hours` while the next item launches
- S-046-14: NEEDS_DECISION and UNTRUSTED rows are never items, and a tick that reads nothing
  still notifies and records waiting items from the stored queue
- S-046-15: `shipmill gate --json` prints `read` and `queue`, and the decision line names the
  depth
- S-046-16: `shipmill gate --dry-run` writes no `cursor.json`, `sweep.json`, `queue.json`, or
  `handed.json`, and `--read work|sweep` forces the depth
- S-046-17: `shipmill status` runs `watch_state.py` without `--work` and prints every section
  it printed before this spec

## Out of scope

- Batching `shipped.py`'s reads (one GraphQL query per commit and one `gh issue view` per
  issue) into one aliased query each, as #709 did for branches: a separate fix, since it
  speeds `shipmill status` too and changes no behaviour. With this spec it leaves the gate's
  per-tick path anyway
- Lowering the launchd interval (`shipmill launchd --every`, default 15 minutes): cheap quiet
  ticks make a shorter one affordable, which the maintainer can set; the default is its own
  change
- GitHub webhooks or a hosted listener in place of the change check: a gate runs on the
  maintainer's host and polls; the change check is the poll made cheap
- A session that works several items: one item per session; a session may still fix what it
  finds on the way, as today
- What each row means and how `watch_state.py` reads it (specs 008, 011, 021): the gate reads
  fewer sections, not different ones

## Decisions relied on

- D-15: a hold starts nothing, and a session waiting on the user is stopped after
  `max_wait_minutes`
- D-16: unattended agent sessions work only on trusted authors' items
- D-55: `shipmill status` reports the pipeline; the host's machinery is `shipmill factory`'s
- D-56: the gate's prune runs after the tick's decision
- D-57: a gate tick checks for change before it reads the state, and hands a session the next
  item of a ranked work queue

## Issues

## Verification
