# S-088: Say why one open issue or pull request is not closed

status: built
serves: G-4

## Problem

`shipmill status` sorts every open issue and pull request into a bucket (`needs decision`,
`to triage`, `to build`, `in progress`, `to land`, `parked`), but nothing answers for one
item. A maintainer or an agent who wants to know why #N is still open reads the whole repo's
picture, then pieces the rest together from `merge-checks`, `window`, and
`decide classify --pr N`. Two buckets give no reason at all: an issue on the `parked` line
shows only `triaged`, so nothing says whether it waits on product intake, the maintainer, or
its reporter; and a pull request `to land` doesn't say what holds the merge (a red or pending
check, a missing review, `needs-decision`, the land level, a hold, a closed land window).
Only a dependency hold says what it waits on today (shipmill/shipmill#1461).

The maintainer asked for it on 2026-11-22 and accepted it as a feature in a session that day.

## Behaviour

`shipmill status --item REF [--json] [owner/name] [--repo PATH]` explains one open item. It
reads only, writes nothing on GitHub or on disk, and is deterministic for the same GitHub
state: it makes the readings the picture makes (`src/shipmill/status.py`'s watch_state.py
rows, triage_state.py's issue states, the open pull requests, `[autonomy]`, and the gate's
`[agents]`), plus, for a pull request, one `gh pr view` of its checks, review decision, and
labels, and, with a `[land.window]`, the window at now (`src/shipmill/land_window.py`).

### The item

REF is any of:

- a number, `1439`: GitHub numbers issues and pull requests alike, so the command finds
  which it is among the repo's open items
- a URL, `https://github.com/<owner>/<name>/issues/<N>` or `.../pull/<N>`, with an optional
  trailing `/`, `#...` fragment, or `?...` query; its `owner/name` must be the repo the
  command reads (the positional slug, else the checkout's origin), compared case-blind

A number and the URL naming the same item give the same output. A REF that is neither, a URL
of another repo, a URL whose kind (`issues` or `pull`) is not the item's kind, or a number
that is no open issue or pull request of the repo exits 2 with one `shipmill:` line naming
the REF. `--item` can't be combined with `--rows`.

### What it prints

```
shipmill/shipmill#1461 (https://github.com/shipmill/shipmill/issues/1461): parked
  why:  triaged as opportunity: waits for product intake to group it and the maintainer to accept it
        clears: the maintainer (accept the opportunity)
```

- The first line: the item as `owner/name#N`, its link, and its bucket, the label of the
  `shipmill status` line it is listed on (`needs decision`, `to triage`, `to build`,
  `in progress`, `to land`, `to merge`, `drafts`, `parked`), or `open` when the picture
  lists it on none
- Then one `why:` entry per condition that keeps it open, each followed by a `clears:` line
  naming who clears it and how: `the maintainer` (a decision, a merge, a level, a hold),
  `an agent` (the next gate tick), `a person` (an assignee or the reporter), or `an event`
  (a check finishing, the window opening, a linked item closing or merging)
- An item the gate takes up as it stands says so as its condition:
  `the gate takes it up on a coming tick, in its tier order`, cleared by an agent

After the conditions come up to three lines (#1473), each only when it has something to say:

```
  step:    Merge #97; Run its migration on production (handoff, 2026-11-17)
  blocks:  owner/b#262 (parked: waits on this) -> owner/b#263 (parked: waits on #262) -> owner/c#399 (parked: waits on owner/b#263)
  closes:  #96, #71 (by #97)
```

`--json` prints one object: `repo`, `number`, `kind` (`issue` or `pull`), `url`, `bucket`,
and `conditions`, each with `reason`, `who` (`maintainer`, `agent`, `person`, `event`), and
`clears`; then `step` (`text` and `date`, or null), `blocks` (each `ref`, `bucket`, and
`waits_on`), `blocks_error` (null, or why the walk failed), and `closes` (each `pull` and
its `issues`).

### The holder's step, what waits on the item, and what it closes

The maintainer accepted these three lines for a direct build on 2026-11-22 (#1473), so an
agent asked why an item is open sees who holds it, what they do, and what the chain waits on,
without rebuilding it by hand.

- **`step:`** the newest hand-off comment on the item, a comment whose first line is
  `<!-- shipmill:handoff -->` by the `--bot-login` or an OWNER, MEMBER, or COLLABORATOR (D-16,
  as triage_state.py counts a hand-off; anyone else's marker never counts). Its step is the
  hand-off's first block of `>` lines, the steps it quotes from the issue, with their list
  marks dropped and joined by `; `; a hand-off without one gives its first line after the
  marker, its leading mentions dropped. Whitespace is collapsed and the text cut at 200
  characters with `…`, then the hand-off's date: `(handoff, YYYY-MM-DD)`. An item with no
  such comment prints no `step:` line
- **`blocks:`** every open issue that waits on the item, directly or through others, across
  repos: the same holds spec 086 counts `held` from. They come from `chains.py show --json
  --trusted-only [--bot-login LOGIN] <the item>`'s walk (spec 017), down through what GitHub
  records waiting on an issue (`blocking`, `parent`), and from this repo's triage_state.py
  BLOCKED notes, which carry the `Depends on` lines GitHub records no reverse of. An open
  issue waits on an item when the item is among its open holds; an UNTRUSTED, UNREADABLE, or
  closed one waits on nothing here, so an outsider's link adds nobody, and the item itself is
  never listed, so a cycle adds nothing of its own. Nearest first, then by reference, each as
  `<ref> (<bucket>: waits on <its open holds>)`: the bucket is the picture's for an issue of
  this repo, and `parked` (BLOCKED) or `to triage` (CYCLE) for another repo's; the holds name
  the item as `this`, an item of the waiter's own repo as `#N`, any other as `owner/name#N`.
  The entries are joined by ` -> ` when each waits on the one before it alone, a single path,
  and by `, ` otherwise. A pull request starts no walk (GitHub records no relation on one), so
  its waiters are this repo's BLOCKED notes alone. A walk that fails prints
  `blocks:  unread: <the last line of its error>` and the command still explains the item
  (exit 0), as spec 086's watch reads a failed walk as a report-only row. Nothing waiting
  prints no `blocks:` line
- **`closes:`** for an issue, each open pull request whose closing keywords name it
  (`closedByPullRequestsReferences`), with the open issues merging it closes
  (`closingIssuesReferences`), as `<issues> (by #P)`, several joined by `; `; for a pull
  request, its own open closing issues. So a merge that also closes an item on another line
  is visible before it happens. None prints no `closes:` line

These reads cost no step of their own (#1469): the item's comments and closing pull requests
come in one GraphQL read, and it and the walk start beside triage_state.py's read, once the
item is known open and the bot's login read.

### The conditions

Every condition comes from a reading the picture or the gate already makes; nothing is
taken from an item's title, body, or comments beyond what the state scripts already read
(D-16).

- **Repo-wide:** an open `shipmill-hold` issue (the HOLD rows) holds everything the gate
  would do, cleared by the maintainer closing it; no `[agents]` in the config means no gate,
  cleared by the maintainer adding one or doing the step by hand; the stage the item waits on
  (`triage` or `fix` for an issue, `land` for a pull request) at `observe` or `propose` is the
  maintainer's to raise or to act on
- **An issue** reads its triage_state.py state: `NEEDS_DECISION` waits on the maintainer's
  answer; `BLOCKED` names each item it waits on and clears when they close or merge (an
  event), or the `blocked` label's removal; `POSTPONED` waits on a later release's revisit;
  `WITH_PERSON` waits on its assignees; `IN_PROGRESS` names its open pull requests; `TRIAGED`
  names its verdict, as below; `UPSTREAM` waits on the other repo's fix
- **A triaged issue's verdict:** triage_state.py's `TRIAGED` line carries `verdict`, the bold
  word of its newest triage comment when it is one the skills write (`opportunity`,
  `feature`, `clarify`, `needs a decision`, `postponed`, `won't fix`, `duplicate`, `plan`,
  `upstream`), and none otherwise. The picture's `parked` line shows it,
  `#N triaged: opportunity`, and `--item` says what it waits on: an opportunity waits on
  product intake and the maintainer's accept, a feature on its spec, `clarify` on the
  reporter, `needs a decision` and `plan` on the maintainer, `won't fix` and `duplicate` on a
  close. A triaged issue without a verdict waits for a new comment or label that moves it
- **The gate's turn:** an item is the gate's when a watch_state.py row the gate starts a
  session on (its `agent` mark) names it, the gate is configured, nothing holds it, and its
  stage is at `act`; then `--item` says the gate takes it up. An item in such a row while
  the stage is lower says the stage's level instead
- **A pull request:** a draft waits on its author (D-67); `needs-decision` on the
  maintainer's answer; GitHub's merge state `BEHIND` on an update of its branch, `DIRTY` on
  a rebase, `BLOCKED` on what branch protection asks; each failing check by name on a fix,
  each pending one on its run finishing (an event); a review decision `CHANGES_REQUESTED` or
  `REVIEW_REQUIRED` on a review; `shipmill-ready` under `land = "propose"` on the
  maintainer's merge; a `[land.window]` that holds one of its labels while the window is
  closed, on the window opening at the time it opens (an event)
- **Nothing found:** an open item none of these names says
  `no reason read: the gate's next tick reads it again`, cleared by an agent, so every open
  item names at least one condition

### Exit codes

0 when the item was explained, 2 on a malformed REF, an item that is no open item of the
repo, or a failed read, as `shipmill status` exits 2.

## Acceptance criteria

- S-088-1: `status --item N` and `status --item <the item's URL>` print the same output for the same open issue, and the same for an open pull request
- S-088-2: a REF that is neither a number nor a GitHub issue or pull request URL, a URL of another repo, a URL whose kind differs from the item's, or a number that is no open item of the repo exits 2 naming the REF
- S-088-3: the first line names the item, its link, and the bucket the picture lists it on, `open` when it is on no line
- S-088-4: every open item gets at least one condition, each with who clears it (`maintainer`, `agent`, `person`, or `event`) and how
- S-088-5: an open HOLD row, no `[agents]`, and the item's stage at `observe` or `propose` each add a condition the maintainer clears
- S-088-6: an issue's triage_state.py state gives its condition: NEEDS_DECISION, BLOCKED with each item it waits on, POSTPONED, WITH_PERSON with its assignees, IN_PROGRESS with its pull requests, UPSTREAM
- S-088-7: triage_state.py's TRIAGED line carries the newest triage comment's verdict when it is one the skills write, and none otherwise
- S-088-8: the picture's parked line shows a triaged issue's verdict, `#N triaged: <verdict>`, and `--item` says what that verdict waits on and who clears it
- S-088-9: an item that a row the gate starts a session on names, with the gate configured, no hold, and its stage at act, reads that the gate takes it up, cleared by an agent
- S-088-10: a pull request names each of: draft, needs-decision, merge state BEHIND, DIRTY, or BLOCKED, each failing and each pending check by name, a review decision CHANGES_REQUESTED or REVIEW_REQUIRED, shipmill-ready under land propose, and a closed land window that holds one of its labels with when it opens
- S-088-11: `--json` prints one object with `repo`, `number`, `kind`, `url`, `bucket`, and `conditions`, each with `reason`, `who`, and `clears`
- S-088-12: `--item` writes nothing: it runs no `gh` command that writes and no `shipmill gh`
- S-088-13: `step:` reads the steps quoted in the newest hand-off by the bot or an OWNER, MEMBER, or COLLABORATOR, with its date, or its first line without its mentions when it quotes none, cut at 200 characters; a marker by anyone else or further into a comment never counts, and an item without a hand-off prints no `step:` line
- S-088-14: `blocks:` lists every open issue a path of open holds leads from to the item, across repos (the walk's) and through this repo's `Depends on` notes, nearest first, each with its bucket and its open holds (`this`, `#N`, `owner/name#N`), joined by ` -> ` for a single path and by `, ` otherwise; an UNTRUSTED, UNREADABLE, or closed issue and the item's own cycle add nothing, a pull request starts no walk, and nothing waiting prints no `blocks:` line
- S-088-15: `closes:` names each open pull request that closes an issue with the open issues it closes, `(by #P)`, and for a pull request its own open closing issues; a closed or merged pull request and a closed issue are left out, and none prints no `closes:` line
- S-088-16: the item's read and the walk run beside triage_state.py's read; a failed walk prints `blocks:  unread: <its error>` and exits 0; `--json` carries `step`, `blocks`, `blocks_error`, and `closes`; and the item of #1473's Check prints its three lines

## Out of scope

- Ranking stuck or blocked work by what it holds back: spec 086's
- Why a closed item closed: `status` lists suspect and unverified closes already
- Explaining an item of another repo: the command explains one item of the repo it reads;
  `blocks:` names other repos' items with their walk state alone, and `status --item` in that
  repo explains each
- Ranking what waits on the item by weight, or a stalled chain: spec 086's `impact` and
  `stalled`

## Decisions relied on

- D-16
- D-67

## Issues

- shipmill/shipmill#1461: S-088-1, S-088-2, S-088-3, S-088-4, S-088-5, S-088-6, S-088-7, S-088-8, S-088-9, S-088-10, S-088-11, S-088-12
- shipmill/shipmill#1473: S-088-13, S-088-14, S-088-15, S-088-16

## Verification

Checked on the build's pull request against this repo, by running `shipmill status --item` on live items besides the tests `specs.py coverage --spec 088` lists in `tests/test_status_item.py`: #1461 (BLOCKED on its spec PR) read `parked`, waiting on shipmill/shipmill#1464 (open); #1441 by its pull URL read `to land`, conflicting with main, and handed to a gate session that wrote nothing on it.

- S-088-1: issue #4 and pull request #9 give the same output by number and by URL in `test_s088_1_*`
- S-088-2: a malformed REF, another repo's URL, the wrong kind, and a number that is no open item each name the REF and exit 2 in `test_s088_2_*`
- S-088-3: every state of each picture line reads that line's label, and a pull request's draft, to land, needs decision, and open buckets, in `test_s088_3_*`
- S-088-4: every issue state, with and without a gate, and an open pull request each name a condition with who clears it in `test_s088_4_*`
- S-088-5: a hold, no `[agents]`, and triage, fix, and land below act each add a maintainer's condition in `test_s088_5_*`
- S-088-6: NEEDS_DECISION, BLOCKED (a closed hold left out), labelled blocked, POSTPONED, WITH_PERSON, IN_PROGRESS, and UPSTREAM in `test_s088_6_*`
- S-088-7: the newest triage comment's verdict, a longer form of one, a curly apostrophe, and an unknown or unbolded word in `test_s088_7_*`; the two scripts' sets are asserted equal
- S-088-8: the parked line's `triaged: opportunity`, the item's condition, and a verdict triage_state.py doesn't write refused in `test_s088_8_*`
- S-088-9: an agent row's item at act reads the gate's turn, not under a hold, without a gate, or under propose; a pull request under land act, and a GATE_IDLE hand-off, in `test_s088_9_*`
- S-088-10: draft, needs-decision, behind, conflicts, a failing and two pending checks, changes requested, review required, shipmill-ready under propose, and a closed land window that opens again in `test_s088_10_*`
- S-088-11: `--json`'s one object, field by field, in `test_s088_11_*`
- S-088-12: the reads a pull request's explanation makes hold no write and no `shipmill gh` in `test_s088_12_*`
- S-088-13: the newest trusted hand-off's quoted steps, the bot's own, an outsider's marker and a quoted one refused, the first line without mentions, and the cut, in `test_s088_13_*`
- S-088-14: a tree of waiters across repos with this repo's buckets, untrusted, unreadable, and closed rows left out, this repo's `Depends on` notes followed transitively, a cycle, nothing waiting, and a pull request that starts no walk, in `test_s088_14_*`
- S-088-15: an issue's open closing pull requests in order, a merged one and a closed issue left out, and a pull request's own, in `test_s088_15_*` and `test_s088_14_a_pull_request_starts_no_walk`
- S-088-16: #1473's Check as one cross-repo chain, a walk that starts while triage_state.py is still read, a failed walk in text and `--json`, and an item with none of the three lines, in `test_s088_16_*`; on #1473's pull request, `--item 1431` here printed `blocks:  shipmill/shipmill#1342 (parked: waits on this)`, and `--item 1342` took 12.1 seconds against 12.0 on 0.161.2
