# S-095: A session that ended ok after an outside failure records that failure, not idle

status: approved
serves: G-1

## Problem

"A session that ends ok after an outside failure (GitHub limit, full disk, denied permission)
turns its item idle" (shipmill/shipmill#1644). Spec 089 reads how a session ended from its log:
`ok` when the last `result` event has `is_error: false`, and only an `ok` session's hands can
turn idle. A session can end `ok` although an outside cause stopped its work part way: its tool
calls failed, the model said it did nothing, and the result is no error. The gate then marks its
subject idle, as if the session had chosen to write nothing, and it waits as GATE_IDLE until it
changes.

The outside causes seen or likely on a host:

- **GitHub's rate limit:** `gh` answers `API rate limit already exceeded` (primary or
  secondary). On 2026-11-25 a host's GraphQL hour ran out from about 15:30 to 16:20 UTC; every
  gate tick and session on it failed its reads meanwhile
- **A full disk:** `No space left on device` from git, uv, or a write
- **A denied permission:** a headless session has no approval surface, so a tool call that needs
  approval is denied. A session on one gated repo had two such denials and ended `ok`
- **The network:** DNS or connection failures to GitHub, PyPI, or a registry

None of these is the item's fault, and none clears by a change on the item.

## Behaviour

This amends spec 089 (its table of ends, `handed.json`'s `ended`, and the host's pauses) in
`src/shipmill/gate.py`, `src/shipmill/walk.py`, `src/shipmill/host_pause.py`,
`src/shipmill/status.py`, `src/shipmill/item_status.py` and
`skills/github-ship-watch/scripts/watch_state.py`.

**The cause, read before `ok`.** Where spec 089 would record `ok` (the last `result` has
`is_error: false`, and no limit or auth end), the tick reads the tool results in the log's tail
first: each `tool_result` with `is_error: true` in a `user` event's `message.content`, its text
the `content` string or the `text` of its items. It records the first cause it finds, in this
order:

| Cause found | End | Its hands | Effect |
|---|---|---|---|
| a failed tool result reads GitHub's rate limit: `API rate limit exceeded`, `API rate limit already exceeded`, or `secondary rate limit`, case ignored | `github_limit` | dropped, handed again once the pause lifts | the host's gates pause their launches until the limit resets |
| a failed tool result reads `No space left on device` | `disk` | dropped, handed again once the pause lifts | the host's gates pause their launches until the free space is back above the floor |
| a failed tool result reads a network failure: `Could not resolve host`, `Temporary failure in name resolution`, `Connection refused`, `Connection reset by peer`, `Network is unreachable`, `error connecting to`, `connection timed out`, or `TLS handshake timeout`, case ignored | `error` | as spec 089's `error` | spec 089's backoff |

A session whose tool calls failed for any other reason keeps spec 089's rules and ends `ok`. A
denied permission is no end (D-113): a headless session meets one in most runs, at a tool call
the gate's allowlist doesn't hold, and goes on; read as an end that drops its hand, nearly every
ok session would be handed again on every tick and spec 061's saving would be gone. The session
keeps the end spec 089 and this table give it, and the gate notifies, as below.

**`handed.json` records the new ends.** `ended` gains `github_limit` and `disk`.
A hand whose session ended one of them drops on the tick that records it, as a `limit` hand
does, never turns idle, and counts as no attempt: it adds no death toward `DEAD_STREAK` and no
end to a run of `error` ends; the hand that replaces it starts a run anew, as after a `limit`. `watch_state.py` reads the two as it reads
spec 089's four.

**The host's pause.** A `github_limit` or a `disk` end writes a record for the host, beside the
credential's pauses: `$XDG_STATE_HOME/shipmill/host/<cause>.json` (`~/.local/state` when
`XDG_STATE_HOME` is unset or empty), holding the cause, the session, and when. Every gate on the
host reads both records before it launches, after the credential's pause: while one holds, the
tick starts no session and reads `PAUSED: <cause>: ...`, naming the cause and when it ends, and
writes its state and runs its prune as a QUIET one does. A pause counts no attempt against any
item. A lifted record stays on disk, marked lifted, so the same session's end never writes it
again.

- **`github_limit`:** the record holds `resets_at`, read from `gh api rate_limit` when the end is
  recorded: the latest `reset` of the `core` and `graphql` resources that have none
  `remaining`, none when neither is spent. While it holds, each tick runs `gh api rate_limit`
  (which spends no request of the budget) and lifts the pause on the first tick both resources
  show some remaining. When the probe fails or its output can't be read, the pause lifts at
  `resets_at`, or one hour after the end without one, GitHub's window
- **`disk`:** each tick reads the free space of the file system holding the gate's checkout and
  lifts the pause on the first tick it is at least the floor, 2 GiB (`DISK_FLOOR`). PAUSED and
  the `gate` check of `shipmill factory` and `shipmill status` name the free space, the floor,
  and the folder to free

**One notification per denied tool.** Once a headless session ended with a `result`, whatever
its end, the tick reads the tools it was denied: each `permission_denials` entry of the last
`result`, its `tool_name` and its `tool_input`'s `command` (or the input's other first string
value), else each failed tool result that reads `Permission for this tool use was denied` or
`Permission to use <tool> has been denied`, named by the tool and input of the `tool_use` it
answers. The command is shown by its first line, cut at 120 characters, so a heredoc or a token
further on never reaches a notification, the tick's output, or the record. The gate records each
tool once in its state folder, `denied.json`, with the command, the session, and when; for a tool
not yet recorded, and with `notify` on, it sends one notification: `session <id> was denied
<tool> (<command>): allow it in the gate's allowlist or [agents.sandbox], or leave it denied`,
with or without `app_id`, since no GitHub mention carries it. A later denial of a recorded tool
sends nothing. A failed send is tried again next tick. The denial changes nothing else: the
session's end, its hand, and the gate's launches are as they would be without it.

**`shipmill status` and the watch name the pause.** `shipmill status`, `shipmill status --item N`
and `watch_state.py` show a host pause as the `GATE_PAUSED` row spec 089 gives a credential's,
`GATE_PAUSED github_limit until <time>` or `GATE_PAUSED disk until <floor> free`, its detail
naming the session, and for `disk` the fix naming the folder.

## Acceptance criteria

- S-095-1: A headless session whose last `result` has `is_error: false` and that spec 089 reads neither `limit` nor `auth` ends `github_limit` when a failed tool result in its log's tail reads GitHub's rate limit, `disk` when one reads `No space left on device`, and `error` when one reads a network failure, in that order; a session whose failed tool results read none of these ends `ok`, and a denied permission, listed in `permission_denials` or read in a failed tool result, changes no end (D-113)
- S-095-2: `handed.json` records `github_limit` and `disk` as `ended`, and `watch_state.py` reads them; a hand whose session ended one of them drops on the tick that records the end, is never marked idle, adds no death toward `DEAD_STREAK`, and adds no end to the item's run of `error` ends
- S-095-3: A `github_limit` end writes `$XDG_STATE_HOME/shipmill/host/github_limit.json` holding the cause, the session, when, and `resets_at`, the latest reset of a `core` or `graphql` resource `gh api rate_limit` shows spent; a `disk` end writes `host/disk.json` holding the cause, the session, and when
- S-095-4: While a host pause holds, a tick of any gate on the host starts no session, reads `PAUSED` naming the cause and its end, and counts no attempt against any item
- S-095-5: While a `github_limit` pause holds, each tick runs `gh api rate_limit` and the first tick whose `core` and `graphql` both show some remaining lifts it; when the probe fails or can't be read, it lifts at `resets_at`, or one hour after the end without one
- S-095-6: While a `disk` pause holds, each tick reads the free space of the file system holding the gate's checkout and the first tick at or above `DISK_FLOOR` (2 GiB) lifts it; PAUSED, and the `gate` check of `shipmill factory` and `shipmill status`, name the free space, the floor, and the folder
- S-095-7: Once a headless session ended with a `result`, whatever its end, each tool it was denied is recorded in the gate's `denied.json` with its command's first line cut at 120 characters, the session, and when, and with `notify` on one notification naming the session, the tool, and that command is sent for a tool not yet recorded, with or without `app_id`; a later denial of a recorded tool sends none, a failed send is tried again next tick, and the session's end, its hand, and the tick's launch are as they would be without the denial
- S-095-8: `shipmill status`, `shipmill status --item N`, and `watch_state.py` print `GATE_PAUSED` with `github_limit` or `disk` and its end while a host pause holds

## Out of scope

- Reading GitHub as the App so the maintainer's budget stops running out under the gate's ticks: spec 093 (#1622)
- Waking an idle subject that waits on something: spec 092 (#1621)
- A configurable disk floor, and holding sessions back before the limit or the disk runs out
- Asking about a denied tool on GitHub (an issue or a comment) rather than by the gate's notification
- Interactive sessions' ends: they leave no log, as spec 089 says

## Decisions relied on

- D-17
- D-100
- D-112
- D-113

## Issues

- shipmill/shipmill#1644: S-095-1, S-095-2, S-095-3, S-095-4, S-095-5, S-095-6, S-095-7, S-095-8

## Verification

Filled in when the spec reaches `built`.
