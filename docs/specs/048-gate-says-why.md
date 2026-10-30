# S-048: The gate says why it isn't working: a failing tick names its cause, RUNNING and QUIET say what they wait on

status: built
serves: G-1

## Problem

A gate on launchd is unattended: the maintainer learns it stopped working only by asking,
and today the answer has to be dug out of the launchd log (shipmill/shipmill#774). On the
default branch (`src/shipmill/gate.py`):

- **Only Claude Code is preflighted before a launch.** The #500 preflight runs when the
  decision is LAUNCH, which is right: a QUIET tick needs no credentials. Whether the App can
  mint a token that reads the repo is never asked before a session starts, and the App check
  before the state read (spec 004) fails as a bare `shipmill: <error>` with exit 2, not as a
  named decision with its fix
- **A failing tick doesn't say why where status reads it.** A `ReleaseError` ends the tick
  with exit 2 and a line in the launchd log; launchd starts it again 15 minutes later and it
  fails the same way. `shipmill status` and `shipmill factory` report `failed: exit 2` and the
  log's last line, with no "since when" and only `tail -n 50 <log>` as the fix. A login
  `CLAUDE_AUTH` exits 0, so launchd's record shows nothing wrong at all
- **RUNNING doesn't say why.** `still_working` reads RUNNING while the session's pid runs
  with its recorded start time. It never looks at how long the session has run or whether
  its log still grows, so a hung session (a stuck tool call, a wait nobody answers) holds the
  repo indefinitely and every tick prints the same line. `gate.json` records the item's
  fingerprint, not the item, so the line can't even name what the session works on
- **QUIET doesn't say whether work is in flight.** `QUIET: no change since …` reads the same
  when the gate waits on CI for its open pull requests and when nothing has moved for a day

The maintainer asks for the status (an agent runs `shipmill status`) and should get the
answer there. The gate notifies no one for now.

## Behaviour

This spec extends spec 005 (headless sessions and their log), spec 009 and spec 044 (the
gate line, now in `shipmill factory`), spec 035 (the Claude Code preflight and its exit
code), and spec 046 (the change check and the QUIET line). Every tick keeps spec 046's
order: hold, busy, still working, the change check, the walk, the decision, then the prune
(D-56).

### The GitHub preflight: GITHUB_AUTH

A new decision, `GITHUB_AUTH` (`src/shipmill/gate.py`, `Action`), sits beside
`CLAUDE_AUTH`: the gate can't reach the repo as the identity its sessions write as, so no
session starts. It starts none and stops none.

- **On a LAUNCH**, in either mode and dry run or not, right after the Claude Code preflight
  passes, the gate checks the credential the session will write with. With `[agents] app_id`
  set: it mints an installation token for the repo (`src/shipmill/app.py`, `mint`, the
  session's permission table) and reads `GET /repos/<repo>` with it. The token is never
  printed or cached: the preflight calls `mint`, not `app_token`, so a dry run writes
  nothing. With no `app_id`: it reads `gh api repos/<repo>` as the host's gh login. Any
  failure is GITHUB_AUTH
- **The App check before the state read** (spec 004's At launch steps, `app_check`), which
  runs on every tick that reads the state because the state read passes the bot login
  (D-21), reads GITHUB_AUTH too when it fails, with the same reasons and fixes, instead of
  ending the tick on a bare error. It still runs before the state read, so a failure reads
  no state (D-14)
- **A tick that launches nothing checks nothing more**: no Claude Code preflight, no mint, no
  repo read. QUIET, UNCHANGED, RUNNING, STALLED, WAITING, and HELD ticks run neither
  preflight

The reason names what failed, and the line ends `; fix: <fix>`:

| What failed | The reason names | The fix |
|---|---|---|
| The App's key is missing or unreadable | the key's path | the key check's own fix today (`chmod 600 <path>`, or `shipmill app-create`) |
| GitHub refuses the JWT (401) | the App id and GitHub's message | the host's clock (`sntp -sS time.apple.com`), or the key for that App id |
| The App has no installation on the repo, or it was suspended | the repo | `shipmill app-install <repo>` |
| The installation lacks a permission the session table asks for | each permission | the installation's settings URL, to accept them |
| Minting the token is refused | GitHub's status and message | `shipmill app-install <repo>` |
| The token, or the host's gh login, can't read the repo | the status and the identity | `shipmill app-install <repo>` with an App; `gh auth login` without one |

A GITHUB_AUTH tick writes no `cursor.json` or `handed.json`, as a CLAUDE_AUTH tick doesn't,
so the next tick walks again (S-046-11).

### A failing tick exits 2 and leaves its cause in tick.json

A **failing tick** is one whose decision is `CLAUDE_AUTH` (a login failure as well as a
token file's, spec 035), `GITHUB_AUTH`, or `HOOKS_FAILED`, or one that a `ReleaseError` ends.
It exits 2 (`src/shipmill/cli.py`, `_gate_exit`), the exit code a token file's CLAUDE_AUTH
and any `ReleaseError` have today (Q-1). `PYPI_WAIT` clears itself once PyPI serves the
version and keeps exit 0; every other decision exits 0.

Every real tick (never a dry run) writes `tick.json` in the gate's state directory, next to
`gate.json`, once its decision is made or its error raised, before the prune:

```json
{"at": "<the tick's start>", "action": "<the decision, or ERROR>", "reason": "<the decision's reason, or the error's first line>",
 "fix": "<the fix, or null>", "failing": {"since": "<the first failing tick of this run>", "count": 3} | null,
 "running": {...} | null, "in_flight": {...} | null}
```

- `failing` is set on a failing tick: `since` is the first tick of the run of failing ticks
  this one belongs to, kept from the `tick.json` before it, and `count` how many in a row. A
  tick that doesn't fail writes `failing: null`, which ends the run
- `fix` is the decision's fix for CLAUDE_AUTH, GITHUB_AUTH, and HOOKS_FAILED. A
  `ReleaseError` carries an optional fix (`src/shipmill/errors.py`): the errors the tick's
  path raises with a fix in their text today (a malformed state file, a checkout on a
  branch, a checkout whose origin is another repo, `gh` not on `PATH`, an `--app-key`
  without `app_id`) set it, and `tick.json` records it. An error without one records the
  fix `shipmill gate --dry-run` in the checkout, which runs the same tick and prints the
  same error, so the maintainer can see whether it holds
- An exception that isn't a `ReleaseError` is a bug in shipmill: it is not caught, writes no
  `tick.json`, and status reads its traceback's last line from the log as today (S-009-3)
- `tick.json` is written once per tick, whole (a temporary file renamed), so a reader never
  sees half of one

### shipmill factory and shipmill status read tick.json

`shipmill factory`'s gate check (`src/shipmill/factory.py`, `gate_check` in
`src/shipmill/status.py`) reads `tick.json` beside the launchd job:

- **Failing**: the gate line's problem is `failing since <since> (<count> ticks): <action>:
  <reason>` and its fix is the record's. It takes the place of the job's `failed: exit 2`
  and `failed: <last line>` problems for the same tick, so one cause is shown once. A
  `tick.json` older than the launchd log's last decision or failure line is stale (a tick
  ran with a shipmill that writes none) and the log reads as today
- **RUNNING**: `running: <item>, <ran for>, log grew <ago>` (headless) or `running: <item>,
  <ran for>` (interactive), no problem
- **STALLED**: the stalled line below, a problem with its fix
- **QUIET**: `quiet: <the in-flight summary>`, no problem: the gate's own in-flight line
  (`InFlight.line`), its `ago` parts aged to the time `shipmill factory` runs, as RUNNING's are

The verdict (S-009-3, S-009-5, S-044-3) is unchanged for what spec 009 already names:
CLAUDE_AUTH and HOOKS_FAILED wait on the maintainer, a failed tick is STUCK. GITHUB_AUTH
waits on the maintainer like CLAUDE_AUTH, and STALLED is STUCK. `shipmill status` shows it
on its one `factory` line as the first problem with `shipmill factory` after it (S-044-2),
and reads nothing new (D-55): the record is the host's, read through the factory checks.
`shipmill factory --json` carries it in the gate check's value and fixes, in spec 044's
shape.

### RUNNING names the session's item, how long it ran, and when its log last grew

`gate.json` records the launch's item, its `brief()` line (`PRS_OPEN #12`, `NEW #774`),
beside its fingerprint; one written before this spec reads `item not recorded`.

- A headless RUNNING (`still_working`) reads `session <id> on <item>, running <N> min, log
  grew <M> min ago: tail -f <log>`
- An interactive RUNNING (`busy`) for the gate's last launch reads `session <id> on <item>,
  running <N> min: claude attach <id>`; a session the gate didn't launch keeps today's line
- `shipmill gate --json` adds `"running": {"session", "item", "minutes", "log_grew"}`
  (`log_grew` the minutes since the log's last write, null for an interactive session), and
  null on any other decision

A headless session's log must grow while it works, and `claude -p`'s default text output
writes only at the end. The gate starts headless sessions with `--output-format stream-json
--verbose` (`ClaudeCli.start`), so each message the session sends or receives is a line of
the log. `ended_dead` and `Dead.last_line` read the log as stream-json: a session ended with
a result when its log holds a `result` event whose `is_error` is false, and the line shown is
that event's `result` text, cut as `last_line` cuts it; the authentication failure check
reads only the tail's lines that aren't events (Claude Code's own stderr) and its `result`
events' text, so a tool's result that quotes the message, such as a read of
`src/shipmill/gate.py`, is no authentication failure (#822). A log written before this
spec, not stream-json, is read as today.

### STALLED: a headless session past its limit with a silent log

A new `[agents]` key, `stall_minutes` (`src/shipmill/agents.py`), an integer from 0 to 1440,
defaults to 30; 0 never reads a session as stalled.

After the busy step, a headless last launch whose process still runs (D-17) and whose log's
last write is `stall_minutes` or more ago is stalled. The tick decides `STALLED` and:

- reads the process's start time again and, when it still matches `gate.json`, stops the
  session: `SIGTERM` to its process group (the detached session's own, `start_new_session`)
- starts no session on that tick and writes no `cursor.json`; the item stays handed in
  `handed.json`, so it is retried after `retry_hours`, like an item a session worked on and
  left (S-046-13), never at once
- reads `STALLED: session <id> on <item>, running <N> min, its log silent for <M> min;
  stopped it; fix: tail -n 20 <log>`. A dry run stops nothing and says `would stop it`
- exits 0: the gate cleared it, and the next tick walks on

The stopped session is not a dead one (`ended_dead` reads it as one that ran: it ran longer
than `DEAD_WITHIN`), so `DEAD_STREAK` doesn't count it. An interactive session leaves no log
the gate writes, so it is never STALLED: its RUNNING line names how long it ran, and the
maintainer attaches to it.

### QUIET says what is in flight

The change check's one GraphQL query (`src/shipmill/walk.py`, S-046-3) also reads the
default branch's last 10 commits with the merged pull request each is associated with (its
number and `mergedAt`). That field is not in the signature: it moves only with the default
head, which already is.

Both QUIET lines, `no change since <cursor>` and `nothing needs an agent; read tiers …`, end
with what is in flight, from the change check's data and the state directory, with no other
read (S-046-1):

- **Open pull requests**: the non-draft ones whose head is in the repo, in three groups by
  their head's check rollup: `<N> wait on CI (#a, #b)` (pending, expected, or none yet),
  `<N> wait to land (#c)` (success), `<N> fail CI (#d)` (failure or error); a group with
  none is left out, and with no such pull request the part reads `no open pull request`
- **The last landed pull request**: `last landed #<N> <ago>`, the newest `mergedAt` among
  the 10 commits, or `no landed pull request in the last 10 commits`
- **The last session that ended with a result**: `last result: session <id> on <item>, ended
  <ago>`, from `last-result.json` in the state directory, or `no session has ended with a
  result yet`. The first tick that finds the last launch ended and not dead (a headless log
  with a successful `result` event, or an interactive session `claude agents` lists done
  outside `DEAD_WITHIN`) writes `{"session", "item", "at"}`, `at` the log's last write, or
  the tick's time for an interactive one

The line reads, for example, `QUIET: no change since 2026-10-28T09:15; in flight: 2 wait on
CI (#771, #773), 1 waits to land (#772); last landed #770 3 h ago; last result: session 5f…
on PRS_OPEN #770, ended 3 h ago`. `shipmill gate --json` adds `"in_flight": {"ci": [...],
"landing": [...], "failing": [...], "landed": {"number", "at"} | null, "result": {"session",
"item", "at"} | null}` on QUIET, null on any other decision. `tick.json` carries the same.

### Docs

- `skills/shipmill-setup/SKILL.md`, The gate: GITHUB_AUTH, a failing tick's exit 2 and
  `tick.json`, STALLED and `stall_minutes`, and what QUIET's in-flight part says
- `skills/github-ship-watch/SKILL.md`, where it reads the gate's line: the gate's own cause
  and fix are on `shipmill factory`'s gate line
- `docs/install.md`, where it lists the `[agents]` keys: `stall_minutes`
- Specs 005 (the headless log), 035 (the login CLAUDE_AUTH's exit code), and 046 (the QUIET
  line and the change check's query): a line saying spec 048 changed them

## Acceptance criteria

- S-048-1: a LAUNCH with `app_id` set, after the Claude Code preflight passes, mints an
  installation token for the repo and reads `GET /repos/<repo>` with it, in either mode and
  on a dry run too, and writes no token cache
- S-048-2: a LAUNCH without `app_id` reads `gh api repos/<repo>` as the host's login before
  any session starts
- S-048-3: a failed mint or repo read makes the tick `GITHUB_AUTH` with the reason and the fix
  the table gives for that failure, starting no session and stopping none
- S-048-4: a failed App check before the state read makes the tick `GITHUB_AUTH` with the
  table's reason and fix, and runs no `watch_state.py` and no change check
- S-048-5: a QUIET, UNCHANGED, RUNNING, STALLED, WAITING, or HELD tick runs no `claude auth
  status`, mints no token, and reads no `repos/<repo>`
- S-048-6: `shipmill gate` exits 2 on CLAUDE_AUTH (login or token file), GITHUB_AUTH, and
  HOOKS_FAILED, and when a `ReleaseError` ends the tick; it exits 0 on PYPI_WAIT, STALLED,
  and every other decision
- S-048-7: a real tick writes `tick.json` with `at`, `action`, `reason`, `fix`, and
  `failing`; a dry run writes none
- S-048-8: a failing tick after a failing tick keeps the first one's `since` and adds one to
  `count`; a tick that doesn't fail writes `failing` null
- S-048-9: a tick that a `ReleaseError` ends writes `tick.json` with action `ERROR`, the
  error's first line, and its fix, or `shipmill gate --dry-run` when it carries none, then
  exits 2
- S-048-10: a tick that an exception other than `ReleaseError` ends writes no `tick.json` and
  the exception propagates
- S-048-11: `shipmill factory`'s gate line reads `failing since <since> (<count> ticks):
  <action>: <reason>` with the record's fix from a failing `tick.json`, and no second
  `failed: exit 2` problem for the same tick
- S-048-12: a `tick.json` older than the launchd log's last decision or failure line is
  ignored, and the gate line reads the log as spec 009 does
- S-048-13: `shipmill status`'s factory line shows a failing tick's cause as its first
  problem, with the verdict waiting on the maintainer for CLAUDE_AUTH, GITHUB_AUTH, and
  HOOKS_FAILED, and STUCK for an error and for STALLED
- S-048-14: `gate.json` records the launch's item; one without it reads `item not recorded`
- S-048-15: a headless RUNNING line names the session, its item, the minutes it has run, and
  the minutes since its log last grew; an interactive RUNNING for the gate's last launch
  names the session, its item, and the minutes it has run
- S-048-16: `shipmill gate --json` prints `running` with session, item, minutes, and
  `log_grew` on RUNNING and STALLED, and null otherwise
- S-048-17: a headless session starts with `--output-format stream-json --verbose`, and
  `ended_dead` reads a stream-json log's `result` event: none, or one with `is_error` true,
  is no result; on a stream-json log the authentication failure check reads only the lines
  that aren't events and the `result` events' text
- S-048-18: `[agents] stall_minutes` defaults to 30, and the config refuses a value that is
  not an integer from 0 to 1440
- S-048-19: a headless session whose process runs and whose log's last write is
  `stall_minutes` or more ago makes the tick `STALLED`; with `stall_minutes = 0` it reads
  RUNNING
- S-048-20: a STALLED tick sends `SIGTERM` to the session's process group only when its start
  time still matches `gate.json`, starts no session, and leaves the item handed in
  `handed.json`; a dry run stops nothing and says `would stop it`
- S-048-21: the change check's GraphQL query reads the default branch's last 10 commits'
  merged pull requests, still in one query, and a change to them alone leaves the signature
  as it was
- S-048-22: both QUIET lines end with the open pull requests grouped as waiting on CI,
  waiting to land, and failing CI, the last landed pull request, and the last session that
  ended with a result, each with its stated wording when there is none
- S-048-23: a QUIET tick with no change runs no read beyond the change check to build its
  in-flight part
- S-048-24: the first tick that finds the last launch ended with a result writes
  `last-result.json` with session, item, and when it ended; a session that ended dead writes
  none
- S-048-25: `shipmill gate --json` prints `in_flight` with ci, landing, failing, landed, and
  result on QUIET, and null otherwise
- S-048-26: `shipmill factory`'s gate line reads `quiet: <the in-flight summary>` from a
  current QUIET `tick.json`, with no problem

## Out of scope

- A notification channel: a stuck gate is usually about the host (an expired login, a
  sleeping machine, an unloaded job), so the channel belongs to the host, set once, not to
  the repo. Until it exists the maintainer asks for the status. The desktop notifications the
  gate sends today (`[agents] notify`, the CLAUDE_AUTH episode) are unchanged
- A watcher outside the host that notices a gate that stopped ticking (the machine sleeps,
  the job was unloaded): it needs the gate to leave a trace on GitHub on quiet ticks, builds
  on this spec, and gets its own issue
- A STALLED reading for an interactive session: it has no log the gate writes, and a person
  can attach to it
- A verdict for "nothing is getting done": QUIET shows when the last pull request landed and
  the last session ended with a result, and no threshold turns an old one into a problem
- Catching exceptions other than `ReleaseError` to record them: a crash is a bug to fix, and
  its traceback stays in the launchd log

## Decisions relied on

- D-14: with `app_id` set a session starts as the App or not at all; a failure to set up the
  App's identity exits 2, never falling back to the host's gh login. GITHUB_AUTH is that
  failure named, and the preflight with an App never reads as the host's login
- D-15: a hold starts nothing, and a session waiting on the user is stopped after
  `max_wait_minutes`; STALLED stops a headless session that went silent the same way, for
  an unattended gate
- D-17: a headless session runs while its pid has its recorded start time; STALLED reads that
  and the log's last write, and a headless session still never reads as waiting
- D-21: the state read passes the App's bot login, which is why the App check runs on every
  tick that reads the state, before the change check
- D-55: `shipmill status` reports the pipeline with one `factory` line; the gate's cause,
  RUNNING, STALLED, and QUIET details are the host's, on `shipmill factory`'s gate line
- D-56: the prune runs after the tick's decision, whatever it is (GITHUB_AUTH and STALLED
  included), and never changes the tick's exit code; a tick that a `ReleaseError` ends
  before its decision prunes nothing
- D-58: a quiet tick reads nothing beyond the change check; the in-flight part and the last
  landed pull request come from that one query

## Issues

- shipmill/shipmill#813: S-048-1, S-048-2, S-048-3, S-048-4, S-048-5
- shipmill/shipmill#814: S-048-14, S-048-15, S-048-17
- shipmill/shipmill#815: S-048-16, S-048-18, S-048-19, S-048-20
- shipmill/shipmill#816: S-048-6, S-048-7, S-048-8, S-048-9, S-048-10
- shipmill/shipmill#817: S-048-11, S-048-12, S-048-13
- shipmill/shipmill#818: S-048-21, S-048-22, S-048-23, S-048-24, S-048-25
- shipmill/shipmill#828: S-048-26

## Verification

Checked on main plus #828's change on 2026-10-29: the code read at each named place, the
named tests run (all pass), and on this host `shipmill factory` and `shipmill gate --dry-run
--json` run against the gate's checkout while its headless session ran.

- S-048-1: read `gate.reached` (after `preflight`, before the dry-run return in `decided`) and `github_auth.app_reach` (`app.mint` with the session's `PERMISSIONS`, then `GET /repos/<repo>`, no `app_token`, no cache), wired in `cli.py`'s gate; `test_s048_1_*` in `tests/test_gate_github_auth.py`; holds
- S-048-2: read `github_auth.host_reach` (`gh api repos/<repo>` when the identity is None); `test_s048_2_*`; holds
- S-048-3: read `GitHubAuth.of`/`app_failed`, `app.py`'s `KeyRefused`, `JwtRefused` (the `sntp` fix), `NotInstalled`, `Lacks` (the settings URL), `MintRefused`, and `app_reach`/`host_reach`'s read failures; `reached` sets `stop=()` and starts nothing; `test_s048_3_*`; holds
- S-048-4: read `decided`: `as_app`'s `ReleaseError` becomes GITHUB_AUTH and returns before `findings(read)`, so no `watch_state.py` and no change check; `test_s048_4_*`; holds
- S-048-5: read `preflight` and `reached`, both only on LAUNCH, and `app.app_check`, which mints nothing; `shipmill gate --dry-run --json` on a RUNNING tick printed `"preflight": null`; `test_s048_5_*`; holds
- S-048-6: read `cli._gate_exit` (2 for `gate.FAILING`: CLAUDE_AUTH, GITHUB_AUTH, HOOKS_FAILED) and the `ReleaseError` exit 2 in `run`; `test_s048_6_*` in `tests/test_gate_tick.py`; holds
- S-048-7: read `gate` (`record_tick` only when not a dry run) and `TickRecord.record`; the host's `tick.json` holds all seven keys, and a dry run left its `at` unchanged; `test_s048_7_*`; holds
- S-048-8: read `record_tick` (keeps `since`, `count + 1`, null on a tick that doesn't fail); `test_s048_8_*`; holds
- S-048-9: read the `except ReleaseError` in `gate` (`ERROR`, `error_line`, `exc.fix or DRY_RUN_FIX`, re-raised) and the fixes `walk.malformed`, `check_checkout`, the branch check, `host_login`'s gh-missing, and the `--app-key` error carry; `test_s048_9_*`; holds
- S-048-10: read `gate`: only `ReleaseError` is caught; `test_s048_10_*`; holds
- S-048-11: read `status.tick_problem` and `job_problems` (exit 2 dropped for a failing record); `test_s048_11_*` in `tests/test_gate_tick_report.py`; holds
- S-048-12: read `status.current_tick` (the log's last line must be the record's own); `test_s048_12_*`; holds
- S-048-13: read `tick_problem` (`TICK_WAITS` waits, ERROR and STALLED STUCK) and `job_problems` (its problem first); `test_s048_13_*`; holds
- S-048-14: read `save_launch`/`load_launch` (`item` beside the fingerprint, absent reads `item not recorded` through `Launch.named`); the host's `tick.json` names the running launch's item, `ISSUES UNBLOCKED shipmill/shipmill`; `test_s048_14_*` in `tests/test_gate_running.py`; holds
- S-048-15: read `still_working` and `busy`; `shipmill gate --dry-run --json` printed `session 510becb1-… on ISSUES UNBLOCKED shipmill/shipmill, running 51 min, log grew 0 min ago: tail -f …`; `test_s048_15_*`; holds
- S-048-16: read `tick_record` (`running`, set only on RUNNING and STALLED decisions); the dry run printed `running` with session, item, minutes, and log_grew; `test_s048_16_*` in `tests/test_gate_stalled.py`; holds
- S-048-17: read `ClaudeCli.start` (`--output-format stream-json --verbose`), `has_result` and `ended_dead`; `test_s048_17_*`; holds
- S-048-18: read `agents.py` (`stall_minutes` default 30, `table.integer` 0 to 1440); `test_s048_18_*` in `tests/test_config.py`; holds
- S-048-19: read `still_working` (STALLED when the log's silence reaches a limit above 0); `test_s048_19_*`; holds
- S-048-20: read `stalled` (start time read again before `stop_group`'s SIGTERM to the group, `would stop it` on a dry run) and `decided` (returns before the walk, so no `cursor.json` or `handed.json`); `test_s048_20_*`; holds
- S-048-21: read `walk.py`'s query (`history(first: 10)` with `associatedPullRequests { number mergedAt }`, one query) and `changes_of` (history kept out of `signed`); `test_s048_21_*` in `tests/test_gate_in_flight.py`; holds
- S-048-22: read `InFlight.line` and `walk.flight_of`, appended to both QUIET lines in `decided`; `test_s048_22_*`; holds
- S-048-23: read `decided` (`InFlight.of` from the change check's `flight` and `last-result.json` alone); `test_s048_23_*`; holds
- S-048-24: read `decided` (`ended_with_result` only when not dead and for a new session, written on a real tick); `test_s048_24_*`; holds
- S-048-25: read `tick_record` (`in_flight` only on QUIET) and `InFlight.record`; the dry run on a RUNNING tick printed `"in_flight": null`; `test_s048_25_*`; holds
- S-048-26: read `status.tick_problem` (a current QUIET record with `in_flight` shows `quiet: ` and `InFlight.line(now)`, no verdict, no fix); `test_s048_26_a_quiet_tick_reads_its_in_flight_summary_and_is_no_problem`; holds
