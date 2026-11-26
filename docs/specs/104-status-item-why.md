# S-104: Say why an item can't move: a loop in its step, its pull request's state and merger, and every waiter in the product

status: approved
serves: G-4

## Problem

`shipmill status --item` (spec 088) names an item's conditions, its holder's step, what waits
on it, and what closes it, yet an agent asked why a parked item is open still needs more reads
to answer, and the real cause can sit in none of them (shipmill/shipmill#1627, grouping
shipmill/shipmill#1541). On one item of a product spread over three repos the agent needed six
more reads:

- **A loop printed as a step.** The step waited on another repo's deploy, and `blocks:` showed
  that deploy's issue waiting on this item through a third issue. Nothing can move, and the
  output carried both facts on adjacent lines without saying so
- **No state of the pull request that does the step.** Its checks and mergeability took a
  separate `gh pr view`
- **No word on who may merge it.** The pull request touched protected paths, so the App's merge
  was refused by the merge gate and a plain `gh pr merge` by the delivery hook; the agent
  learned both by trying, twice, before it could hand the maintainer the right command
- **No titles in the chain.** `blocks:` lists numbers and buckets, so the agent fetched each
  title to tell the maintainer what the chain is
- **A waiter missing from `blocks:`.** An issue in a second repo of the product carried
  `Depends on` the item, and its own `status --item` read that hold, yet the item's `blocks:`
  left it out: S-088-14 reads another repo's waiters only through GitHub's relations, and
  `Depends on` lines through this repo's own notes, so a `Depends on` line in another repo with
  no matching relation is left out by design

The maintainer accepted the opportunity (labels `opportunity` and `planned`) for its spec.

## Behaviour

This extends `shipmill status --item REF [--json]` (spec 088, `src/shipmill/item_status.py`,
`src/shipmill/item_links.py`, `src/shipmill/status.py`) with a `warning:` line, a `pr:` line
per open closing pull request, titles in `blocks:`, and waiters read from every repo of the
product. It still reads only and writes nothing on GitHub or on disk (S-088-12), and exits 0
whenever the item was explained, as spec 088 says: a read added here that fails prints
`unread: <why>` where its line would be and never ends the command.

```
owner/a#96 (https://github.com/owner/a/issues/96): parked
  why:     a person's item: waits on @maint
           clears: a person (the step)
  step:    Merge #97 and run it on production in the same window as owner/b's deploy (handoff, 2026-11-17)
  warning: the body names owner/b#263, which waits on this item (owner/b#263 -> owner/b#262 -> this): if the step needs it first, neither can move
  pr:      #97 "Add the ledger migration": checks passing, mergeable
           merge: the maintainer only, by hand (protected: migrations/**): gh pr merge 97 -R owner/a --squash
  blocks:  owner/b#262 "Ship the ledger reader" (parked: waits on this) -> owner/b#263 "Deploy the ledger" (parked: waits on #262)
  closes:  #71, #96 (by #97)
```

The lines come in this order: `step:`, `warning:`, `pr:`, `blocks:`, `closes:`, each only when
it has something to say.

### A loop: `warning:`

`warning:` says the item waits on something that waits on it. It compares the items its holder
names with the item's `blocks:` set (below), after `blocks:` is read:

- **The step:** the references in the `step:` line's source, the newest trusted hand-off
  (S-088-13), read whole, not cut at 200 characters
- **The body:** the references in the item's own body, read only when its author is an OWNER,
  MEMBER, or COLLABORATOR or the `--bot-login` (D-16), from the item's GraphQL read, which
  gains the `body` and `author` fields
- **Its holds:** the item's own open holds, the BLOCKED note's (S-088-6); a hold on a waiter is
  a loop whatever the text says

A reference is `#N` (the item's repo), `owner/name#N`, or a GitHub issue or pull request URL,
the shapes triage_state.py's `DEPENDENCY` reads; the item itself is never one. Each reference
that is in `blocks:` prints one `warning:` line, nearest waiter first:

- from the step or the body: `the step names <ref>` (or `the body names <ref>`), `, which waits
  on this item (<path>): if the step needs it first, neither can move`. A text that names an
  item only to say the item blocks it reads the same, so the line says what to check, not that
  the chain is stuck
- from a hold: `this item waits on <ref>, which waits on it (<path>): neither can move`

`<path>` is the chain from the named waiter to the item through `blocks:`'s holds, each link
shown as `blocks:` shows a hold, joined by ` -> ` and ending in `this`; with several paths, the
shortest, then the first by reference. A step, body, and holds that name nothing in `blocks:`
print no `warning:` line, and with `blocks:` unread there is none either.

### The pull request that does the step: `pr:`

For an issue, each open pull request whose closing keywords name it (the pull requests
`closes:` reads, S-088-15), in the same order, prints:

```
  pr:      #P "<title>": checks <checks>, <mergeability>
           merge: <who may merge it>
```

Its state comes from the item's one GraphQL read (S-088-16), whose closing pull request nodes
gain `title`, `isDraft`, `mergeStateStatus`, `baseRefName`, `labels`, `files`, and the head
commit's `statusCheckRollup` with each context's name and state: no read of its own.

- **checks:** `passing` when every check finished and none failed; `failing: <names>` when one
  failed, as item_status.py's `FAILED` reads; `pending: <names>` when none failed and one is
  pending, as `PENDING` reads; `none` with no check
- **mergeability**, from `mergeStateStatus`: `mergeable` (CLEAN, HAS_HOOKS, UNSTABLE),
  `behind <base>` (BEHIND), `conflicts with <base>` (DIRTY), `blocked by branch protection`
  (BLOCKED), `a draft` (DRAFT), `mergeability not computed yet` (UNKNOWN)

A pull request item prints its own `merge:` line after its conditions, with no `pr:` line,
since its conditions already name its checks and merge state (S-088-10).

### Who may merge it: `merge:`

`merge:` gives the first that applies, by the rules the merge itself is held by (spec 030's
`shipmill gh pr merge` hold, S-030-13 and S-030-23, `skills/github-pr-triage/scripts/pr_gate.py`,
and the delivery hook, D-54), each with its `who` as spec 088's conditions name it:

| Case | `merge:` reads | who |
|---|---|---|
| a draft | `its author, once they mark it ready (D-67)` | person |
| no `[agents]` at the base | `the maintainer (no gate): <command>` | maintainer |
| a zone at `never` | `the maintainer only, by hand (<zone>: <reason>; ...): <command>` | maintainer |
| labelled `needs-decision`, or a zone at `ask` | `a gate session, once you answer its question (<zone>: <reason>)` | maintainer |
| `[autonomy] land` below `act`, or a hold | `the maintainer once it is labelled shipmill-ready (land is <level>): <command>` | maintainer |
| otherwise | `a gate session, through shipmill gh pr merge (land is act)` | agent |

The zones and levels are `decide classify --pr P`'s (spec 030, `src/shipmill/classify.py`),
read at the checkout's `origin/HEAD`, never from the pull request (D-48), with the earned
level of spec 083 where it applies (D-101); the land level is `shipmill autonomy`'s (D-51).
`<command>` is the maintainer's own terminal's merge, `gh pr merge P -R owner/name --squash`,
or `--merge` when `[agents] merge = "merge"` (D-96): a session can't run it, since the
delivery hook refuses a plain `gh` write where the App is available (D-54) and the merge gate
refuses the App's merge of a `never` zone. When spec 036's resolved `maintainer` role names
users, `the maintainer` is followed by them, `(@a, @b)`.

The classification costs one read per open closing pull request: classify's `--pr` read of its
files and patches (and the production record only where spec 083's area-record rule already
reads it). It needs the checkout `status` runs in to be a clone of the item's repo with
`origin/HEAD` set and a `.github/shipmill.toml` there; otherwise, or when its read fails, the
line is `merge: unread: <why>` and names the fix (`git remote set-head origin --auto`, or run
it from a checkout of the item's repo), as the merge's own hold names it.

### Titles in `blocks:`

Each `blocks:` entry carries its title after its reference, in double quotes: `<ref> "<title>"
(<bucket>: waits on <holds>)`. The title comes from reads already made: triage_state.py's row
for an issue of this repo, chains.py show's row for the walk's, and the search hit (below) for
the product's; none costs a read. It is cut at 80 characters with `…`, control characters
dropped as the step's are (`CONTROL`), and a waiter with no title read (an untrusted row's,
which chains.py never prints) shows none.

### Every waiter in the product

`blocks:` keeps S-088-14's sources, the walk and this repo's BLOCKED notes, and adds the
`Depends on` lines of the product's other repos, so it lists the issues whose own
`status --item` reads them waiting on the item. This widens S-088-14, which by design reads
another repo's `Depends on` line only where GitHub records a matching relation.

- **The product's repos:** with `[product] repos` in this repo's config, those repos and this
  one; with `[product] home`, the home and the repos the home's `.github/shipmill.toml` lists
  on its default branch, one read of that file (D-53, D-84 for a component's session). A repo
  with neither reads no other repo, as today
- **The read:** a GitHub issue search per level of the `blocks:` walk, `is:issue is:open`,
  qualified by the product's repos other than this one (this repo's waiters come from its
  notes), naming each item of the level not yet searched as `owner/name#N` and as its URL
  path. GitHub's search narrows; it decides nothing: a hit counts as waiting on an item only
  when a line of its body, outside a fence, is a strict `Depends on` line (spec 041, the shape
  triage_state.py's `depends_lines` reads) naming that item, and its author is an OWNER,
  MEMBER, or COLLABORATOR of its repo or the `--bot-login` (D-16). Each counted hit holds its
  bucket `parked`, as another repo's BLOCKED issue reads today, its title, and as `waits_on`
  all the open references of its strict `Depends on` lines that the search or the walk saw
- **The cost:** at most 10 search requests per command, split where GitHub's query length or
  operator limit requires; the search API's own limit is apart from the GraphQL budget the
  gates read with (spec 094). A level found past the tenth request, or a search that fails,
  leaves what was found in `blocks:` and adds the line `  blocks:  other repos unread: <why>`
  under it

A waiter that the walk and the search both find is listed once, with its holds merged
(`item_links.merged`).

### JSON

`status --item --json` keeps every key of spec 088 and spec 094 and its `"schema": 1`, and adds,
each a new key (S-094-9):

- `warnings`: one `{"source": "step" | "body" | "hold", "ref": "owner/name#N", "path": [...]}`
  per `warning:` line, `path` the chain's references from the named waiter to the item; `[]`
  for none
- `pulls`: one per `pr:` line, `{"pull", "title", "checks": {"state": "passing" | "failing" |
  "pending" | "none", "failing": [...], "pending": [...]}, "merge_state", "merger"}`, with
  `merger` as `{"who", "reads", "zones": [...], "command"}` (`command` null when the maintainer
  runs none) or null with `merger_error` naming why; a pull request item has one entry for
  itself
- `title` on each `blocks` entry (a string, or null when none was read)
- `blocks_unread`: null, or why the product's search stopped

`shipmill queue --json` (spec 094, `src/shipmill/queue.py`) adds the same `title` to each of
its `blocks` entries, from triage_state.py's rows it already reads, so the two shapes stay
equal; it makes no search and no read per item (S-094-10), so its `blocks` stays S-094-14's
and S-094-15's, and S-094-16's equality still holds where the walk finds no hold outside the
repo, a waiter the search finds being outside it. `queue` carries no `warnings` or `pulls`.

## Acceptance criteria

- S-104-1: on fixture facts where the item's newest trusted hand-off names an issue of its `blocks:` chain, `status --item` prints `warning:` naming that issue and the path from it to `this`, between `step:` and `blocks:`; where the step names nothing in the chain, or `blocks:` is unread, it prints no `warning:` line
- S-104-2: a reference in the item's body that is in `blocks:` prints `warning: the body names ...` when the body's author is an OWNER, MEMBER, COLLABORATOR, or the `--bot-login`, and nothing when another author wrote it; the item's own open hold on a waiter prints `warning: this item waits on <ref>, which waits on it (...): neither can move`; a reference to the item itself never warns
- S-104-3: for an issue with an open closing pull request, `pr:` prints its number, title, checks as `passing`, `failing: <names>`, `pending: <names>`, or `none`, and its mergeability from each `mergeStateStatus` value in the table, read from the item's one GraphQL read with no `gh pr view`; a closed or merged pull request prints none
- S-104-4: `merge:` reads each row of the table on fixture facts: a draft, no `[agents]`, a `never` zone (with each zone and reason and `gh pr merge P -R owner/name --squash`, or `--merge` under `[agents] merge = "merge"`), `needs-decision` or an `ask` zone, land at `propose` or a hold, and land at `act` with no zone above `notify`
- S-104-5: a pull request whose files fall under a REVIEW.md Protected area at `never` reads `merge: the maintainer only, by hand (protected: ...)`, followed by the resolved `maintainer` role's users, with the levels read at `origin/HEAD` even where the pull request edits `[decisions]`
- S-104-6: a checkout whose origin is not the item's repo, `origin/HEAD` unset, no config at `origin/HEAD`, or a failed classify read prints `merge: unread: <why>` naming the fix and exits 0; a pull request item prints its own `merge:` line and no `pr:` line
- S-104-7: each `blocks:` entry prints its title in double quotes after its reference, cut at 80 characters with control characters dropped, from reads already made; an entry without a read title prints none
- S-104-8: on fixture facts where an issue of a second product repo, by a trusted author, has a strict `Depends on` line naming the item, and an issue of a third product repo depends on that one, both with no GitHub relation, `blocks:` lists both; an untrusted author's, a closed issue's, a fenced or malformed line's, a mere mention's, and a repo outside the product's hit lists nothing
- S-104-9: a repo with no `[product]` makes no search; a component reads its home's config once; a command makes at most 10 search requests; past them, or on a failed search, `blocks:` keeps what it found, adds `blocks:  other repos unread: <why>`, and exits 0
- S-104-10: `status --item --json` keeps `"schema": 1` and every key spec 088 and spec 094 give it, and adds `warnings`, `pulls` (with `merger` or `merger_error`), `title` on each `blocks` entry, and `blocks_unread`
- S-104-11: `queue --json`'s `blocks` entries carry the same `title` as `status --item --json`'s for the same waiter, with no new read (no search, no `gh pr view`), and `queue` keeps every other key and value it gave before
- S-104-12: on the fixture of shipmill/shipmill#1541's Check, with repo names of the fixture, `status --item` prints the `warning:` line, `pr:` with the maintainer as the only merger, and `blocks:` listing the waiters of both other repos with their titles

## Out of scope

- A `warning:` read from free text beyond references: a step that names another repo's deploy in words ("the other part's deploy") is not matched; the spec gate's rule that a person's step holds on its preconditions through `Depends on` lines (spec-gate.md, A step only a person can do) is what makes such a wait readable
- Telling whether a text that names a waiter needs it first: the line says what to check
- Searching outside the product's repos, or reading a waiter's triage state: a counted hit reads `parked`, even one its own repo would still read NEW before triage
- Changing `queue` beyond `title`: `warnings`, `pulls`, and the product's search stay `status --item`'s, since `queue` makes no read per item (S-094-10)
- Merging, labelling, or posting the command anywhere: `--item` reads only

## Decisions relied on

- D-16
- D-48
- D-51
- D-53
- D-54
- D-55
- D-67
- D-84
- D-96
- D-101

## Issues

## Verification
