# S-093: A gate's ticks read GitHub as the App, not on the maintainer's budget

status: approved
serves: G-1

## Problem

A gate's own reads spend the maintainer's GitHub budget. The tick's hold check, its change
check, and its walk (`src/shipmill/gate.py`'s `WatchState`, `run_command`, and `run_state`)
run `gh` in the gate's own environment, so they read as the user the gate runs as; only the
sessions the gate starts get the App's token (`session_env`). Spec 004 chose this when the
gate's reads were few ("Only sessions change identity", S-004-12). Every gate on a host now
draws on one personal budget of 5,000 GraphQL points an hour, shared with the maintainer's own
`gh`, every interactive session, and any fleet report:

- On one host with 24 gates the ticks spent about 430 points an hour (2026-11-22)
- On 2026-11-24 a fleet overview left 136 points, and the next reader failed on "API rate
  limit already exceeded"; a gate tick in that window fails the same way, so a maintainer who
  exhausts their budget stalls every gate on the host

An App's installation token draws on the installation's own limit, which GitHub counts apart
from the user's. The App already mints read-only tokens (spec 065, D-84) and narrowed tokens
(D-90); the tick just doesn't use one (shipmill/shipmill#1516, accepted as an opportunity on
2026-11-25).

## Behaviour

With `[agents] app_id` set, every GitHub read a gate tick makes through `gh` runs with an App
installation token that can only read, the tick's read token, instead of the maintainer's
login. Without an App, or when the token can't be minted, the tick reads as today and says so.
What the tick decides, writes, and exits with is unchanged; only whose budget its reads draw
on changes.

### The reads that move

Each of these runs with `GH_TOKEN` set to the tick's read token in the environment of that
one command or subprocess, never in the gate's own process environment:

- The hold check (`Hold.read`, the open `shipmill-hold` issue)
- The change check (`WatchState.changes`: `walk.py`'s `check` GraphQL query, the per-workflow
  runs reads of D-58, and the land window's last held merge of spec 056)
- The issue subjects' `updatedAt` (`WatchState.issues`, spec 061) and the waits-on markers
  (`WatchState.waited`, spec 089)
- Each tier and the sweep (`watch_state.py --tier N` and `--sweep`), with every script those
  run in turn (`triage_state.py` and the rest), which inherit the subprocess's environment

The token is minted, or read from its cache, at the tick's first GitHub read, from
`[agents] app_id` and the key `shipmill gate` already uses (`--app-key`, else
`~/.config/shipmill/app-<app_id>.pem`).

### The reads that stay

- `gh api user` (`host_login`): an installation token can't read `/user`, and the login it
  reads is the maintainer's by definition (spec 005, spec 036)
- The GitHub preflight (spec 048's `reached`), the upgrade proposal (spec 047), and the
  permission notice (spec 060, D-86): each already reads or writes with its own token, as now
- Sessions: their `gh` and git helpers (spec 004) and their tokens are unchanged; the tick's
  read token never reaches a session

### The tick's read token

`src/shipmill/app.py` gains a table, `TICK_READ_PERMISSIONS`: `actions`, `checks`,
`contents`, `discussions`, `issues`, `pull_requests`, `statuses`, and `metadata`, each at
`read`, plus `deployments: read` where the installation grants it (D-77). Every entry is a
permission of the session's table at no more than its access (D-90's rule for a narrowed
token), so the App needs no new permission.

The token covers the gate's repo. In a repo whose `.github/shipmill.toml` has a `[product]`
table, it also covers the repos the watch reads there under the gate's repo's owner: in a
component, its `[product] home` and the repos the home's `[product] repos` lists, as D-84 names
them; in a home repo, its own `[product] repos`. A product that lists a repo of another owner
makes the tick read as the host (see Falling back). GitHub's answer must cover exactly the
asked repos and grant nothing beyond the table, as S-065-4 checks the read token; anything else
refuses the token.

It is cached in the gate's state directory as `app-token-tick.json` (mode `0600`), apart from
the session's `app-token.json`, the coordinator's, the component's read token, and every
narrowed token's file, and reused while the same App minted it, it covers the same repos, and
it has at least 10 minutes left (spec 004's rule). It is never written to the session's
helpers, a session's environment or `--settings`, a git credential, a process's arguments,
stdout, a log, or `tick.json`. A dry run mints the token when no cached one is reusable and
writes no cache file, as a dry run writes no bot ids (#1034).

### Falling back

The tick reads as the host, with the gate's environment as today, when:

- `[agents] app_id` is unset (including `[agents] identity = "host"` or `"none"`, spec 082)
- The product lists a repo of another owner than the gate's repo
- Minting the token fails with a shipmill error (the key missing or readable by others, the App
  not installed on a covered repo, a permission the installation hasn't granted, GitHub
  unreachable, an answer that refuses the token)

A failed mint never fails the tick and never changes its decision: reads write nothing, so
D-14's reason against a fallback (an agent's text reading as the maintainer's) doesn't apply to
them. A read that fails once the token is in use (a rate limit, a network error) fails the tick
as a host read's failure does today, ending it `ERROR` (spec 048); the tick doesn't retry it as
the host.

### What the tick records

`tick.json` (spec 048, `TickRecord`) and `shipmill gate --json` gain `reads_as`:

- `{"identity": "app", "why": null}` when the tick's reads went as the App
- `{"identity": "host", "why": "<reason>"}` when they went as the host: `no [agents] app_id`,
  `the product lists <owner/name> of another owner`, or the mint's error's first line
- `null` when the tick read nothing from GitHub (a `CLAUDE_AUTH` refusal before the hold check)

An `ERROR` tick records the `reads_as` of the reads it made before it failed, so a rate-limit
failure tells the App's limit from the maintainer's. A `tick.json` written before this spec,
without the key, still loads, as `reads_as` null.

The tick's text line ends `; reads as host: <why>` when `[agents] app_id` is set and the reads
fell back; it is unchanged when they went as the App or when no App is configured.

`docs/install.md`'s sentence "The gate's own reads still use your `gh` login" changes to say
that with an App the gate's reads go as the App with a read-only token, and without one as
your login. This spec replaces S-004-12 and spec 004's sentence "Only sessions change
identity": the tests of S-004-12 change to this spec's.

## Acceptance criteria

- S-093-1: with `[agents] app_id` set and the App's token minted, the hold check, the change check's GraphQL query and each per-workflow runs read, `WatchState.issues`, and `WatchState.waited` run with `GH_TOKEN` equal to the tick's read token in the environment passed to that command
- S-093-2: with `[agents] app_id` set and the token minted, each `watch_state.py --tier N` and `--sweep` subprocess gets `GH_TOKEN` equal to the tick's read token in its environment
- S-093-3: in every case `gh api user` (`host_login`) runs without the tick's read token in its environment, and after a tick the gate process's own `os.environ` holds no `GH_TOKEN` it didn't hold before
- S-093-4: the tick's read token is asked with exactly `TICK_READ_PERMISSIONS` at `read`, plus `deployments: read` only when the installation grants it; a GitHub answer that grants a permission beyond them, write or admin access, or a repo not asked refuses the token, which is never returned or cached
- S-093-5: in a repo without `[product]`, the token is asked for the gate's repo alone; in a component it is asked for the gate's repo, its `[product] home`, and the home's `[product] repos` of the same owner; in a home repo for the gate's repo and its `[product] repos`; a product listing a repo of another owner mints no token and the tick reads as the host with `why` naming that repo
- S-093-6: the token is cached in the state directory's `app-token-tick.json` with mode `0600` and reused while the same App minted it, it covers the same repos, and it has at least 10 minutes left, else minted again; it never appears in `app-token.json`, the session's helpers, a session's environment or `--settings`, a process's arguments, stdout, or `tick.json`
- S-093-7: a dry run with no reusable cached token mints one and writes no `app-token-tick.json`
- S-093-8: with `[agents] app_id` unset, the tick's reads run in the gate's environment with no `GH_TOKEN` added, and `tick.json`'s `reads_as` is `{"identity": "host", "why": "no [agents] app_id"}`
- S-093-9: with `[agents] app_id` set and the mint failing with a shipmill error, the tick reads as the host, its decision and exit code are those of the same tick reading as the host, `tick.json`'s `reads_as` is `{"identity": "host", "why": <the error's first line>}`, and its text line ends `; reads as host: <the error's first line>`
- S-093-10: with the token minted, `tick.json` and `shipmill gate --json` record `reads_as` as `{"identity": "app", "why": null}` and the text line carries no `reads as` part
- S-093-11: a read as the App that fails (such as GitHub's rate limit) ends the tick `ERROR` with exit 2 as a host read's failure does, `tick.json` records `reads_as` app, and the read is not run again as the host
- S-093-12: a tick that reads nothing from GitHub records `reads_as` null, and a `tick.json` without `reads_as` loads as null
- S-093-13: `docs/install.md` says the gate's own reads go as the App with a read-only token when `[agents] app_id` is set, and as the maintainer's `gh` login without one

## Out of scope

- `shipmill status`, `shipmill factory`, and `fleet.py`: they keep reading as the person who
  runs them; taking the same token there is a later request
- A gate session's reads: its helpers already read as the App (spec 004)
- shipmill/shipmill#1515, a gate session starting from the snapshot the gate read instead of
  reading the state again: it cuts a session's time and reads, a different outcome, with new
  state handed to the session (specs 046, 061)
- shipmill/shipmill#1517, a tick that stays QUIET when every change since the cursor is the
  App's own write on an item it handed: a new rule in the change check (spec 046) that cuts
  walks, not whose budget a walk spends
- shipmill/shipmill#1518, a free conditional REST pre-check so a gate notices a change within a
  minute or two: an outcome about latency, with new stored ETags and a shorter interval
- shipmill/shipmill#1519, one change check for every gate on a host: a host-level reader and a
  hand-off between gates; it reads with this spec's token once both are built
- Webhooks instead of polling (#1518's later step)

## Decisions relied on

- D-14
- D-54
- D-58
- D-77
- D-84
- D-90

## Issues

The build issues, filled in once they are filed: one `- owner/repo#N: S-093-1, S-093-2` per
line, naming the criteria that issue delivers. Each criterion belongs to exactly one.

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
