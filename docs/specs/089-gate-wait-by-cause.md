# S-089: A gate waits after a session by why it ended, and resumes once the cause is gone

status: approved
serves: G-1

## Problem

"A gate's wait after a session that could not run ignores the cause and outlives the fix"
(shipmill/shipmill#1512, an accepted opportunity). A gate treats a session that could not run
like one that ran and wrote nothing, so an item waits up to `retry_hours` (24 by default) after
the cause is gone, and sometimes for good. Seen in v0.163.1 and v0.163.2:

- A Claude usage limit is no authentication failure (`AUTH_FAILURE`): a session it stops within
  `DEAD_WITHIN` (60 s) reads dead, one it stops later reads as a run, so its item waits
  `retry_hours` at once. Each item in each gate on the host spends its own attempts finding the
  account's limit, and the limit's reset time in the session's log
  (`rate_limit_event.rate_limit_info.resetsAt`) is never read
- After `DEAD_STREAK` (3) dead sessions in a row the item is held for `retry_hours`, and
  replacing `~/.config/shipmill/claude-token` doesn't clear the hold: the gate's state records no
  credential
- A capped dead session's hands stay in `handed.json` (`without()` runs only when not capped).
  The same tick launches another item, `gate.json` then names that session, and the deaths are
  per item, so the walk past `retry_hours` no longer knows the first session died: its
  unchanged subjects turn idle and stay idle until they change. On 2026-11-24 every agent pull
  request here waited on nothing that way (#1431 #1432 #1434 #1440 #1471, then #1498 #1500 #1502
  #1504 #1505), behind sessions cf076ed3 and b65d4d03 that died on a usage limit
- A session that left a subject unchanged because it waits on another item goes idle on the
  subject alone: #1441 stayed idle after the answer it waited on came on #1253

The root cause: idle means "a session ran and chose to write nothing", but `handed.json` doesn't
record how the session ended, and `DEAD_WITHIN` guesses it from the time it took. The log already
says: a stream-json `result` event's `is_error`, and on a limit an `api_error_status` of 429 and a
`rate_limit_event` with `status: "rejected"` (a limit-killed `result` has `subtype: "success"`
with `is_error: true`).

Removing the wait isn't the fix: for an item without subjects it is the only bound on a session
that runs and writes nothing, and for a subject it gives spec 061's idle mark its time.

## Behaviour

This amends spec 046 (S-046-15, the dead-session rules), spec 048 (`ended_dead`) and spec 061
(idle) in `src/shipmill/gate.py`, `src/shipmill/walk.py`, `src/shipmill/status.py` and
`skills/github-ship-watch/scripts/watch_state.py`.

**How a session ended.** Once a headless launch's process is gone (D-17), the tick reads its
stream-json log's tail and records one end:

| End | Read from the log | Its hands | Counts as an attempt |
|---|---|---|---|
| `ok` | the last `result` event has `is_error: false` | kept; idle when the subject didn't change (spec 061) | yes |
| `limit` | an `api_error_status` of 429, or a `rate_limit_event` with `status: "rejected"` | dropped; the credential pauses | no |
| `auth` | an `api_error_status` of 401, or `AUTH_FAILURE` as today (#822) | dropped; the credential pauses | no |
| `error` | anything else: a `result` with `is_error: true`, no `result` at all, a log not stream-json, or a session a STALLED tick stopped | dropped and handed again after the backoff | yes, toward the backoff |

`limit` is read before `auth`, and `auth` before `error`. `DEAD_WITHIN` no longer decides a
headless session's end: a session that dies at minute 10 without a result is `error`. An
interactive session leaves no log, so `listed_dead` reads it as today.

**`handed.json` records the end.** Each hand gains `ended`: absent while its session runs, then
one of the four. Only a hand whose session ended `ok` can turn idle; the others never do. A hand
whose session ended `limit`, `auth`, or `error` drops on the tick that records it, whichever
session `gate.json` names by then, so a later launch can't orphan it. On the first tick after an
upgrade, a hand with no `ended` whose session is no longer running is classified once from its
session's log, and one whose log is gone reads `error`; so hands already stuck return to the
queue without a hand edit.

**The credential's pause, shared on the host.** A `limit` or `auth` end writes a record for the
credential the session used, in `$XDG_STATE_HOME/shipmill/claude/<credential>.json`
(`~/.local/state` when `XDG_STATE_HOME` is unset or empty). `<credential>` is the first 16 hex
digits of the SHA-256 of the token file's content (spec 035), or `login` for a gate with no
token file; the token itself is never written. The record holds the cause (`limit` or `auth`),
the session, when, and for `limit` the newest `resetsAt` the log carries. Every gate on the host
reads it before it launches: while a record for its credential holds, the tick starts no
session and reads PAUSED, naming the cause and when it ends. A paused tick still writes its
state and runs its prune as a QUIET one does.

- **`limit`:** while paused, each tick runs `claude -p "/usage"` with the sessions' own
  credential (`CLAUDE_CODE_OAUTH_TOKEN` from the token file, spec 035, never the host login),
  which calls no model, and lifts the pause on the first tick its output shows no window full.
  When its output can't be read, or the probe fails, the pause holds until the record's
  `resetsAt`, then lifts. With neither, it lifts after `retry_hours`
- **`auth`:** the pause holds until the token file's content changes, which changes
  `<credential>`, so the next tick reads no record and launches. A gate with no token file lifts
  it on the first tick `claude auth status` reports a login. One notification per pause, as
  CLAUDE_AUTH sends today
- **A token change ends either pause.** A usage limit belongs to the credential, so replacing
  the token file's content ends a `limit` pause too: the next tick reads no record for the new
  `<credential>`, launches, and probes with the new token should a limit hold there as well
- A pause counts no attempt against any item: the item that hit it is handed again once it
  lifts

**Backoff for an `error` end.** An item whose session ended `error` is handed again after 15
minutes, then 1 hour, then 4 hours, a delay per death in the run of `error` ends on that item;
after the third (`DEAD_STREAK`) the item is held for `retry_hours` and reported SESSION_DEAD as
today, and its hands never turn idle. A session that ended `ok` resets the run.

**Waiting on another item.** A session that leaves a subject unchanged because it waits on
another item names it in a comment on the subject whose first line is
`<!-- shipmill:waits-on <owner/repo>#<N> -->`, posted as the `--bot-login`. The walk that finds
the subject idle reads the subject's newest such marker by the bot; when the named item's
`updatedAt` is later than the hand's `at`, the subject is not idle and is handed again. A marker
by anyone else counts for nothing. The skills' instructions (github-pr-triage's and
github-issue-triage's hold comments) post the marker with the hold sentence they already write.

**`shipmill status` and the watch name the wait.** `shipmill status` and `watch_state.py` show a
paused gate as one row, `GATE_PAUSED <cause> until <time or "the token changes">`, with its fix
(the token's for `auth`, none for `limit`), and an item held by the backoff as
`GATE_RETRY <item> after <time>: <n> error ends in a row`. `shipmill status --item N` says the
same for an item whose hand is in backoff or under a pause, instead of "the gate takes it up on
a coming tick".

## Acceptance criteria

- S-089-1: A headless session whose log's last `result` has `is_error: false` ends `ok`; one whose log holds an `api_error_status` of 429 or a `rate_limit_event` with `status: "rejected"` ends `limit`, whatever its `result` says and however long it ran; one with an `api_error_status` of 401 or an `AUTH_FAILURE` line ends `auth`; any other ends `error`, a session with no `result` that ran past 60 s included
- S-089-2: Each hand in `handed.json` records its session's end as `ended` once the session is gone, and a hand loads without it as written before this spec
- S-089-3: A walk never marks idle a hand whose `ended` is not `ok`; a subject whose session ended `ok` and didn't change turns idle as S-061-4 and S-061-5 say
- S-089-4: A hand whose session ended `limit`, `auth`, or `error` drops on the tick that records the end, even when `gate.json` already names a later session; with the hands of cf076ed3 and b65d4d03 as `handed.json` held them on 2026-11-24 and their logs, the first tick after the upgrade classifies them `limit` and drops them, and their pull requests are handed again
- S-089-5: A `limit` or `auth` end writes `$XDG_STATE_HOME/shipmill/claude/<credential>.json`, `<credential>` the first 16 hex digits of the token file content's SHA-256 or `login`, holding the cause, the session, when, and for `limit` the log's newest `resetsAt`; the file never holds the token
- S-089-6: While a record for its credential holds, a tick of any gate on the host starts no session, reads PAUSED naming the cause and its end, and counts no attempt against the item that hit it
- S-089-7: While a `limit` pause holds, each tick runs `claude -p "/usage"` with `CLAUDE_CODE_OAUTH_TOKEN` from the token file, and the first tick whose output shows no window full removes the record and may launch
- S-089-8: When the `/usage` output can't be read or the probe exits non-zero, a `limit` pause lifts at the record's `resetsAt`, or after `retry_hours` when it has none
- S-089-9: After the token file's content changes, under a `limit` or an `auth` pause alike, the next tick reads no record for the new credential and launches the held item; a gate with no token file lifts an `auth` pause once `claude auth status` reports a login
- S-089-10: An `auth` pause sends one notification, and later ticks under the same pause send none
- S-089-11: An item whose session ended `error` is handed again 15 minutes, then 1 hour, then 4 hours after each death in its run; after `DEAD_STREAK` `error` ends in a row it is held for `retry_hours` and reported SESSION_DEAD, and a session ending `ok` on it resets the run
- S-089-12: An idle subject whose newest `<!-- shipmill:waits-on owner/repo#N -->` comment by the `--bot-login` names an item updated after the hand's `at` is handed again on that walk; the same marker by any other author leaves it idle
- S-089-13: `shipmill status` and `watch_state.py` print `GATE_PAUSED` with the cause and its end for a paused credential and `GATE_RETRY` with the item, the time, and the count for an item in backoff; `shipmill status --item N` names the pause or the backoff for an item it holds
- S-089-14: A session that ended `ok` and wrote nothing behaves as before this spec: a subject goes idle until it changes (spec 061), and an item without subjects is handed again after `retry_hours`

## Out of scope

- Holding sessions back at high use, before a limit is hit, from the same `/usage` read, and showing that read in `doctor` or `factory`: a follow-up once the probe has run in practice
- Billing gate sessions to Console API credit: #1478
- Sharing state between gates beyond the credential's pause (two gates on one item): #1465
- Interactive sessions' ends: they leave no log, and `listed_dead` keeps reading them as today

## Decisions relied on

- D-17
- D-58
- D-87
- D-100

## Issues

- shipmill/shipmill#1550: S-089-1, S-089-2
- shipmill/shipmill#1551: S-089-3, S-089-4, S-089-14
- shipmill/shipmill#1552: S-089-5, S-089-6, S-089-9, S-089-10
- shipmill/shipmill#1553: S-089-7, S-089-8
- shipmill/shipmill#1554: S-089-11
- shipmill/shipmill#1555: S-089-12
- shipmill/shipmill#1556: S-089-13

## Verification
