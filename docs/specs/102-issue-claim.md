# S-102: An issue is never worked by two sessions at once

status: approved
serves: G-1

## Problem

"Nothing tells two workers on one repo that an issue is already taken" (shipmill/shipmill#1465),
so one issue can be worked twice. The opportunity is shipmill/shipmill#1511.

- Whether a subject is taken lives only in one gate's `handed.json` (spec 061, D-87), so two
  gates on one repo, on two hosts or a gate plus a `/loop` (spec 009), can hand the same issue
  on the same tick
- A session started by hand (`github-issue-resolve` on one issue) is invisible to the gate
  until it opens a pull request
- The one shared signal, an open linked pull request (`triage_state.py` reads IN_PROGRESS),
  "appears only once the work is done, so two sessions can each spend a full fix before either
  sees the other" (#1465)

The cost is duplicate work and two competing pull requests for one issue, one of which the PR
reviewer has to refuse. A maintainer who runs more than one gate on a repo, or starts sessions
by hand while the gate runs (U-1), pays for it, and so do the agents whose work is thrown away
(U-4).

Any fix has to keep four constraints the opportunity names:

- **N-2 and D-87:** the claim is a fact on GitHub; `handed.json` stays a cache of the gate's own
  launches, not state another reader needs
- **Noise:** each claim and each renewal must not notify the issue's watchers; a lease renewed
  by comment would flood the thread, and even an edited comment moves the issue's `updatedAt`,
  which spec 061 reads as a session's write
- **D-67 and github-issue-triage's hard rule 7:** no agent parks a pull request as a draft, save
  an auto-fix loop
- **A dead session's claim lapses by itself,** or one crash blocks the issue for good

## Behaviour

### The claim is a ref on GitHub

A claim is a git ref in the repo on GitHub, `refs/shipmill/claims/<N>`, one per issue or pull
request number `N`. It points to a **claim commit**: a commit with the empty tree whose message
is exactly

```text
shipmill claim #<N>
holder: <holder>
until: <YYYY-MM-DDTHH:MMZ>
```

- `holder` names who holds it: `gate <session id>` for a gate's session, or the id
  `shipmill claim` printed for a session started by hand (a UUID4)
- `until` is the lease's end in UTC, from the writer's clock
- A claim is **live** while `until` is after now, and **lapsed** from then on. A lapsed claim
  holds nothing: nobody has to delete it, and the next claimer replaces it

A ref is the claim because it is the only fact on GitHub that is written without a notification
and without touching the issue: creating or moving a ref outside `refs/heads/` and `refs/tags/`
notifies no watcher, shows in no issue timeline, starts no workflow (`on: push` filters on
branches and tags), and leaves the issue's `updatedAt` where it was, so spec 061's idle reading
is unchanged. The claim commit is written with `POST repos/<repo>/git/commits` on the empty
tree; `claims.py` calls no issue, comment, label, or pull request endpoint. Only a writer with push access can write one, so a claim is a trusted author's by
construction (D-16). A clone's default refspec fetches `refs/heads/*` alone, so the refs never
reach a checkout.

**Writes are compare-and-swap** (`src/shipmill/claims.py`, a new module, through
`src/shipmill/github.py`):

- **Take a free number:** create the ref (`POST repos/<repo>/git/refs`) pointing to a claim
  commit with no parent. GitHub refuses a ref that exists (422), so of two writers on the same
  tick exactly one takes it
- **Renew, take over a lapsed claim, or release:** write a new claim commit whose parent is the
  claim commit read, and move the ref to it without force (`PATCH repos/<repo>/git/refs/...`,
  `force: false`). GitHub refuses a move that isn't a fast-forward (422), so a writer that read
  a claim another writer has since replaced loses
- A writer may renew or release only a claim whose holder is its own; it may take over only a
  lapsed one. A **release** writes `until` as the time of the write, so the claim lapses at once
  and no ref is deleted (a delete can't be made conditional)
- A 422 on a create or a move reads as **taken**, never as an error. Any other failure fails the
  command or the tick as a failed read does (S-008-11)

**The read** is one GraphQL query (`src/shipmill/github.py`): `refs(refPrefix:
"refs/shipmill/claims/", first: 100)` with each target commit's `oid` and `message`, paged past
100. A message that isn't the three lines above is no claim (it holds nothing) and is named in
`shipmill claim --list`'s output as `unreadable`.

**Probed before the build.** That GitHub's REST API creates and fast-forwards a ref under
`refs/shipmill/` as the App, refuses a non-fast-forward move with 422, and that GraphQL's
`refs` lists that prefix, is read from GitHub's documentation, not yet seen on a repo. The first
build issue runs these four calls on a scratch repo as the App and records the result on its
pull request; a refusal stops the build and goes back to the spec as a decision.

### The lease

A new `[agents]` key, `claim_minutes` (`src/shipmill/agents.py`), an integer from 15 to 1440,
defaults to 60: the length of a lease. It must outlast the gate's tick interval, since the gate
renews on its ticks; `shipmill doctor` warns when it is not more than the launchd job's
`--every`.

### The gate claims before it launches, and honours other claims

- **The walk** (`src/shipmill/gate.py`, `src/shipmill/walk.py`): when a walk meets an item with
  subjects (tier 3, 4, or 6, spec 061), it reads the claims once for the walk. A subject with a
  live claim whose holder is not one of this gate's running sessions is **taken**, as a handed
  subject is: the item is cut to its subjects not taken, and an item whose every subject is
  taken is no item. A walk that meets no item with subjects reads no claims. An UNCHANGED tick
  whose first taken item was taken by a claim reads `every item was taken; the first, <kind>
  #<N>, is claimed by <holder> until <time>`
- **Before the launch:** after the preflights and the hand-off re-read (S-061-12), the gate
  claims each subject of the cut item with the holder `gate <session id>` (the id it will start
  the session with) and `until` now plus `claim_minutes`. A subject whose claim write reads
  taken is cut from the item; when none is left, the tick starts no session and writes no
  `cursor.json` or `handed.json`, and decides QUIET, `#<N> claimed by another holder meanwhile;
  the next tick walks again`. A dry run reads the claims and writes none
- **The session's env** carries `SHIPMILL_CLAIM_HOLDER=gate <session id>`, so the session's own
  `shipmill claim` renews the gate's claim instead of reading it taken
- **Renewal:** a tick that finds its session still working (spec 046's still-working check)
  renews each of that session's live claims whose `until` is less than half of `claim_minutes`
  away. A renewal is a ref move: no comment, no label, no notification
- **Release:** the tick that records the session's end in `handed.json` (spec 089) releases
  its claims. A gate whose host stops renews nothing, and its claims lapse within
  `claim_minutes`
- **Lapse is a change:** `cursor.json` records `claims_until`, the earliest `until` among the
  claims the walk read as taken by another holder. A tick at or after it counts as a change
  (S-046-2) and walks, so a lapsed claim's subject is handed on the first tick after it lapses.
  Deleted, `cursor.json` is missing, which is a change already (N-2: it stays a cache)

`handed.json` is unchanged: it records the gate's own hands, and a claim is never read from
it.

### `shipmill claim`, for a session started by hand

A new command (`src/shipmill/cli.py`):

- `shipmill claim <N>`: claims `#N` for `claim_minutes` (or `--minutes M`, 15 to 1440) and
  prints `claimed #<N> until <time> as <holder>`, exit 0. With no `--holder` and no
  `SHIPMILL_CLAIM_HOLDER` in the environment, it takes a new holder id and prints it. With a
  live claim held by another holder it writes nothing, prints `#<N> claimed by <holder> until
  <time>`, and exits 1
- `shipmill claim <N> --holder <id>` (or the environment's `SHIPMILL_CLAIM_HOLDER`): renews that
  holder's live claim, or takes `#N` when it is free or lapsed, exit 0; exits 1 as above when
  another holder's claim is live
- `shipmill claim <N> --release --holder <id>`: releases that holder's claim, exit 0; exits 1
  when the live claim is another holder's, and 0 with `#<N> not claimed` when there is none
- `shipmill claim --list`: prints each live claim as `#<N> <holder> until <time>`, and each
  unreadable one, oldest `until` first; `--json` prints them as a list of objects
- `--repo owner/name` as the other commands take it; it writes as the App where `[agents]
  app_id` is set, else as `[agents] identity` says, as `shipmill gh` does (D-14, D-54), and
  exits 2 on a malformed `N` or `--minutes`, a failed read, or a write refused with anything but
  422

### The skills claim before they work

- `skills/github-issue-resolve/SKILL.md`: before any code, `shipmill claim <N>` through the CLI
  the plugin pins; exit 1 stops the session on that issue with the holder named in its report,
  and no comment. It renews with `--holder` before each push, and releases once the pull
  request is open (IN_PROGRESS covers the issue from then on) or when it ends without one
- `skills/github-issue-triage/SKILL.md` and
  `skills/github-issue-triage/references/implementer-brief.md`: an implementer is dispatched
  only for an issue its `shipmill claim` took; an issue another holder claims is listed as
  claimed in the pass's report, not dispatched
- `skills/shipmill-setup/SKILL.md` (The gate) and `docs/install.md` (the `[agents]` keys):
  `claim_minutes`, and that two gates or a gate and a hand-started session on one repo share
  the claims

## Acceptance criteria

- S-102-1: `claims.py` takes a free number by creating `refs/shipmill/claims/<N>` at a parentless claim commit whose message is the three lines `shipmill claim #<N>`, `holder: <holder>`, `until: <YYYY-MM-DDTHH:MMZ>`, and renews, takes over, or releases by moving the ref without force to a claim commit whose parent is the one read
- S-102-2: a 422 on the create or the move reads as taken and writes nothing more; any other failed write raises naming the ref
- S-102-3: of two gates that walk the same tick with the same free issue `#N`, both reading no claim, exactly one starts a session: the second's create of `refs/shipmill/claims/<N>` gets 422, its item is cut to nothing, and it decides QUIET `#<N> claimed by another holder meanwhile; the next tick walks again` with no `cursor.json` or `handed.json` written
- S-102-4: a walk that reads a live claim on `#N` held by a holder other than its running sessions treats `#N` as taken: the item is cut to its other subjects, an item with no other subject is no item, and with no other item the tick reads UNCHANGED `every item was taken; the first, <kind> #<N>, is claimed by <holder> until <time>`
- S-102-5: a claim written by `shipmill claim <N>` (a hand-started session) keeps the gate from handing `#N` while it is live, as S-102-4 says
- S-102-6: a claim whose `until` has passed holds nothing: the walk hands its subject, and the gate's create-or-move takes it over with a commit parented on the lapsed one
- S-102-7: `cursor.json` records `claims_until`, the earliest `until` of the claims a walk read as taken; a tick at or after it counts as a change and walks, and a tick before it with nothing else new stays QUIET
- S-102-8: a LAUNCH claims each subject of its cut item with holder `gate <session id>` and `until` now plus `claim_minutes` before it starts the session, and the session's env carries `SHIPMILL_CLAIM_HOLDER` with that holder; a dry run writes no claim
- S-102-9: a tick that finds its session still working renews each of its live claims less than half of `claim_minutes` from its `until`, and none further out; the tick that records the session's end releases its claims by a move whose `until` is the time of the write
- S-102-10: a walk that meets no item with subjects runs no claims query, and the claims read is one GraphQL query per 100 claims
- S-102-11: `shipmill claim <N>` exits 0 and prints `claimed #<N> until <time> as <holder>` on a free or lapsed number; exits 1 printing `#<N> claimed by <holder> until <time>` with no write on another holder's live claim; and with `--holder` or `SHIPMILL_CLAIM_HOLDER` naming the live claim's own holder renews it, exit 0
- S-102-12: `shipmill claim <N> --release --holder <id>` releases that holder's claim (exit 0), exits 1 on another holder's live claim, and exits 0 printing `#<N> not claimed` when there is none
- S-102-13: `shipmill claim --list` prints the live claims as `#<N> <holder> until <time>`, oldest `until` first, leaves lapsed ones out, names a claim commit whose message isn't the three lines as `unreadable`, and `--json` prints the same as a list
- S-102-14: `shipmill claim` exits 2 on a malformed number, a `--minutes` outside 15 to 1440, or `--release` without a holder, before any write
- S-102-15: `[agents] claim_minutes` defaults to 60 and the config refuses a value that isn't an integer from 15 to 1440; `shipmill doctor` warns when it isn't more than the launchd job's interval
- S-102-16: a claim's create, renewal, take-over, and release call only `git/commits` and `git/refs` endpoints and no issue, comment, label, or pull request endpoint, and a subject whose only writes since its hand are its claim's still reads idle under S-061-4
- S-102-17: `skills/github-issue-resolve/SKILL.md`, `skills/github-issue-triage/SKILL.md`, `skills/github-issue-triage/references/implementer-brief.md`, `skills/shipmill-setup/SKILL.md`, and `docs/install.md` say what "The skills claim before they work" says

## Out of scope

- **An assignee or an `in-progress` label with a lease:** a label holds no time, so the lease
  would live in a comment, and a renewal is then a comment (a notification each) or an edit,
  which moves the issue's `updatedAt` and makes every claimed subject read as written on under
  spec 061, undoing its idle saving. A label add and remove is no compare-and-swap either: two
  gates that read no label both add it. An assignee notifies the person assigned, and the App's
  bot can't be one
- **An early draft pull request as the claim:** D-67 and hard rule 7 forbid an agent parking a
  pull request as a draft, it puts an empty pull request on the repo for every item, including
  ones the session ends up postponing, and it notifies the repo's watchers each time
- **A lock only the gates read** (one gate per repo at install, or a file only gates take):
  it leaves out the session started by hand, the second case of #1511. The refs here are that
  lock, taken by the skills through `shipmill claim` as well
- **`triage_state.py` reading claims:** the skill scripts stay Python 3.10 with no
  dependencies and read issues, not refs; the skills ask `shipmill claim` before they dispatch
  instead. A CLAIMED triage state is a follow-up if a report needs it
- **`shipmill status --item` and the watch report naming a claim:** `shipmill claim --list`
  shows them; adding them to spec 088's and spec 094's records is a follow-up
- **Deleting lapsed refs:** a lapsed claim holds nothing and the next claimer replaces it, so
  at most one ref per number stays; a prune of refs for closed items is its own change
- **A claim across repos of a product** (spec 038): each repo's claims are its own
- **Clock skew** between writers beyond a minute: a lease of at least 15 minutes absorbs it

## Decisions relied on

- D-4: the one setting, `[agents] claim_minutes`, lives in `.github/shipmill.toml`
- D-14: the gate and `shipmill claim` write as the App where `app_id` is set
- D-16: a claim is honoured from any writer with push access, which is trusted by construction
- D-54: shipmill writes to GitHub only as the App, or as the identity the repo chose
- D-58: a tick checks for change first; a lapsed claim the last walk skipped is one more change
- D-67: no agent parks a pull request as a draft, which rules the early draft out as the claim
- D-87: `handed.json` stays a cache of the gate's own launches, and the deciding fact, the
  claim, is read from GitHub
- D-100: the gate records how a handed session ended, and that tick releases its claims
- D-111: an idle subject waits until it changes; a claim write changes nothing an idle reading
  reads

## Issues

- shipmill/shipmill#1701: S-102-1, S-102-2, S-102-16
- shipmill/shipmill#1702: S-102-11, S-102-12, S-102-13, S-102-14, S-102-15
- shipmill/shipmill#1703: S-102-3, S-102-4, S-102-5, S-102-6, S-102-7, S-102-8, S-102-9, S-102-10
- shipmill/shipmill#1704: S-102-17

## Verification
