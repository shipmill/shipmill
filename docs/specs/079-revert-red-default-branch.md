# S-079: A merge that turns the default branch red is backed out without a person

status: approved
serves: G-2

## Problem

A default branch can go red after a merge the gate judged green: two green pull requests
that conflict in behaviour, a check that runs only on the default branch, a flaky test.
shipmill then stops every landing but the pull request whose `Repairs:` line names the
failed run (D-75), and does nothing else: no row of the watch names a red default branch,
the gate's change check doesn't see a check finish there, and nobody looks for the merge
that broke it. Landing waits until a person finds that merge and repairs it by hand (#1209,
grouped into #1230, which the maintainer accepted on 2026-11-18).

It hits maintainers whose agents merge often: one red head holds every other pull request,
and the hold grows with the share of merges no person watches. Prior art: Anthropic's post
on source control at agent volume, which merges, tests after the merge, and backs a failing
change out by an automated bisect and revert.

This spec builds on D-75 and changes none of it: the revert is the pull request that
repairs the default branch, and it lands through the same gate as any other.

## Behaviour

### The key

`[autonomy]` in `.github/shipmill.toml` (D-4) gains one key, `revert`, parsed in
`src/shipmill/autonomy.py` with the levels and the error shape of its other keys, and read
from the default branch, never from a pull request:

```toml
[autonomy]
revert = "act"   # observe (default) | propose | act
```

| Level | What shipmill does on a red default branch |
|---|---|
| `observe` | reports it (the BASE_RED row below); landing waits as today (D-75) |
| `propose` | re-runs the failed run once, finds the merge, opens the revert pull request, and reopens the issues; a person merges it |
| `act` | the same, and the revert pull request lands through `pr_gate.py` like any other, bounded by `[autonomy] land` |

A config without the key reads `observe`, so no repo changes behaviour by upgrading (D-63).
An open `shipmill-hold` issue reads `act` as `propose`, as for every stage (D-15).
`shipmill autonomy` and `shipmill doctor` print the level beside the other stages'. `revert`
is not a zone of `[decisions]`: the revert pull request's own zones decide it, as below.

### Reading a red default branch

A new script, `skills/github-pr-triage/scripts/base_red.py <owner/repo> [--branch B]
[--bot-login L] [--limit K] [--json]`, reads the default branch (or `--branch`) from GitHub
only (D-6). Its first line is `<STATE> <branch>@<sha7>`:

- **GREEN**: no completed check on the head failed, by `pr_gate.py`'s reading of the base
  (D-75): the newest run per check, and a queued, running, cancelled, skipped, neutral, or
  stale one is not red
- **RERUN_DUE**: a failed check is an Actions job whose workflow run is on its first attempt.
  A line `rerun: <run URL>` names each such run. A flaky test and a failure outside the code
  clear here, as D-75 says, before any merge is blamed
- **CULPRIT**, **CANDIDATES**: every failed check was re-run, or can't be (a commit status).
  For each failed check the script walks the branch's first-parent history back from the
  head, at most `--limit` commits (default 30, at least 2), reading that check's newest run on
  each commit. The **last green** is the newest commit where it completed green; the **first
  red** is the oldest commit after the last green where it failed. The candidates are the
  commits after the last green up to and including the first red: the first red itself, and
  the commits before it on which the check never completed (**unjudged**). The states' lines
  are the union over the failed checks; one candidate is CULPRIT, several are CANDIDATES
- **NO_GREEN**: a failed check completed green on none of the `--limit` commits

Each candidate prints one line, oldest first: `candidate: <sha7> #N` (the merged pull request
the commit came from, or `no pull request` for a direct push or a release commit), then
`revertable` or `not revertable: <reason>`, then `unjudged, rerun: <run URL>` for an unjudged
commit with a cancelled run of the check's workflow, or `unjudged` for one with no run. A
candidate is revertable only when it is a pull request's merge that the `--bot-login` merged
(a gate merge) and no tag contains its commit; the reasons are `no pull request`, `merged by
a person`, and `released in <tag>`.

Two lines follow when they apply: `repair: #R` for each open pull request whose body has a
`Repairs:` line naming a failed run of the head (`pr_gate.py`'s `repaired`), and `asked: #Q`
for the open issue the `--bot-login` filed whose first line is
`<!-- shipmill:base-red <branch> -->`. `--json` prints one object with `state`, `branch`,
`sha`, `failed` (each check's name and run URL), `rerun`, `candidates`, `repair`, and
`asked`. A read that fails, a `--limit` below 2, or a branch the repo doesn't have exits 2,
never a partial reading (Q-1). The lines name numbers, SHAs, logins, and URLs only, never a
title or a body (D-16).

### The watch and the gate

`skills/github-ship-watch/scripts/watch_state.py` gains a row, `BASE_RED <branch>@<sha7>`,
whenever `base_red.py` reads anything but GREEN, its detail the state in words and the
numbers it names: `rerun due`, `culprit #N`, `candidates #A #B`, `no green in the last K
commits`, then `repair open: #R` or `asked in #Q` when the reading has that line. A GREEN
reading gives no row, save `BASE_RED <branch>@<sha7>: green again, close #Q` while the
question issue is still open. Every BASE_RED row carries a fix (spec 011).

The row needs an agent (`agent: true`) only when the default branch's `[autonomy] revert` is
`propose` or `act` and the reading has neither a `repair:` nor an `asked:` line, or is the
`green again` row. With a repair open, the pull request is tier 3's to land; with a question
asked, its answer is tier 4's. The gate reads the row in tier 2, first in that tier
(`TIERS` in `watch_state.py`, `src/shipmill/walk.py`), handed like any tier 2 item with the
subject `<branch>@<sha7>`.

So that a check finishing on the default branch is a change the gate sees, the change
check's one GraphQL query (`src/shipmill/github.py`) also reads the default head's check
rollup state, and the signature holds it. A tick reads `base_red.py` only when that state is
a failure or the last reading wasn't GREEN.

### What the session does

A session handed BASE_RED follows `skills/github-pr-triage/references/ci-failures.md` (A red
default branch), which gains these steps for a level of `propose` or `act`, every write
through `shipmill gh` (D-54):

1. **RERUN_DUE**: re-run each named run once, `shipmill gh run rerun <id> --failed`, and
   leave; the next reading judges the second attempt
2. **CANDIDATES with a run to re-run**: re-run every `unjudged, rerun:` run, and leave; the
   next reading has fewer candidates
3. **CULPRIT**, or **CANDIDATES** with no run left to re-run and at most three candidates,
   every one revertable: `shipmill revert open <PR>... --run <failed run URL>`, below
4. **Anything else** (a candidate that is not revertable, more than three candidates,
   NO_GREEN, a `revert open` that exits 2 on a conflict, or a revert pull request whose own
   head fails the check it repairs): no revert. The session closes such a revert pull
   request and asks the maintainer with the needs-decision protocol (D-21) on one issue it
   files as the App, its first line `<!-- shipmill:base-red <branch> -->`, naming the failed
   run, the candidates, and why none was reverted. One such issue is open per branch at a
   time; the session that reads `green again` closes it with a comment naming the head

The reviewer of the revert pull request checks its `Repairs:` claim, as D-75 says, and its
review is recorded like any other (spec 055).

### `shipmill revert open`

`shipmill revert open <PR>... --run <URL>` (`src/shipmill/revert.py`, wired in
`src/shipmill/cli.py` beside `spec open`) opens the revert of one or more merged pull
requests, from the repo's checkout. It checks first and writes nothing when a check fails,
exiting 2 with the reason (Q-1):

- the default branch's `[autonomy] revert` is `propose` or `act`
- the App is available (D-54)
- `--run` names a failed completed check on the default branch's head, by `pr_gate.py`'s
  `repaired`
- each `<PR>` is revertable by `base_red.py`'s rule: merged into the default branch by the
  App's bot, its merge commit on the branch's first-parent history, and in no tag
- no open pull request already has a `Repairs:` line naming that run
- the reverts apply: on a branch `revert/<N>-<sha7>` (the oldest reverted pull request and
  the red head) cut from `origin/<default>`, it reverts each merge commit, newest first, one
  commit per pull request (`git revert`, with `-m 1` for a two-parent merge). A conflict
  aborts, names the conflicting files, and pushes nothing

Then it pushes the branch and opens the pull request as the App, labelled `revert` (created
when the repo lacks it; `skills/shipmill-setup/scripts/setup_state.py` lists it in
`LABELS_MISSING` once `revert` isn't `observe`), with:

- the title `Revert "<title>"` for one pull request, the title GitHub's Revert button
  writes, or `Revert #A, #B` for several
- a body holding one `Reverts #N` line per pull request (the line spec 058's retro and spec
  073's history read), the line `Repairs: <URL>` (D-75), and a `## Plan` section: `Serves:`
  the ids of the reverted pull requests' own `Serves:` lines, or `quality bar` when none has
  one; `Files:` the reverted files; `Order:` this pull request first, then each reopened
  issue's fix again; `Proof:` the failed check, named, green on this pull request's head
- no changelog entry of its own: reverting an unreleased change removes its fragment or
  Unreleased line with it

Then, for each reverted pull request, it reopens every issue that pull request closed as
completed (`closingIssuesReferences`, in this repo), with one comment per issue:

```markdown
<!-- shipmill:reverted #N by #R -->
Reopened: #N, which closed this, is being reverted in #R. `<check>` failed on <branch>@<sha7> after it merged: <failed run URL>
```

An issue already open, or already carrying that marker for #R, is left as it is, so a second
run writes nothing twice. It prints the pull request's URL and each reopened issue.

### The gate and triage read the revert

- `skills/github-pr-triage/scripts/pr_gate.py`: a pull request the `--bot-login` authored
  whose body has both a `Reverts #N` and a `Repairs:` line, and that would read READY, reads
  BLOCKED with `  revert: [autonomy] revert is propose; a person merges it` while the default
  branch's level is `propose` (or `act` under a hold). At `act` it is judged as any pull
  request: the `Repairs:` line passes the red base (D-75), a review record covers its head
  (spec 055), and its zones apply (spec 030), so a revert that touches an `ask` zone, such as
  `.github/**`, waits for the maintainer's answer
- `skills/github-issue-triage/scripts/triage_state.py`: an open issue carrying the
  `--bot-login`'s `<!-- shipmill:reverted #N by #R -->` comment no longer counts #N as a merged
  pull request that closes it. While #R is open it reads BLOCKED, `revert #R of #N open`; once
  #R merged it reads as its other state (NEEDS_PR for a triaged implement), with `#N:reverted`
  in its note, so the fix is built again; once #R closed without merging, #N counts again and
  the issue reads DONE_NOT_CLOSED. A marker by anyone but the `--bot-login` counts for nothing

`skills/github-ship-watch/SKILL.md` lists the BASE_RED row and its fix, and
`skills/github-pr-triage/references/landing.md` and `skills/shipmill-setup/SKILL.md` name the
key where they describe a red default branch and the autonomy levels.

Touched areas: `src/shipmill/autonomy.py` (`[autonomy] revert`), `src/shipmill/revert.py`,
`src/shipmill/cli.py` (`revert open`), `src/shipmill/github.py`, `src/shipmill/walk.py`,
`src/shipmill/doctor.py`, `skills/github-pr-triage/scripts/base_red.py`,
`skills/github-pr-triage/scripts/pr_gate.py`,
`skills/github-pr-triage/references/ci-failures.md`,
`skills/github-pr-triage/references/landing.md`,
`skills/github-ship-watch/scripts/watch_state.py`, `skills/github-ship-watch/SKILL.md`,
`skills/github-issue-triage/scripts/triage_state.py`,
`skills/shipmill-setup/scripts/setup_state.py`, `skills/shipmill-setup/SKILL.md`, landing,
and `tests/test_base_red.py`, `tests/test_revert.py`.

## Acceptance criteria

- S-079-1: a config with no `[autonomy] revert` reads `observe`; `observe`, `propose`, and `act` parse, any other value exits 2 naming the key and the three levels; `shipmill autonomy` prints the level, and prints `propose` for a configured `act` while a `shipmill-hold` issue is open
- S-079-2: `base_red.py` prints `GREEN <branch>@<sha7>` when no completed check on the head failed, counting a queued, running, cancelled, skipped, neutral, or stale check as not red, and `RERUN_DUE` with a `rerun: <run URL>` line for a failed Actions job whose workflow run is on attempt 1
- S-079-3: for a check that failed on its second attempt at the head, passed at commit A, and failed first at commit B, `base_red.py` prints `CULPRIT` with B as its one candidate when B directly follows A, and `CANDIDATES` listing B and each commit between A and B on which the check never completed, oldest first; a commit after B is not a candidate, and a check green on none of the `--limit` commits prints `NO_GREEN`
- S-079-4: a candidate line names its merged pull request and reads `revertable` only when the `--bot-login` merged it and no tag contains its commit; it reads `not revertable: no pull request` for a direct push, `not revertable: merged by a person` for a merge by anyone else, and `not revertable: released in <tag>` for a tagged commit; an unjudged candidate with a cancelled run of the check's workflow carries `unjudged, rerun: <run URL>`
- S-079-5: `base_red.py` prints `repair: #R` for an open pull request whose `Repairs:` line names a failed run of the head, and `asked: #Q` for an open issue by the `--bot-login` whose first line is `<!-- shipmill:base-red <branch> -->`; `--json` prints one object with `state`, `branch`, `sha`, `failed`, `rerun`, `candidates`, `repair`, and `asked`; a failed read, a `--limit` below 2, or an unknown branch exits 2 with no reading
- S-079-6: `watch_state.py` prints a `BASE_RED <branch>@<sha7>` row with a fix for every reading but GREEN, and `green again, close #Q` for a GREEN reading with the question issue open; the row is `agent: true` only when the default branch's `[autonomy] revert` is `propose` or `act` and the reading has no `repair:` and no `asked:` line, or is the `green again` row; under `observe` it is never an agent row
- S-079-7: `watch_state.py --tier 2` lists BASE_RED before BOT_FAILED, and the gate's change check reads the default head's check rollup state in its one GraphQL query and counts a change of it as a change, so a tick after a check fails on an unchanged head walks the tiers instead of deciding QUIET
- S-079-8: `shipmill revert open` exits 2 and writes nothing (no branch pushed, no pull request, no issue reopened) when `[autonomy] revert` on the default branch is `observe`, the App isn't available, `--run` names no failed completed check on the default head, a named pull request isn't merged, was merged by anyone but the App's bot, or sits in a tag, or an open pull request already has a `Repairs:` line naming the run
- S-079-9: `shipmill revert open <A> <B> --run <URL>` pushes `revert/<A>-<sha7>` cut from `origin/<default>` holding one revert commit per pull request, newest first, whose tree equals the default head's with both changes undone; a revert that conflicts exits 2 naming the conflicting files and pushes nothing
- S-079-10: the pull request `revert open` opens is authored by the App, labelled `revert`, titled `Revert "<title>"` for one pull request and `Revert #A, #B` for several, and its body holds a `Reverts #N` line per pull request, the line `Repairs: <URL>`, and a `## Plan` section `pr_gate.py`'s `plan_problems` accepts, its `Serves:` the reverted pull requests' own ids or `quality bar`
- S-079-11: `revert open` reopens each issue a reverted pull request closed as completed and comments on it once, its first line `<!-- shipmill:reverted #N by #R -->` and its text naming the failed check and the run's URL; an issue already open, or already carrying that marker for #R, gets no second comment
- S-079-12: `pr_gate.py` reads an otherwise READY pull request the `--bot-login` authored whose body has a `Reverts #N` and a `Repairs:` line as BLOCKED with a `revert:` line naming the level while the default branch's `[autonomy] revert` is `propose`, and as READY at `act`; at `act` the same pull request without a review record of its head still reads UNREVIEWED, and one in an `ask` zone still reads its needs-decision verdict
- S-079-13: `triage_state.py` reads an open issue carrying the `--bot-login`'s `<!-- shipmill:reverted #N by #R -->` comment as BLOCKED naming #R while #R is open, as NEEDS_PR with `#N:reverted` in its note once #R merged (for an issue whose triage verdict is implement), and as DONE_NOT_CLOSED once #R closed without merging; the same marker in a comment by any other author changes nothing
- S-079-14: `ci-failures.md`'s "A red default branch" holds the four steps (re-run once, re-run the unjudged candidates' cancelled runs, `revert open` for a culprit or at most three revertable candidates, otherwise ask on one `<!-- shipmill:base-red <branch> -->` issue per branch and close it when the branch reads green), and `skills/github-ship-watch/SKILL.md` lists the BASE_RED row with its fix

## Out of scope

- Approval tiers by change type (part 2 of #1209): a level for part of a zone, by path, shipped as spec 057; routing by diff kind (docs-only, a dependency bump) can be its own request
- Reverting a merge a person made, a direct push, or a change a tag already holds: the session asks instead. A released change is fixed forward, as a veto of a landed decision is (spec 030)
- Running a check on a commit that never had a run of it (a bisect on shipmill's own compute): the reading uses the runs the forge holds and re-runs cancelled ones (N-2)
- A looser gate for the revert pull request: it needs its review record, its plan, and its zones like any pull request, so a revert in an `ask` zone waits for the maintainer
- Rolling back a deploy the red merge reached: `[autonomy] rollback` and `shipmill operate` own that (D-31, N-1)
- Counting automatic reverts in `metrics.py`'s change failure rate: the retro already counts a reverted decision (spec 058), and a measure of reverts per merge can be its own request
- A red branch other than the default one (a release branch of a hotfix lane): `--branch` reads it by hand, and no row or session follows it

## Decisions relied on

- D-4
- D-6
- D-15
- D-16
- D-21
- D-48
- D-54
- D-58
- D-63
- D-75

## Issues

- shipmill/shipmill#1287: S-079-1, S-079-12
- shipmill/shipmill#1288: S-079-2, S-079-3, S-079-4, S-079-5
- shipmill/shipmill#1290: S-079-13
- shipmill/shipmill#1292: S-079-6, S-079-7
- shipmill/shipmill#1294: S-079-8, S-079-9, S-079-10, S-079-11
- shipmill/shipmill#1296: S-079-14

## Verification
