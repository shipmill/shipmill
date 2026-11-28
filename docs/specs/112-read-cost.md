# S-112: A goal report reads each closed week once, one at a time per host, and a person's read commands read as the App

status: approved
serves: G-1

## Problem

shipmill/shipmill#1516, accepted on 2026-11-25, has the Outcome "a gate's ticks don't spend
the maintainer's budget, and a maintainer who exhausts it doesn't stall the gates". Spec 093
moved a tick's reads to the App's read token. Two requests grouped into the opportunity since
show what is left:

- **The goal-report chain costs too much, all at once** (#1847). `watch_state.py --tier 4` and
  `--sweep` run `intake_state.py --plans --goals`, which runs `retro.py gather --goals`, which
  runs `metrics.py` once per week window: this week, the week before, each week of a met
  streak, with per-PR queries. A closed week's numbers don't change, yet every run reads them
  again, because each window ends at a moment that moves with `now`. Nothing stops several
  gates and the maintainer's commands from running the chain at once; with `sweep_hours = 6`
  all 25 gates of one host swept within 16 minutes on 2026-11-28; and a failed sweep writes no
  `sweep.json`, so it runs again on every tick (one gate re-ran it for 15 hours). The token was
  refused twice in a day with `API rate limit already exceeded`. Moving the reads to the App
  moves the budget, not the cost: the installation has per-minute limits too
- **A person's session reads as the maintainer** (#1849). `shipmill status` (with `--item` and
  `--summary`), `shipmill queue`, and the `status --item` that `decision answer` runs read with
  plain `gh`, and so do the state scripts a session runs by hand. On 2026-11-28 one session's
  check ran two goal-report chains on the maintainer's token beside 25 gates. The maintainer
  asked for shipmill commands for these reports rather than a generic script runner, so the
  scripts stay the skills' internals

## Behaviour

Nothing here changes what a report says or what a tick decides, save that the retro's weeks
start at a UTC midnight. It changes how often the goal report's weeks are read, how many such
reads run at once on a host, when a gate sweeps, and whose budget a person's read commands
draw on.

### The retro's weeks start at a UTC midnight

`retro.py gather` (`skills/github-ship-watch/scripts/retro.py`) reads its metrics windows of
`--days` N days aligned to the UTC day. With D the UTC midnight that starts today:

- **The open window** runs from D less N days to now: N days and the hours since midnight
- **Each earlier window** (the week before, and each earlier week `met_streaks` asks for) is the
  N days before the start of the window after it, so it starts and ends at a UTC midnight

`metrics.py` (`skills/github-ship-watch/scripts/metrics.py`) gains `--since TIME`, the window's
start, read as `--until` reads a time; with it the window runs from `--since` to `--until`.
`--since` with `--days`, or a `--since` not before the window's end, exits 2. gather passes
`--since` and `--until` for every window. Its JSON's `window` keeps its keys; `start` is now a
midnight. Spec 027's "the retro's week" is this window.

### A closed window is read once

A window is **closed** when its end is at least an hour before now: a margin for events GitHub
indexes late, as `CURSOR_OVERLAP` is the change check's. gather keeps the `metrics.py` report
of each closed window in the checkout's state folder, the one the gate keeps `sweep.json` in:
`<git rev-parse --git-common-dir of --checkout>/shipmill/metrics/<key>.json`, where `<key>` is
the SHA-256 of a canonical JSON of the repo (lowercased), the window's start and end, the
`metrics.py` arguments other than `--json`, `--since`, and `--until`, sorted, and the SHA-256 of
`metrics.py`'s own content. The file holds `{"key": {...}, "report": <metrics.py's JSON>}`.

- A closed window whose file exists is read from it, with no `metrics.py` run
- A closed window with no file runs `metrics.py` and writes the file (atomically, by rename)
- The open window, and a window that ended less than an hour ago, always runs `metrics.py` and
  is never written
- A file that isn't that JSON object, or whose `key` doesn't hash to its name, exits 2 naming
  the file, as any malformed read does
- Each run deletes the files of windows that ended more than 60 days before now
- With `--checkout` outside a git checkout, gather keeps no cache and runs `metrics.py` for every
  window, as today

A changed `metrics.py`, a different `--bot` or `--environment`, or another repo reads anew. A
closed window's report is frozen once written: a label added later to an issue of that week, or
a late edit, isn't seen there. The files are a cache of GitHub's answers: deleted, the next run
reads GitHub again and misses nothing (N-2). A gate's dry run may write them too, as they hold
nothing the gate decides from.

### One report at a time on a host

`retro.py gather` holds the host's report lock while it runs: an exclusive `flock` on
`$XDG_CACHE_HOME/shipmill/locks/report.lock`, else `~/.cache/shipmill/locks/report.lock`, beside
`suite_lock.py`'s `suite-locks`. The lock file holds the holder's repo and pid, as
`suite_lock.py`'s does; the lock frees when the holder's process exits, killed or not, and leaves
no state behind. A second gather on the host, from a gate or a person's command, waits for it;
after 10 minutes waiting it exits 2 with `another report holds this host's lock: <repo> (pid
<pid>) for <minutes> min`. A gate's tier or sweep that fails this way fails as any failed read
does (S-046-11), and a failed sweep backs off (below).

### A refused read waits on GitHub's secondary limit

A `gh` read of `metrics.py` or `retro.py` that GitHub refuses with its secondary-limit wording
(`secondary rate limit`, in any case, on gh's stderr) waits and tries again: 60 seconds, then
120, then 240, one stderr line per wait, `GitHub's secondary rate limit: waiting <n> s
(<k> of 3)`. A fourth refusal fails as a failed read does today. A refusal with the primary
limit's wording (`API rate limit exceeded` or `API rate limit already exceeded`) isn't retried:
it fails at once, as today, and a session it ends keeps D-112's host pause. The two are told
apart by GitHub's wording alone, never by `gh api rate_limit` before or after: GitHub answers one
token from two counters with their own resets (#1847's correction), so `remaining` can't tell
which one refused.

### Sweeps spread over the period

A gate's sweep (`src/shipmill/walk.py`, `Swept.due`) is due at its repo's phase points, not
`sweep_hours` after the last sweep. The repo's offset is the first 8 hex digits of the SHA-256 of
`owner/name`, lowercased, read as an integer, modulo `sweep_hours` times 3,600 seconds; its
phase points are the Unix epoch plus the offset plus each multiple of `sweep_hours`. A sweep is
due when there is no `sweep.json`, or the latest phase point at or before now is later than
`sweep.json`'s `at`. Gates on one host sweep at times set by their repos' names, whenever they
were started; a repo still sweeps once per `sweep_hours`. The first sweep after the upgrade may
come sooner than `sweep_hours` after the last one, once.

### A failed sweep backs off

A sweep that fails writes `sweep-failed.json` in the state folder, `{"at": <when it started>,
"count": <failed sweeps in a row>, "error": <its error's first line>}`, and leaves `sweep.json`
as it was, so tiers 2, 5, and 7 keep reading the last good sweep's rows. While the file exists, a
sweep is due only when the phase rule says so and now is at least `at` plus the wait for
`count`: none after the first failure (the next tick tries again), 30 minutes after the second,
then twice the last wait, at most `sweep_hours`. A sweep that succeeds deletes the file. A dry
run writes and deletes neither, and `shipmill gate --sweep` sweeps whatever the file says.

A tick that skips a due sweep for the back-off ends its text line `; sweep backs off until
<HH:MM> UTC after <count> failures`, and `shipmill gate --json`'s `walk` gains `"sweep_backoff":
{"until": <time>, "count": <n>} | null`.

### A person's read commands read as the App

With `[agents] app_id` set, `shipmill status` (every form: the report, `--item`, `--summary`),
`shipmill queue` without `--fleet`, and the two commands below read GitHub as the App: every
`gh` read they run, and every `watch_state.py` or other script they run as a subprocess, get
`GH_TOKEN` set to a read token in that one command's environment, never in the shipmill
process's own `os.environ`. `decision answer`'s read after its move is the `status --item` it
runs (`src/shipmill/cli.py`), so it reads as the App too; its move writes as today, through
`shipmill gh` (D-54).

The read token is spec 093's: `TICK_READ_PERMISSIONS` at `read`, over the repos `tick_repos`
names for the checkout's config (`src/shipmill/tick_read.py`, `src/shipmill/app.py`), minted
with the key D-54 names (a leading `--app-key`, else `SHIPMILL_APP_KEY`, else
`~/.config/shipmill/app-<app_id>.pem`), cached in the checkout's state folder as
`app-token-tick.json` with S-093-6's reuse rule, and shared with a gate of the same checkout. It
never reaches stdout, a process's arguments, a log, or any process but the read commands' own
reads. `gh api user` (`host_login`) stays the person's login.

The command prints one line on stderr, so its stdout, JSON included, is unchanged:

- `reads as app <app_id>` when its reads went as the App
- `reads as host: <why>` when `[agents] app_id` is set and they fell back: a product repo of
  another owner, or the mint's error's first line (no key on this host, the App not installed),
  as S-093-9 words a tick's
- nothing when no `[agents] app_id` is set

A failed mint never fails the command and never changes its output or exit code: reads write
nothing. A read that fails once the token is in use fails as a host read's failure does, and
isn't run again as the host (S-093-11).

### Two read commands for the goal report and the plans

The reports a person's session or a `## Check` block needs get shipmill commands, so they name
no script path and read as the App as above:

- `shipmill goals report <owner/repo> [--checkout DIR] [--bot LOGIN]...` runs the wheel's
  `retro.py gather <owner/repo> --goals --checkout DIR --json` (DIR defaults to `.`), passing
  each `--bot`: spec 027's report
- `shipmill product plans <owner/repo> [--checkout DIR] [--bot-login LOGIN] [--wip N]` runs
  the wheel's `intake_state.py <owner/repo> --plans --goals --json` in DIR, passing the flags
  given: the plan and goal rows (spec 028, spec 106), which print the goal report they read
  (#1842)

Each prints its script's stdout unchanged and exits with its exit code. Both run the scripts
shipped in the wheel (`shipmill`'s own `skills/`), so the release the CLI pins is the release the
scripts are.

### Docs

- `docs/install.md`'s App section: with an App, `shipmill status`, `shipmill queue`, `shipmill
  goals report`, and `shipmill product plans` read as the App with a read-only token, and say so
  on stderr
- `skills/product-intake/SKILL.md`, PROJECT_START_DUE: a check issue's `## Check` that needs
  spec 027's report or the plan rows names `shipmill goals report` or `shipmill product plans`,
  through the pinned `uvx`, never a script path
- Spec 046, under S-046-8: a line saying spec 112 changed when a sweep is due
- Spec 027, under S-027-9: a line saying spec 112 aligned the weeks to the UTC day

## Acceptance criteria

- S-112-1: `retro.py gather --days N` runs its open window from the UTC midnight N days before today's to now, and each earlier window over the N days before the next one's start, so every earlier window starts and ends at a UTC midnight
- S-112-2: `metrics.py --since T1 --until T2` measures the window from T1 to T2; `--since` with `--days`, or a `--since` not before the window's end, exits 2
- S-112-3: a closed window (ended at least an hour ago) with no cache file runs `metrics.py` once and writes `<git-common-dir>/shipmill/metrics/<key>.json`; a second gather reads it and runs no `metrics.py` for that window
- S-112-4: the cache key changes, and the window is read again, when the repo, the window's bounds, any `metrics.py` argument but `--json`, `--since`, and `--until`, or `metrics.py`'s content changes
- S-112-5: the open window and a window that ended less than an hour ago always run `metrics.py` and are never written to the cache
- S-112-6: a cache file that isn't the JSON object gather writes, or whose `key` doesn't hash to its name, exits 2 naming the file
- S-112-7: a gather deletes the cache files of windows that ended more than 60 days ago, and with `--checkout` outside a git checkout writes no cache and runs `metrics.py` for every window
- S-112-8: while one `retro.py gather` runs, a second on the same host waits on `report.lock` and runs once the first exits; after 10 minutes waiting it exits 2 naming the holder's repo and pid
- S-112-9: a holder killed while it holds `report.lock` frees it for the next gather at once
- S-112-10: a `metrics.py` or `retro.py` read refused with `secondary rate limit` waits 60, 120, and 240 seconds, printing one stderr line per wait, and a fourth refusal fails as a failed read does
- S-112-11: a read refused with `API rate limit exceeded` or `API rate limit already exceeded` is not retried
- S-112-12: a sweep is due with no `sweep.json`, or when the repo's latest phase point at or before now (epoch plus `int(sha256(owner/name lowercased)[:8], 16) mod (sweep_hours * 3600)` seconds plus a multiple of `sweep_hours`) is later than `sweep.json`'s `at`, and not otherwise
- S-112-13: a failed sweep writes `sweep-failed.json` with `at`, `count`, and `error`, counting failures in a row, and leaves `sweep.json` unchanged
- S-112-14: with `sweep-failed.json` present, a sweep is due only when the phase rule holds and now is at least `at` plus 0 after 1 failure, 30 minutes after 2, 60 after 3, doubling, at most `sweep_hours`
- S-112-15: a sweep that succeeds deletes `sweep-failed.json`; a dry run writes and deletes no `sweep-failed.json`; `shipmill gate --sweep` sweeps whatever it says
- S-112-16: a tick that skips a due sweep for the back-off ends its text line `; sweep backs off until <HH:MM> UTC after <count> failures`, and `--json`'s `walk.sweep_backoff` names the time and count, null otherwise
- S-112-17: with `[agents] app_id` set and the token minted, every `gh` read and script subprocess of `shipmill status` (report, `--item`, `--summary`), `shipmill queue` without `--fleet`, `shipmill goals report`, and `shipmill product plans` gets `GH_TOKEN` equal to the read token in that command's environment
- S-112-18: in those commands `gh api user` runs without the read token, the process's own `os.environ` gains no `GH_TOKEN`, and `decision answer`'s move writes with no read token in its environment
- S-112-19: the read token is asked with `TICK_READ_PERMISSIONS` over the repos `tick_repos` names, cached in the state folder's `app-token-tick.json` under S-093-6's reuse rule, and never appears on stdout or stderr or in a process's arguments
- S-112-20: those commands print `reads as app <app_id>` on stderr when they read as the App, `reads as host: <why>` when `[agents] app_id` is set and they fell back, and no `reads as` line without `[agents] app_id`; their stdout is the same in all three cases
- S-112-21: with the mint failing with a shipmill error, the command reads as the host, its stdout and exit code are those of the same command reading as the host, and stderr reads `reads as host: <the error's first line>`
- S-112-22: `shipmill goals report <owner/repo>` runs the wheel's `retro.py gather <owner/repo> --goals --checkout . --json`, passing `--checkout` and each `--bot` given, and prints its stdout and exits with its code
- S-112-23: `shipmill product plans <owner/repo>` runs the wheel's `intake_state.py <owner/repo> --plans --goals --json`, passing `--checkout`, `--bot-login`, and `--wip` given, and prints its stdout and exits with its code
- S-112-24: `docs/install.md` says that with `[agents] app_id` the read commands of S-112-17 read as the App with a read-only token, and `skills/product-intake/SKILL.md`'s PROJECT_START_DUE step tells a check issue's `## Check` that needs the goal report or the plan rows to name `shipmill goals report` or `shipmill product plans`, never a script path

## Out of scope

- shipmill/shipmill#1517, a tick that stays QUIET when every change since the cursor is the
  gate's own session's write: a new rule for what counts as a change (spec 046, spec 061, D-87),
  whose risk is missing a person's reply on a handed item (#1447) and whose read of the last
  event's actor costs reads of its own. A different design from this spec's; it gets a spec of
  its own
- shipmill/shipmill#1519, one change check for every gate on a host: a host-level reader that
  writes each gate's answer and a hand-off between gates, whose main question (who runs it) this
  spec doesn't share. The change check costs about a point a tick and reads as the App since
  spec 093, so it is the smaller saving; it gets a spec of its own
- shipmill/shipmill#1848, recording what each read spends: a different outcome, which went to
  intake apart. #1847's correction (sum each query's `rateLimit { cost }`, don't diff `used`) is
  for it
- A generic `shipmill run <script>` that runs any skill script with the read token: the two
  commands cover the chain that drains the budget; the other scripts a person's session runs
  (`triage_state.py`, `watch_state.py`, the weekly retro's full `gather`) stay on the person's
  `gh` until a measure shows they matter
- `shipmill queue --fleet`, `fleet.py`, and `shipmill factory`: they read repos of several
  owners, each with its own App, and keep reading as the person
- Naming the App's bot login in `reads as` (`shipmill-<owner>[bot]`): it takes a read of
  `/app`; the line names the App's id
- Moving the other skills' script lines (14 places) to shipmill commands: product-intake's plan
  and goal-report reads move here; the rest move with the commands that cover them

## Decisions relied on

- D-14
- D-54
- D-55
- D-58
- D-84
- D-90
- D-98
- D-112

## Issues

The build issues, filled in once they are filed: one `- owner/repo#N: S-NNN-1, S-NNN-2` per
line, naming the criteria that issue delivers. Each criterion belongs to exactly one.

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
