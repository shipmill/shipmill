# S-091: Say in a few lines whether the gate works and who holds the open work

status: approved
serves: G-4

## Problem

The maintainer's first question about a repo is "what is its status": is the gate working,
and who holds the open work. `shipmill status` answers it as a list of every item by bucket
(more than 100 lines on shipmill's own repo), so the answer has to be counted by hand. Whether
the gate works is in its log and its state directory (`tick.json`, `last-result.json`), not
on one line, and an item handed to a session that died read "the gate takes it up on a coming
tick" until spec 089 put the hand's end in `handed.json` (shipmill/shipmill#1512). A local
script outside shipmill builds the answer from `status`'s text and the gate's log, and breaks
whenever either changes (shipmill/shipmill#1522).

The maintainer accepted it as a feature on 2026-11-25, with its spec and build to follow at
once.

## Behaviour

`shipmill status --summary [--json] [owner/name] [--repo PATH]` prints the repo's status in a
few lines. It reads only and writes nothing on GitHub or on disk. `--summary` can't be
combined with `--rows` or `--item`; either exits 2 naming the flags.

```
shipmill/shipmill: 87 open issues, 6 pull requests
  gate             RUNNING 4 min ago: session f7a49869 on ISSUES UNBLOCKED; last result 2 h ago (session 0b1c2d3e on PRS_OPEN #1599); last landed #1592 1 h ago
  waits on you     14 issues, 1 pull request
  agent takes it   9 issues, 5 pull requests
  needs attention  none
  waits on nobody  64 issues
```

### The gate line

Read from the gate's state directory (`src/shipmill/gate.py`'s `state_dir`, shared by every
worktree of the checkout) and one GitHub read:

- **The last tick:** `tick.json`'s action and its age, `<ACTION> <ago> ago`; `no tick
  recorded` without the file
- **A session now:** when the last tick's action is `RUNNING` or `STALLED`, its `running`
  session and item, `session <id8> on <item>`; when it is `LAUNCH` or `SESSION_DEAD`, the
  session `gate.json` recorded with its item; else `no session runs`. A session id is shown by
  its first 8 characters on the text line and in full in `--json`
- **The last result:** `last-result.json`'s session, item, and age, `last result <ago> ago
  (session <id8> on <item>)`; `no session has ended with a result yet` without the file
- **The last landed pull request:** the newest `mergedAt` among the merged pull requests of
  the default branch's last 10 commits, as the gate's change check reads it (S-048-21),
  `last landed #N <ago> ago`; `no landed pull request in the last 10 commits` without one

A state file that can't be read puts `unread <file>: <its error's first line>` in its part
and the command goes on (D-55: a check that fails prints its error and the rest still run).
A config without `[agents]` prints `gate  none: no [agents] in .github/shipmill.toml` in
place of the parts.

### The totals and the split

The totals count the open issues and open pull requests the picture lists (triage_state.py's
issues that are not closed, and `gh pr list`'s open pull requests). Each open item counts on
exactly one of four lines:

- **waits on you:** the maintainer holds it: a needs-decision question, an opportunity or a
  plan to accept or decline, a review required, a merge under `land = "propose"`, a hold, a
  stage below `act`
- **agent takes it:** the gate takes it up on a coming tick, or a session fixes, rebases, or
  reviews it
- **needs attention:** an error holds it from the agent: its session ended error and it waits
  for the backoff (GATE_RETRY), the sessions' credential is paused by a usage limit or a
  refused credential (GATE_PAUSED), or it was handed to a session that wrote nothing on it and
  the gate won't hand it again until it changes (GATE_IDLE)
- **waits on nobody:** it waits on an event or a person outside the factory: postponed, a
  pending check, a closed land window, an upstream fix, an assignee or a reporter

The split is read from the same conditions `shipmill status --item` gives each item (spec
088), so the summary and `--item` never disagree, and through them from watch_state.py's
`GATE_RETRY`, `GATE_PAUSED`, and `GATE_IDLE` rows, which watch_state.py reads from the gate's
own hand-off record, `handed.json` (spec 046, D-87, and each hand's `ended`, spec 089). An
item's line is the first of these that holds:

1. **needs attention**, when one of its conditions comes from a `GATE_RETRY`, `GATE_PAUSED`, or
   `GATE_IDLE` row
2. **waits on you**, when a condition's `who` is `maintainer`
3. **agent takes it**, when a condition's `who` is `agent`
4. else **waits on nobody** (`who` is `person` or `event`)

An issue counts where its pull request, or the item it waits on, sits: an issue whose
conditions name an open pull request of the repo (IN_PROGRESS, AGENT_DRAFT) or an open item of
the repo it waits on (BLOCKED) counts on the first line, in the order above, among its own
line and the lines of the items it names. A cycle of such links counts each item in it by its
own conditions alone; an item of another repo or a closed one adds nothing.

`--json` prints one object:

```json
{
  "repo": "owner/name",
  "gate": {"configured": true, "tick": {"at": "...", "action": "RUNNING"}, "tick_error": null,
           "running": {"session": "...", "item": "..."}, "result": {"session": "...", "item": "...", "at": "..."},
           "result_error": null, "landed": {"number": 1592, "at": "..."}},
  "totals": {"issues": 87, "pulls": 6},
  "split": {"maintainer": {"issues": [1604], "pulls": [1598]}, "agent": {...}, "attention": {...}, "nobody": {...}}
}
```

`gate` is `{"configured": false}` without `[agents]`. Each split names its numbers, ascending.

### Reads

The summary makes the readings `status --item` makes for every item at once (`src/shipmill/status.py`'s
watch_state.py rows, triage_state.py's issue states, the open pull requests, `[autonomy]`, the
gate's `[agents]`), plus each open pull request's checks, review decision, and labels, read
beside each other, and the default branch's last landed pull request. It runs none of the
host's other checks (the launchd job, the App check, the plugin, the worktrees): those are
`shipmill factory`'s (D-55).

### Exit codes

0 when the summary was printed, 2 on a combination of flags it refuses or a failed GitHub read,
as `shipmill status` exits 2.

## Acceptance criteria

- S-091-1: `status --summary` prints the repo with its open issue and pull request totals, a `gate` line, and the four split lines in the order waits on you, agent takes it, needs attention, waits on nobody; `--summary` with `--rows` or `--item` exits 2
- S-091-2: the gate line names the last tick's action and age, the running session and item from tick.json (RUNNING, STALLED) or gate.json (LAUNCH, SESSION_DEAD), the last result from last-result.json, and the last landed pull request, each with its own wording when absent
- S-091-3: an unreadable tick.json or last-result.json puts its error in its part and the summary still prints, exit 0; a config without `[agents]` prints the gate as none
- S-091-4: every open item counts on exactly one split line, so the four lines' counts sum to the totals
- S-091-5: an item named by a GATE_RETRY, GATE_PAUSED, or GATE_IDLE row counts as needs attention, before any other condition it has
- S-091-6: an item with no attention condition counts as waits on you when a condition is the maintainer's, else agent takes it when one is an agent's, else waits on nobody, by the conditions `status --item` gives it
- S-091-7: an issue whose conditions name an open pull request or an open item of the repo it waits on counts on the first line among its own and theirs; a cycle of links ends, each item in it counted by its own conditions
- S-091-8: `--json` prints one object with `repo`, `gate`, `totals`, and `split`, each split naming its issues and pulls ascending
- S-091-9: `--summary` writes nothing: it runs no `gh` command that writes and no `shipmill gh`

## Out of scope

- The fleet's one row per repo in `fleet.py report`: it can read `--json` later
- Why one item is open: `status --item`'s (spec 088)
- The host's machinery: `shipmill factory`'s (D-55)

## Decisions relied on

- D-16
- D-55
- D-87
- D-100

## Issues

- shipmill/shipmill#1522: S-091-1, S-091-2, S-091-3, S-091-4, S-091-5, S-091-6, S-091-7, S-091-8, S-091-9

## Verification

Filled in when the spec reaches `built`.
