# S-094: Give each open item's holder, why, and what clears it in one JSON, per repo and per host

status: approved
serves: G-4

## Problem

Spec 091's `status --summary --json` says whether the gate works and splits the open items by
who holds them, and spec 088's `status --item` says why one item is open. Neither says, for
every open item at once, why it sits where it does and what clears it, and neither covers
every gate on a host. A maintainer's own tooling that reports "what waits on me" across
several gated repos rebuilds that from `shipmill status`'s text, `handed.json`, and the
launchd plists, and breaks on the next release: the `stalled chains` line of spec 086 did
(shipmill/shipmill#1620). `waits on nobody` also lumps together an item assigned to a person,
one that waits on another repo, and a postponed one, which call for different follow-ups.

The maintainer accepted it on 2026-11-25, with its spec and build to follow at once.

## Behaviour

### One record per open item

`shipmill status --summary --json` (`src/shipmill/status_summary.py`) adds `items`: one record
per open issue and pull request, ascending by number:

```json
{"number": 1604, "kind": "issue", "holder": "elsewhere", "via": null, "accept": null,
 "why": "waits on other/repo#12 (open)", "clears": "other/repo#12 closing or merging",
 "waits_on": ["other/repo#12"], "conditions": [{"reason": "...", "who": "event", "clears": "...", "holder": "elsewhere"}]}
```

- **`conditions`:** the conditions `status --item` gives the item (spec 088,
  `src/shipmill/item_status.py`), each with its own `holder`, read by the same code
- **`holder`:** the item's line, as spec 091 places it (its own conditions, then the items it
  counts with), from the holders below
- **`via`:** `null` when the item's own conditions place it; else the number of the open item
  of this repo it counts with (its pull request, or the item it waits on, S-091-7) whose line
  it took
- **`why`** and **`clears`:** the reason and the clears of the first condition that places it:
  its own first condition whose holder is its line, or with `via`, the `why` and `clears` of
  the item it counts with
- **`waits_on`:** the open targets it waits on, as `owner/name#N`: the items of this repo or
  another that a BLOCKED note names and that are not closed or merged, and the open pull
  requests an IN_PROGRESS or AGENT_DRAFT note names; `[]` for a pull request and an issue
  with none
- **`accept`:** `"opportunity"` or `"plan"` for an issue triaged as such, which the maintainer
  accepts or declines; else `null`

`status --item N --json` adds the same `holder`, `via`, `accept`, `why`, `clears`, and
`waits_on`, and the same `holder` on each condition, built by the same code as the summary's
record, so the two agree for every item. To place an item that counts with another, `--item`
reads the conditions of the open items of this repo it counts with, as the summary does.

### Finer holders

Spec 091's `waits on nobody` splits into four. Each condition has a holder, from its `who`
unless a rule below names another:

| Holder | Condition |
|---|---|
| `attention` | the gate's record holds it (GATE_RETRY, GATE_PAUSED, GATE_IDLE), as in spec 091 |
| `maintainer` | `who` is `maintainer`, save labelled blocked |
| `agent` | `who` is `agent` |
| `people` | `who` is `person`: an assignee, the reporter's answer, a draft's author |
| `elsewhere` | a BLOCKED wait on an item of another repo, an upstream report (UPSTREAM, or triaged upstream), labelled blocked (it waits on an outside event, which the maintainer marks by removing the label) |
| `postponed` | POSTPONED, triaged postponed, or a parent whose note starts `children K/N closed`, a plan moving through its children |
| `nobody` | any other `event`: a pending check, a closed land window, a veto window, a wait on an item of this repo |

An item's line is the first in the order `attention`, `maintainer`, `agent`, `people`,
`elsewhere`, `postponed`, `nobody` among its conditions' holders, and with spec 091's links,
among its own line and those of the items it counts with. A parent moving through its children
counts by its own conditions alone, not with its children: they are listed on their own lines.
The `split` object gains the keys `people`, `elsewhere`, and `postponed`; the text adds the
lines `waits on people`, `waits elsewhere`, and `postponed` before `waits on nobody`.

### A schema version

The JSON of `status --summary --json` and `status --item --json` carries `"schema": 1` as its
first key. A change that removes or renames a key, or changes a value's meaning, raises it; a
new key leaves it.

### The fleet form

`shipmill status --summary --host [--json]` reads every gate job on this host
(`src/shipmill/launchd.py`'s `gate_repos`, the plists `shipmill launchd` writes) and summarizes
each one's repo from its job's `WorkingDirectory`, the gate's checkout, in plist order. With
`--json` it prints one object, `{"schema": 1, "repos": [...]}`, each entry the repo's
`status --summary --json` object. A repo whose summary fails is the entry
`{"schema": 1, "repo": "owner/name", "error": "<its error's first line>"}` (in the text, the
line `owner/name: unread: <error>`), and the others still print (D-55). A host with no gate job
prints `{"schema": 1, "repos": []}`, or `no gate job on this host` in the text. It exits 0 when
every repo was summarized, 2 when one failed. `--host` without `--summary`, or with a repo
named, exits 2 naming the flags.

## Acceptance criteria

- S-094-1: `status --summary --json` lists every open issue and pull request once in `items`, ascending, each with `number`, `kind`, `holder`, `via`, `accept`, `why`, `clears`, `waits_on`, and `conditions`, and the record's `holder` is the line `split` puts it on
- S-094-2: an item placed by its own conditions has `via` null and the `why` and `clears` of its first condition with that holder; an issue that counts with an open item of the repo names it in `via` and carries that item's `why` and `clears`
- S-094-3: `waits_on` names the not-closed targets of a BLOCKED note, of this repo or another, and the open pull requests of an IN_PROGRESS note, as `owner/name#N`
- S-094-4: a condition from an assignee or the reporter is `people`; a wait on another repo's item, an upstream report, or labelled blocked is `elsewhere`; POSTPONED, triaged postponed, or a parent moving through its children is `postponed`; any other event is `nobody`
- S-094-5: an item's line is the first in the order attention, maintainer, agent, people, elsewhere, postponed, nobody; a parent moving through its children counts by its own conditions alone
- S-094-6: an issue triaged as an opportunity or a plan has `accept` naming it and holder `maintainer`; any other item has `accept` null
- S-094-7: the text summary prints `waits on people`, `waits elsewhere`, and `postponed` before `waits on nobody`, and `split` carries all seven holders
- S-094-8: `status --item N --json` carries the same `holder`, `via`, `accept`, `why`, `clears`, `waits_on`, and conditions as the summary's record of N, including an issue that counts with its pull request
- S-094-9: the JSON of `status --summary --json` and `status --item --json` carries `"schema": 1`
- S-094-10: `status --summary --host --json` prints `{"schema": 1, "repos": [...]}` with one summary object per gate job on the host, in plist order, each read from its job's WorkingDirectory; no gate job prints an empty list
- S-094-11: a repo of the fleet whose summary fails is an entry with `repo` and `error`, the others still print, and the command exits 2; `--host` without `--summary` or with a repo named exits 2

## Out of scope

- Anything about the maintainer beyond the gated repos: their own priorities, trackers, repos without a gate (shipmill/shipmill#1620)
- Gates on other hosts: the fleet form reads this host's launchd jobs only
- A new item state in `triage_state.py`: the holders read the states and notes it gives today

## Decisions relied on

- D-16
- D-55
- D-87
- D-100

## Issues

- shipmill/shipmill#1620: S-094-1, S-094-2, S-094-3, S-094-4, S-094-5, S-094-6, S-094-7, S-094-8, S-094-9, S-094-10, S-094-11

## Verification

Filled in when the spec reaches `built`.
