# S-094: Give each open item's holder, why, and what clears it in one JSON, per repo and per host

status: built
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

Such tooling also costs GitHub reads: on 2026-11-25 a caller that ran `status --item` once per
issue across 24 gates spent the maintainer login's GraphQL hour and tripped GitHub's secondary
limit, which starved the gates of reads for about 45 minutes.

The maintainer accepted it on 2026-11-25, with its spec and build to follow at once, and asked
for the records in a command of their own: shipmill gives a gated repo's status through narrow
read-only commands, each answering one question with `--json`, as `factory`, `autonomy`,
`window`, and `milestones` do, rather than more modes on `status`.

## Behaviour

### `shipmill queue`

`shipmill queue [owner/name] [--json] [--fleet] [--repo PATH]` (`src/shipmill/queue.py`)
answers one question: who holds each open issue and pull request of the repo, why, and what
clears it. It reads only and writes nothing on GitHub or on disk. The repo defaults to the
checkout's origin, as `status` does.

`--json` prints one object:

```json
{"schema": 1, "repo": "owner/name", "totals": {"issues": 87, "pulls": 6},
 "split": {"maintainer": {"issues": [1604], "pulls": [1598]}, "agent": {...}, "attention": {...},
           "people": {...}, "elsewhere": {...}, "postponed": {...}, "nobody": {...}},
 "items": [{"number": 1604, "kind": "issue", "holder": "elsewhere", "via": null, "accept": null,
            "why": "waits on other/repo#12 (open)", "clears": "other/repo#12 closing or merging",
            "waits_on": ["other/repo#12"],
            "conditions": [{"reason": "...", "who": "event", "clears": "...", "holder": "elsewhere"}]}]}
```

`split` names each holder's issues and pull requests, ascending; `items` holds one record per
open issue and pull request, ascending by number:

- **`conditions`:** the conditions `status --item` gives the item (spec 088,
  `src/shipmill/item_status.py`), each with its own `holder`, read by the same code
- **`holder`:** the item's line, placed as spec 091 places it (its own conditions, then the
  items it counts with), from the holders below
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

The text prints the repo with its totals, then each holder's label, in the order of the table
below, with its items under it, one line each: `#N <kind>: <why> (clears: <clears>)`.

### Finer holders

Each condition has a holder, from its `who` unless a rule below names another:

| Holder | Label | Condition |
|---|---|---|
| `maintainer` | waits on you | `who` is `maintainer`, save labelled blocked |
| `agent` | agent takes it | `who` is `agent` |
| `attention` | needs attention | the gate's record holds it (GATE_RETRY, GATE_PAUSED, GATE_IDLE), as in spec 091 |
| `people` | waits on people | `who` is `person`: an assignee, the reporter's answer, a draft's author |
| `elsewhere` | waits elsewhere | a BLOCKED wait on an item of another repo, an upstream report (UPSTREAM, or triaged upstream), labelled blocked (it waits on an outside event, which the maintainer marks by removing the label) |
| `postponed` | postponed | POSTPONED, triaged postponed, or any wait of a parent whose note starts `children K/N closed`, a plan moving through its children |
| `nobody` | waits on nobody | any other `event`: a pending check, a closed land window, a veto window, a wait on an item of this repo |

An item's line is the first in the order `attention`, `maintainer`, `agent`, `people`,
`elsewhere`, `postponed`, `nobody` among its conditions' holders, and with spec 091's links,
among its own line and those of the items it counts with. A parent moving through its children
counts by its own conditions alone, not with its children: they are listed on their own lines.

### One read of the repo's facts

`queue` builds every record from one read of the repo's facts: watch_state.py's rows,
triage_state.py's states, the open pull requests, and the open pull requests' checks, review
decision, and labels in one `gh pr list` beside them. It makes no read per item: no
`gh pr view`, no `status --item` of its own. `status --summary` reads the pull requests' checks
the same way.

### `status --item` and `status --summary`

`status --item N --json` (spec 088) adds `"schema": 1` as its first key, the same `holder`,
`via`, `accept`, `why`, `clears`, and `waits_on` as `queue`'s record of N, built by the same
code, and the same `holder` on each condition. To place an item that counts with another, it
reads the rows and the conditions of the open items of this repo it counts with, as `queue`
does, so the two agree for every item.

`status --summary` keeps spec 091's lines and JSON keys, with no `schema` and no `items`. Its
split comes from the same records as `queue`'s, with `people`, `elsewhere`, and `postponed`
counted on its `waits on nobody` line; a parent moving through its children counts there too.
This supersedes spec 091 in two cases: a labelled-blocked issue, whose condition is the
maintainer's (S-091-6), now waits on an outside event and counts as `waits on nobody`, and a
parent moving through its children no longer counts with them (S-091-7).

### A schema version

The JSON of `queue --json`, of `queue --fleet --json`, and of `status --item --json` carries
`"schema": 1` as its first key. A change that removes or renames a key, or changes a value's
meaning, raises it; a new key leaves it.

### The fleet form

`shipmill queue --fleet [--json]` reads every gate job on this host (`src/shipmill/launchd.py`'s
`gate_repos`, the plists `shipmill launchd` writes) and gives each one's repo from its job's
`WorkingDirectory`, the gate's checkout, in plist order. With `--json` it prints one object,
`{"schema": 1, "repos": [...]}`, each entry the repo's `queue --json` object. It reads one
repo at a time, never several at once. A repo whose read fails is the entry
`{"schema": 1, "repo": "owner/name", "error": "<its error's first line>"}` (in the text, the
line `owner/name: unread: <error>`), and the others still print (D-55). Once a repo's read
fails on GitHub's rate limit, it reads no further repo: each remaining one is an entry whose
error says it was not read because GitHub's rate limit was reached, so a fleet read never
spends the budget the gates read with. A host with no gate job prints
`{"schema": 1, "repos": []}`, or `no gate job on this host` in the text. It exits 0 when every
repo was read, 2 when one was not. `--fleet` with a repo named exits 2 naming the flags.

## Acceptance criteria

- S-094-1: `queue --json` prints one object with `schema`, `repo`, `totals`, `split` (all seven holders), and `items`, one record per open issue and pull request, ascending, each with `number`, `kind`, `holder`, `via`, `accept`, `why`, `clears`, `waits_on`, and `conditions`, and the record's `holder` is the line `split` puts it on
- S-094-2: an item placed by its own conditions has `via` null and the `why` and `clears` of its first condition with that holder; an issue that counts with an open item of the repo names it in `via` and carries that item's `why` and `clears`
- S-094-3: `waits_on` names the not-closed targets of a BLOCKED note, of this repo or another, and the open pull requests of an IN_PROGRESS note, as `owner/name#N`
- S-094-4: a condition from an assignee or the reporter is `people`; a wait on another repo's item, an upstream report, or labelled blocked is `elsewhere`; POSTPONED, triaged postponed, or any wait of a parent moving through its children is `postponed`; any other event is `nobody`
- S-094-5: an item's line is the first in the order attention, maintainer, agent, people, elsewhere, postponed, nobody; a parent moving through its children counts by its own conditions alone
- S-094-6: an issue triaged as an opportunity or a plan has `accept` naming it and holder `maintainer`; any other item has `accept` null
- S-094-7: the text of `queue` prints the repo with its totals, then each holder's label in the table's order with one line per item, `#N <kind>: <why> (clears: <clears>)`
- S-094-8: `status --item N --json` carries the same `holder`, `via`, `accept`, `why`, `clears`, `waits_on`, and conditions as `queue`'s record of N, including an issue that counts with its pull request whose rows name only that pull request
- S-094-9: the JSON of `queue --json`, `queue --fleet --json`, and `status --item --json` carries `"schema": 1` as its first key
- S-094-10: `queue` reads the open pull requests' checks, review decision, and labels in one `gh pr list`, and runs no `gh pr view` and no command that writes, whatever the number of open items
- S-094-11: `queue --fleet --json` prints `{"schema": 1, "repos": [...]}` with one `queue --json` object per gate job on the host, in plist order, each read from its job's WorkingDirectory, one repo at a time; no gate job prints an empty list
- S-094-12: a repo of the fleet whose read fails is an entry with `repo` and `error`, the others still print, and the command exits 2; once a read fails on GitHub's rate limit, no further repo is read and each remaining entry says so; `--fleet` with a repo named exits 2
- S-094-13: `status --summary` keeps spec 091's lines and JSON keys, and counts the people, elsewhere, and postponed items of `queue` on its waits on nobody line

## Out of scope

- Anything about the maintainer beyond the gated repos: their own priorities, trackers, repos without a gate (shipmill/shipmill#1620)
- Gates on other hosts: the fleet form reads this host's launchd jobs only
- A new item state in `triage_state.py`: the holders read the states and notes it gives today
- Releases (branch sync, the release bot, tags, publish), chains (progress, stalled chains), the agents' sessions in `factory` (live, dead, idle hand-offs), and one shared snapshot of facts the commands read: a later spec each

## Decisions relied on

- D-16
- D-55
- D-87
- D-100

## Issues

- shipmill/shipmill#1620: S-094-1, S-094-2, S-094-3, S-094-4, S-094-5, S-094-6, S-094-7, S-094-8, S-094-9, S-094-10, S-094-11, S-094-12, S-094-13

## Verification

- S-094-1: `shipmill queue --json` on shipmill/shipmill printed `schema`, `repo`, `totals`, `split` with the seven holders, and 85 records for 79 issues and 6 pull requests, ascending, each with the nine keys and on its split line
- S-094-2: the same run's #1531 read `via` 1524 with #1524's why and clears, and #1516 `via` 1622, its spec pull request's question; #322 read its own `postponed` condition with `via` null
- S-094-3: #1531's `waits_on` was `["shipmill/shipmill#1524", "shipmill/shipmill#1528"]`, the open items its BLOCKED note names
- S-094-4: #338 (labelled blocked) read `elsewhere` and the postponed issues `postponed`; no issue there was a person's, so `people` and the rest of the table are each a case of `test_s094_4_each_condition_has_its_finer_holder`
- S-094-5: the run placed 63 items with the maintainer, 11 with the agent, 1 elsewhere, and 10 postponed, each once; a parent moving through its children read `postponed` in its test
- S-094-6: the run marked 50 issues `accept: "opportunity"` and 4 `accept: "plan"`, each held by the maintainer
- S-094-7: `shipmill queue` printed the repo with its totals, then each holder's label with its items as `#N <kind>: <why> (clears: <clears>)`
- S-094-8: `status --item N --json` for #1531 (linked), #338, and #322 matched `queue`'s record of N key for key
- S-094-9: `queue --json`, `queue --fleet --json`, and `status --item --json` each printed `"schema": 1` as their first key
- S-094-10: the run's reads were one `gh pr list` with the checks, reviews, and labels of every pull request beside the open pull request list, and no `gh pr view`, as `test_s094_10_one_read_of_the_facts_and_no_read_per_item` asserts of the commands run
- S-094-11: `queue --fleet --json` with a home holding one gate job printed `{"schema": 1, "repos": [...]}` with that job's repo, read from its WorkingDirectory; a home with none printed an empty list in its test, and the order of several in `test_s094_11_the_fleet_form_reads_every_gate_job`
- S-094-12: in that run the repo's read failed (gh had no login under the test home) and was its entry with `repo` and `error`, exit 2; the stop on GitHub's rate limit, in a `gh` read and in watch_state.py, is proven by its two tests, and `--fleet` with a repo exits 2 in its test
- S-094-13: `shipmill status --summary` on shipmill/shipmill printed spec 091's four lines, its JSON with spec 091's keys, with #338 and the postponed issues on waits on nobody
