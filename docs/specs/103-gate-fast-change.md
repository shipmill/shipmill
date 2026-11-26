# S-103: A gate acts on a change within minutes, and its session starts from the gate's read

status: approved
serves: G-1

## Problem

A change on GitHub reaches a gate session's first step late, twice over
(shipmill/shipmill#1626, grouping #1515 and #1518):

- **The gate notices late.** The gate polls on its launchd interval, 15 minutes by default
  (`src/shipmill/launchd.py`, `DEFAULT_EVERY`), so "a maintainer's answer, a failed check or a
  new issue waits 7.5 minutes on average, up to 15, before anything reacts" (#1518). Polling
  more often multiplies the GraphQL change check's points by the same factor (spec 046), and the
  hold read before it (`gh issue list`, GraphQL too) with it, so the delay can't be cut by
  turning the interval down
- **The session reads it all again.** The tick read the state seconds before it launched the
  session, and the change check's data is already in `known.json` for the tier reads, but the
  session gets none of it: its prompt says "Rerun watch_state.py for the details"
  (`src/shipmill/gate.py`, `UNTRUSTED`), and it reads the repo in full. #842 measured that as
  "17 to 31% of a headless session's main-thread time (36 min in one repo, 22.5 min in
  another), 44 to 121 s a call" (#1515)
- **Each walk reads tier 6 whole.** A walk that reaches tier 6 runs `triage_state.py` over every
  open issue, though the change check already knows which few items changed since the cursor
  (#1515, "Updating the snapshot by changes only")

The requests come from the maintainer's own fleet of 24 gates on one host. Success, from #1626:
a gate notices a change within a minute or two at no more GraphQL points an hour than today; a
session launched on a state nothing changed since reads no repo state before its first step and
decides as a session that read it fresh would.

## Behaviour

This spec extends spec 046 (the change check, the tiers, `cursor.json`, `known.json`), spec 061
(handing by subject, `handed.json`), and spec 093 (the tick's reads go as the App's read token:
every read below that a tick makes goes as spec 093 says). It has three parts, each buildable
on its own in this order: the pre-check, the session's snapshot, and the patched tier 6 read.

### Part 1: the pre-check

**What it reads.** A set of conditional REST reads (`If-None-Match` with the ETag GitHub gave
last time), each reduced to a digest of the fields that matter:

| Read | Digest | A move means |
|---|---|---|
| `repos/{repo}/issues?state=all&sort=updated&direction=desc&per_page=1` | the newest item's number and `updated_at` | an issue or pull request was opened, edited, commented on, labelled, pushed to, or closed: this covers spec 046's updated items, a pull request's new head, its labels and draft state, the open incidents, and the `shipmill-hold` issues |
| `repos/{repo}/git/ref/heads/{default}` | the head SHA | the default branch moved |
| `repos/{repo}/releases/latest` | the tag, or none on a 404 | a new release |
| `repos/{repo}/actions/workflows/{file}/runs?per_page=10`, one per watched workflow (`watched()`, D-58) | each run's id, status, and conclusion | a release or operate run started or finished |
| `repos/{repo}/actions/runs?per_page=10` | `total_count`, and each run's id, status, and conclusion | an Actions run started or finished anywhere in the repo: the default head's and the open pull requests' checks, which don't move a pull request's `updated_at` (#1518) |

A 304 answer is no move. A 200 answer is a move only when its digest differs from the one kept,
so a new ETag over the same content (another token, a header GitHub changed) is no move. A
failed read (anything but 200, 304, and the latest release's 404) is a move: the tick goes on to
the change check, which fails as a failed read does today (S-008-11).

The digest rules live once, in `skills/github-ship-watch/scripts/precheck.py` (Python 3.10, the
standard library, `gh api -i`), which the gate runs and `watch_state.py` imports (Part 2).

**What it keeps.** `precheck.json` in the gate's state directory, beside `cursor.json`: each
read's path, ETag, and digest; `checked`, when the change check last ran; `pending`, when a move
was first seen that no change check has read yet, or null; `hold`, the open `shipmill-hold`
issues the last hold read found; and `flight`, what was in flight at the last change check (spec
048). Like `handed.json` it is a cache of what the forge holds (N-2): deleted, the next tick
reads every answer as a move and runs the change check, never missing one. A dry run writes no
`precheck.json`.

**When the change check runs.** The pre-check is the tick's first GitHub read: it runs after the
Claude credential and the session list and `attend` (spec 003), before the hold check. The
change check is **wanted** when the pre-check moved, `pending` is set, or a gate-side change is
due (no `cursor.json`, a hand past `retry_hours` not yet marked idle, a dead last session, a
sweep due, a pull request queued for the land window, spec 056), or `checked` is 60 minutes or
more ago (the floor, for what the pre-check can't see: an outside App's check run, a run that
finished behind 10 newer ones, a reaction). It **runs** when it is wanted and `checked` is at
least `--every` minutes ago, or there is no `checked`. So the change check runs at most once in
any `--every` minutes, as it does today with the tick on that interval.

- **Not wanted:** the tick reads nothing else from GitHub. It runs the hold, busy, and
  still-working checks with the hold `precheck.json` keeps, and when none of them decides, it
  decides QUIET `no change since <cursor>; pre-check unchanged`, ending with what was in flight
  at the last change check (spec 048). It runs no App check, no role resolution, and no
  `--refresh` fetch
- **Wanted, not yet due:** the tick sets `pending` (keeping an earlier one) and decides QUIET
  `change seen at <HH:MM>; the change check runs at <HH:MM> (--every <N>)`, reading nothing
  else from GitHub as above
- **Runs:** the tick goes on as today: `--refresh`, the hold read (which `precheck.json` then
  keeps), busy, still working, the App check, the roles, the change check, and the walk. Once
  the change check's reads went through it sets `checked` to the tick's start and clears
  `pending`; a failed read keeps both, so the next tick that may tries again

A hold opened between change checks is read at the next one: a launch only ever follows a
change check, so the hold read before it still stops every launch (D-15). A paused credential
or host (specs 089, 095) is probed, and the App's identity checked, only on a tick that runs the
change check, so a shorter launchd interval probes no more often than today.

`{default}` is the default branch the last change check read, kept in `precheck.json`; before
the first, the checkout's `origin/HEAD`.

`--walk` and `--sweep` force the change check whatever `checked` says, for a run by hand.

**The intervals.** `shipmill gate` gains `--every N` (minutes, 5 to 1440, default 15): the
least time between two change checks. `shipmill launchd` keeps `--every N` (same range and
default) and passes it to the gate in the job's arguments, and gains `--check-every M` (minutes,
1 to N, default 2): the job's `StartInterval`, how often the pre-check runs. A job written
before this spec has no `--every` in the gate's arguments and its old `StartInterval`, so it
runs the pre-check on its old interval and the change check at most every 15 minutes: never
more points than before, and no faster until `shipmill launchd` writes it again.
`cli_fix` (`src/shipmill/launchd.py`) keeps a job's `--every` and `--check-every` when it
writes the job again.

**What it records.** `tick.json` (spec 048) and `shipmill gate --json`'s `walk` gain
`"precheck": {"moved": [<read>, ...], "requests": <n>, "not_modified": <n>, "due": <time> |
null}`: the reads that moved, the reads made, how many answered 304, and when a pending change
check runs.

### Part 2: the session starts from the gate's read

**The snapshot.** A walk that launches a session writes `snapshot.json` in the state directory
before the launch:

- `at`: the walk's start; `flags`: the state read's flags (`--trusted-only`, `--bot-login`, the
  role flags, `StateRead.flags()`), since rows read with other flags are other rows (D-16)
- `precheck`: the pre-check's digests the tick read, the snapshot's version of the forge
- `tiers`: the tiers the walk read, and `rows`: every row they printed, with the sweep's stored
  rows (spec 046), as `watch_state.py --json` prints them

It is a local cache of the forge, like `known.json` (N-2): the session never takes a row from it
without checking that the forge still matches.

**The prompt.** A launched session's prompt (`src/shipmill/gate.py`, `prompt`) replaces "Rerun
watch_state.py for the details" with `Run watch_state.py --snapshot <path> for the details: it
reads the state again when it changed since the gate read it.`, `<path>` being the snapshot's
absolute path. The rest of `UNTRUSTED` is unchanged.

**The read.** `watch_state.py --snapshot PATH` (`skills/github-ship-watch/scripts/watch_state.py`)
uses the snapshot only when it is **fresh**:

- the file exists, reads as the JSON the gate writes, its `at` is less than 15 minutes old, and
  its `flags` equal the flags of this run
- the pre-check, run again now by `precheck.py` with the session's own token, gives the same
  digest for every read the snapshot holds

A fresh snapshot prints its rows, as `--json` or the table, for the tiers it holds and the
sweep's sections, and one stderr line `read from the gate's snapshot of <at> (tiers <span>)`.
It runs no GraphQL query and no REST read but the pre-check's. Anything else, a missing,
unreadable, old, or other-flags snapshot, or a moved digest, reads the state fresh exactly as
without `--snapshot`, after one stderr line `snapshot not used: <why>`. A snapshot is never an
error: the forge stays the source.

Only the session's first read moves to the snapshot. Every read a write depends on stays fresh
as today: `pr_gate.py` before a land, `triage_state.py` before a close or a label, and the
skills' other state scripts take no `--snapshot`.

The skills that tell a gate session to read the state first (`skills/github-ship-watch/SKILL.md`,
`skills/github-issue-triage/SKILL.md`, `skills/github-pr-triage/SKILL.md`) say to pass the
`--snapshot` the prompt names, and that it falls back by itself.

### Part 3: a walk patches tier 6 by the items that changed

`snapshot.json` also keeps `triage`: tier 6's reading of each open issue, by number: its
triage state and note as `triage_state.py --json` gives them; `links`, the numbers its reading
depends on (its `Depends on` lines, its parent and sub-issues, the members of a cycle through
it, the pull requests that name it); and `due`, the earliest time its reading changes by the
clock alone (a hand-off, an assignment, or a check falling due, a postpone's window), or null.
With them it keeps `inputs`, a digest of the repo-wide inputs tier 6 reads (the newest stable
tag, the milestones, the trusted roles), and `reconciled`, when tier 6 was last read in full.

A walk that reads tier 6 runs `watch_state.py --tier 6 --known <known.json> --patch
<snapshot.json>`, and `triage_state.py` reads again, by number, only:

- the issues and pull requests the change check read as updated since the cursor
- every issue whose `links` name one of those (the reverse index, built from `links`), so
  closing a blocker reads its dependents again and turns them from BLOCKED to UNBLOCKED
- every issue whose `due` has passed
- issues not in `triage`: a new one, or one the last read didn't reach

and keeps every other issue's reading from `triage`; an issue the change check read as closed
drops out. It reads every open issue, as today, when: `snapshot.json` has no `triage`, is
unreadable, or was read with other flags; `inputs` changed; or `reconciled` is 24 hours or more
ago.

**The reconciliation.** A full read with a `triage` to compare against compares each issue's
patched reading with the full one. A difference is a bug in the patching: the tick records
`"patch_drift": [<number>, ...]` in `tick.json` (spec 048) and prints `tier 6 patch drift:
#<N> <patched state> != <read state>` to stderr, one line each; the full read replaces `triage`
either way, and `reconciled` becomes the walk's start. The known gaps it covers: an event that
moves no `updated_at` (a reaction) and a link to an item in another repo.

Tiers other than 6 read as today: tiers 1 and 3 already cost no read beyond the change check
(S-046-6), and tier 4 reads only the labelled items.

### Docs

- `skills/shipmill-setup/SKILL.md`, The gate, and `docs/install.md`: the pre-check every
  `--check-every` minutes, the change check at most every `--every`, and that an existing job
  speeds up once `shipmill launchd` writes it again
- `skills/github-ship-watch/SKILL.md`: `--snapshot` and `--patch`, and `precheck.py`
- Specs 046 and 061, under S-046-1 and S-046-3: a line saying spec 103 runs a pre-check before
  the change check and reuses the hold read between change checks

## Acceptance criteria

Part 1, the pre-check:

- S-103-1: a tick whose pre-check reads every answer 304 (or a 200 with the kept digest), with no `pending`, no gate-side change due, and `checked` under 60 minutes ago makes no GraphQL request, no REST request but the pre-check's reads, and no `--refresh` fetch, and decides QUIET `no change since <cursor>; pre-check unchanged`
- S-103-2: each of a newer `updated_at` on the newest issue or pull request, a moved default head, a new latest release, a changed run in a watched workflow's newest 10, and a changed `total_count` or run in the repo's newest 10 Actions runs reads as a move, and a tick with that move and `checked` at least `--every` minutes ago runs the change check
- S-103-3: a 200 answer whose digest equals the kept one is no move, and a failed pre-check read is a move
- S-103-4: a move seen while `checked` is under `--every` minutes ago runs no change check, sets `pending`, and decides QUIET `change seen at <HH:MM>; the change check runs at <HH:MM> (--every <N>)`; the first tick at or after that time runs the change check though its own pre-check reads every answer 304
- S-103-5: with no `cursor.json`, a hand past `retry_hours` not yet idle, a dead last session, a sweep due, or a pull request queued for the land window, the change check is wanted without a pre-check move; with nothing wanted for 60 minutes since `checked`, a tick runs it anyway
- S-103-6: on a fake transport that counts GraphQL requests, 60 simulated minutes of ticks every 2 minutes with `--every 15` make no more GraphQL requests than the same 60 minutes of today's ticks every 15 minutes, under each of: nothing changes; one issue updated at minute 7; an issue updated every minute; and the change check runs at most once in any 15 minutes
- S-103-7: a tick that runs no change check reads no hold from GitHub and decides HELD from the hold `precheck.json` keeps when it names an open `shipmill-hold` issue; a tick that runs the change check reads the hold first and keeps it, and no LAUNCH follows a tick that read no hold
- S-103-8: a change check whose reads went through sets `checked` to the tick's start and clears `pending`; a failed read changes neither; a dry run writes no `precheck.json`; a deleted `precheck.json` makes the next tick run the change check
- S-103-9: `shipmill gate --every` and `shipmill launchd --every` refuse a value outside 5 to 1440; `shipmill launchd --check-every` refuses one outside 1 to `--every`; the job's `StartInterval` is `--check-every` times 60 and its gate arguments carry `--every <N>`; with neither flag the job runs every 2 minutes with `--every 15`
- S-103-10: `cli_fix` writes a job again with its `--every` and `--check-every`, and a job with no `--every` in its gate's arguments keeps its `StartInterval`
- S-103-11: `tick.json` and `shipmill gate --json` record `precheck` with the reads that moved, the requests made, how many answered 304, and when a pending change check runs; `--walk` and `--sweep` run the change check whatever `checked` says; a tick that runs no change check runs no `/usage` probe (spec 089) and no host pause check (spec 095)

Part 2, the session's snapshot:

- S-103-12: a walk that launches a session writes `snapshot.json` with `at`, `flags`, `precheck`, `tiers`, and `rows`, the rows exactly those the walk's tiers printed and the sweep's, before the session starts; a dry run writes none
- S-103-13: a launched session's prompt names `watch_state.py --snapshot <the snapshot's absolute path>` and no longer says "Rerun watch_state.py for the details"
- S-103-14: `watch_state.py --json --snapshot` with a snapshot under 15 minutes old, the same flags, and every pre-check digest unchanged prints the snapshot's rows, which equal what `watch_state.py --json` restricted to the same tiers and sections prints on the same fake forge, and makes no GraphQL request and no REST request but the pre-check's
- S-103-15: `watch_state.py --snapshot` with a missing file, a file that isn't the JSON the gate writes, a snapshot 15 minutes old or more, other flags, or one pre-check digest moved prints the rows a run without `--snapshot` prints and one stderr line `snapshot not used: <why>`, and exits as that run does
- S-103-16: `pr_gate.py`, `triage_state.py`, and the skills' other state scripts take no `--snapshot`, so a read before a write is always fresh

Part 3, the patched tier 6 read:

- S-103-17: a walk after one issue was updated, with a `triage` read in full under 24 hours ago and unchanged `inputs`, makes `triage_state.py` read that issue and the issues whose `links` name it and no other, and the tier 6 rows it prints equal a full read's on the same fake forge
- S-103-18: closing an issue that another names in a `Depends on` line turns the other's reading from BLOCKED to UNBLOCKED in the patched read
- S-103-19: an issue whose `due` has passed is read again though nothing updated it, and a row that fell due by the clock alone reads the same patched as fresh
- S-103-20: no `triage`, one read with other flags, changed `inputs`, or `reconciled` 24 hours or more ago makes tier 6 read every open issue
- S-103-21: a full read whose reading of an issue differs from the patched one records `patch_drift` with that issue's number in `tick.json`, prints `tier 6 patch drift: #<N> <patched> != <read>` to stderr, and replaces `triage` with the full read
- S-103-22: `skills/shipmill-setup/SKILL.md`, `docs/install.md`, `skills/github-ship-watch/SKILL.md`, `skills/github-issue-triage/SKILL.md`, `skills/github-pr-triage/SKILL.md`, and specs 046 and 061 say what the Behaviour's Docs list and The read say

## Out of scope

- Webhooks instead of polling: they need a public receiver, a host decision per maintainer
  (#1518's later step, spec 046's Out of scope)
- `pr_gate.py` sharing the gate's read: it reads before a land, a write, so it stays fresh; the
  session's share of time in it is measured, not cut, here
- `fleet.py overview` taking a repo's snapshot: a side reader (#1515), cheap enough today
- One pre-check or change check for every gate on a host: shipmill/shipmill#1519
- A tick staying QUIET when every change is the App's own write: shipmill/shipmill#1517
- Patching tiers other than 6, and the rows of items in other repos: the daily full read covers
  the latter
- Measuring the share of a session's time in `watch_state.py` and `pr_gate.py` before and after
  (#1626's third success line): a measurement, run as #842 did once the build ships, not a
  criterion a test can check
- Rewriting existing launchd jobs to the shorter interval without the maintainer running
  `shipmill launchd` (Decisions for you)

## Decisions relied on

- D-14: the pre-check and the snapshot only read; sessions still write as the App alone
- D-15: a hold starts nothing; a launch follows only a change check, which reads the hold first
- D-16: snapshot rows are used only with the flags they were read with, and the prompt still
  names digits the gate parsed
- D-56: a tick that decides from the pre-check still prunes when one is due
- D-58: the change check is unchanged and runs after the hold check; this spec puts a pre-check
  before both and reuses the hold read between change checks (Decisions for you names the
  departure)
- D-87: hands, idle subjects, and their `updatedAt` reads are unchanged; a hand past
  `retry_hours` not yet idle is a gate-side change, as today

## Issues

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
