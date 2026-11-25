# S-086: See which stuck or blocked work holds the most back

status: built
serves: G-1, G-4

## Problem

The maintainer can't see which open item holds back the most work, which chains of work have
stalled, or what stands between a milestone and its release (shipmill/shipmill#1342). What
exists covers the links, not their weight:

- Spec 017 holds an item until what it waits on closes (`Depends on` lines, `blockedBy`,
  sub-issues, across repos), spec 041 reports cycles, and spec 042 closes a parent once its
  check holds; none says how much waits behind an item
- The gate's walk takes a tier's rows in a fixed order (S-046-12); spec 070 puts expedite
  outcomes first, but only for an outcome the maintainer has already marked
- Spec 069's queue of what waits on the maintainer is ordered oldest first, so a decision that
  unblocks ten items sits behind an older one that unblocks none
- Nothing reports an item that others wait on and that hasn't moved for days; it is found by
  hand
- A milestone is done when its specs are built (spec 022), but nothing lists the open items on
  its path to release, or which of them wait on the maintainer

Measured on 2026-11-19 across the maintainer's 18 gated repositories, from the forge: of 522
open issues, 180 (35%) are blocked by a native relation or a `Depends on` line. 203 open
issues block at least one other; of the 127 at the head of a chain, 68 wait on the agent queue
with nothing holding them, 51 on a person, 4 on a `needs-decision` question, and 4 are
postponed. The widest heads hold 11, 10 and 8 issues transitively, and 33 heads have had no
event for 7 days or more, one of them an agent-queue issue idle 19 days holding 5. More than
half the heads are agent work that nothing stops, yet the walk takes them in tier order with
no knowledge of what waits behind them.

The maintainer accepted the opportunity on 2026-11-19 for G-1 and G-4. Everything here is a
read model computed from issues, relations, labels and timelines on each read, with no state
of its own (N-2) and no visual map (N-4).

## Behaviour

### What an item holds: `chains.py show --json`

`skills/github-issue-triage/scripts/chains.py`'s walk (spec 017) already reads every item a
chain holds, up through its holds and down through what GitHub records waiting on it
(`blocking`, `parent`). Its item query gains each issue's `milestone { title }`, `updatedAt`,
and the open pull requests that close it (`closedByPullRequestsReferences`, their
`updatedAt`), and each row of `show --json` gains five fields, computed from the items read:

- `held`: how many distinct open issues wait on the item, directly or through others. An open
  issue X counts for H when a path of open holds (as `holds` reads them: a `Depends on` line,
  `blockedBy`, a sub-issue) leads from X to H. H itself never counts, so a cycle adds nothing
  to its own members. Only an issue whose holds the walk read counts: an UNTRUSTED item (D-16)
  or an UNREADABLE one waits on nothing here, so an outsider's `Depends on` line can't raise
  an item's count. A closed issue counts for nothing
- `held_direct`: how many of those name it among their own open holds
- `milestones`: the milestones of the issues counted in `held`, each `owner/repo title`,
  sorted, each once
- `waiting_for`: what the item itself waits for, the first that applies: `decision` (labelled
  `needs-decision`), `cycle` (on a cycle, spec 041), `items` (an open hold), `upstream`
  (labelled `upstream`), `postponed` (labelled `postponed`), `maintainer` (a person's item
  labelled `human` or `role:maintainer`), `person` (any other person's item, spec 036),
  `pull request` (an open pull request closes it), `no gate` (show's NO_GATE), else `agent`.
  An open pull request reads `pull request`, an UNTRUSTED item `untrusted`, an UNREADABLE one
  `unreadable`, and a closed item `null`
- `idle_days`: whole days since the newest of the issue's `updatedAt` and the `updatedAt` of
  each open pull request that closes it; `null` for an item that isn't an open issue

A **head** is an open issue with `held` of 1 or more whose `waiting_for` is neither `items`
nor `cycle`: the item a chain waits on first. Show's table lines, its exit codes, and its
other JSON fields are unchanged.

### Three views of the same walk

Each runs one walk, takes show's `--trusted-only` and `--bot-login`, writes nothing on GitHub,
and exits 2 on what show exits 2 on. Each also takes `--repo OWNER/NAME` (repeatable), which
adds every open issue of that repo as a start, read in pages of 100, beside any references.

- **`chains.py impact <owner/repo#N>... [--repo OWNER/NAME]... [--json]`** prints the items
  with `held` of 1 or more, most held first, then `held_direct`, then the reference: one line
  each, `<ref> holds <held> (<held_direct> directly), waits for <waiting_for>, idle <d>d`, then
  ` milestones: <list>` when it has any, then the title. `--json` prints `{"rows": [...]}`
  with show's row fields, in that order. Exit 0
- **`chains.py stalled ... [--days N]`** prints the heads whose `idle_days` is N or more
  (default 7; a value below 1 exits 2), most held first, then the longest idle, in impact's
  line and JSON shapes. Exit 1 when it prints a row, else 0
- **`chains.py path --repo OWNER/NAME --milestone TITLE [--json]`** prints a milestone's path
  to release: every open issue in the open milestone of that exact title, and every open item
  they wait on, recursively, each once. The items that wait on the maintainer come first
  (`decision`, then `maintainer`), then the rest by `held` counted within the path, most
  first, then the reference. Each line is the reference, its `waiting_for`, how many items of
  the path wait on it, its idle days, and its title; `--json` prints `{"milestone": TITLE,
  "rows": [...]}`. A repo with no open milestone of that title exits 2, `error: no open
  milestone "<TITLE>" in OWNER/NAME`; one with nothing open prints `milestone <TITLE>:
  nothing open` and exits 0. It needs exactly one `--repo` and no references (exit 2 else)

### The watch reports a stalled chain

`skills/github-ship-watch/scripts/watch_state.py` reads the new fields from the `chains.py
show --json --trusted-only` run it already makes over the repo's open issues (`chain_rows`),
so no second walk:

- **`CHAIN_STALLED`**, in the full report only (never under `--tier` or `--sweep`): one row
  per head whose `idle_days` is 7 or more, its subject the head's reference, its detail
  `holds K open issue(s), no event for D day(s), waits for <waiting_for>`, its fix `see its
  chain: uv run --no-project python <chains.py> show <ref>`, built from the checked reference
  and numbers alone (D-16). It is report-only, never an agent's row. A walk that fails is the
  existing CHAIN_UNREADABLE row, as today
- **`shipmill status`** (`src/shipmill/status.py`) lists the CHAIN_STALLED rows on a line of
  their own, `stalled chains:`, each as its subject and detail, and they change no verdict

### The walk takes what holds the most first

- **Impact on the rows.** When `watch_state.py` reads tier 4 or tier 6 (`--tier 4`, `--tier
  6`), and in the full report, it runs that same `chains.py show` walk over the repo's open
  issues and gives each `ISSUES` row an `impact` field: `[number, held]` for each of its
  subjects with `held` of 1 or more, most held first, then the number; `[]` for none. A walk
  that fails under a tier read adds the CHAIN_UNREADABLE row (report-only) and leaves every
  row's `impact` empty, so the tier is ordered as before and the tick goes on
- **The finding.** `src/shipmill/findings.py`'s `Finding` gains `impact`, a tuple of
  `(number, held)` pairs, `()` by default and for a `watch_state.py` that prints none; a
  malformed field (not a list of pairs of positive whole numbers) fails the read. `impact`
  never joins the fingerprint (`fingerprint`, `src/shipmill/walk.py`'s `item_key`), so an item
  whose counts change is still the item that was handed (S-046-13, D-87)
- **The order.** `src/shipmill/walk.py`'s `order` sorts the rows of tiers 4 and 6 by their
  highest `held`, most first, before S-046-12's key (the kind's place, then the subject); a
  row with no impact reads 0. Spec 070's expedite rows (S-070-4) still come before every
  standard row of their tier, and impact orders within each of the two groups. Tiers keep
  their order, no tier is skipped, and the rows of other tiers keep S-046-12's order. With no
  link between open issues, every walk's order is the one it is today
- **Why it came first.** When the handed item has impact, the gate's LAUNCH reason
  (`src/shipmill/gate.py`, `walked_decision`) reads `<brief> needs an agent (tier N), first by
  impact: #<number> holds <held> open issue(s); read tiers ...`, naming the handed subject
  with the highest `held`, and the session's prompt (`prompt`) gains the line `#<number> holds
  <held> open issue(s) that wait on it: start with it.`, both built from the digits the gate
  parsed (D-16)

### The maintainer's queue by impact

`skills/github-ship-watch/scripts/fleet.py queue` gains `--order age|impact` (default `age`,
spec 069's oldest first, unchanged and with no new read). With `--order impact` it runs one
`chains.py impact --json --trusted-only [--bot-login LOGIN]` with a `--repo` for every repo of
the fleet file, after the repos' reads, so counts run across the fleet's repos. Each row gains
`holds`, its item's `held` (0 when the walk lists no row for it), and rows sort by `holds`,
most first, then by spec 069's order. The table line puts `holds K` before the wait, and
`--json`'s items gain `holds` and its object `order`. A walk that fails prints one
`IMPACT_ERROR` line with the error's first line after the queue, which then keeps spec 069's
order, and the run exits 2. `skills/github-ship-watch/SKILL.md`'s Fleet section documents
`--order impact`, and `skills/github-issue-triage/SKILL.md` documents `impact`, `stalled`, and
`path` beside `chains.py show`.

## Acceptance criteria

- S-086-1: `chains.py show --json` gives an item waited on by A directly and by B through A a `held` of 2 and a `held_direct` of 1, counts a waiter in another repo, counts nothing for an item's own cycle, and lists the waiters' milestones as `owner/repo title`, sorted, each once
- S-086-2: an UNTRUSTED or UNREADABLE issue, and a closed one, adds nothing to any item's `held` or `held_direct`, so an outsider's `Depends on` line leaves every count unchanged
- S-086-3: `waiting_for` reads each of `decision`, `cycle`, `items`, `upstream`, `postponed`, `maintainer`, `person`, `pull request`, `no gate`, and `agent` for an issue set up for it, the first that applies in that order, and `idle_days` is the whole days since the newer of the issue's `updatedAt` and its open closing pull request's
- S-086-4: `chains.py impact` prints only the items with `held` of 1 or more, most held first, then `held_direct`, then the reference, in the documented line and `--json` shapes, and exits 0; `--repo OWNER/NAME` reads every open issue of the repo past the first page of 100 as a start
- S-086-5: `chains.py stalled` prints the heads idle for 7 days or more, and with `--days 3` those idle for 3 or more, never an item whose `waiting_for` is `items` or `cycle`, and exits 1 with a row and 0 without; `--days 0` exits 2
- S-086-6: `chains.py path --repo R --milestone T` lists every open issue of the milestone and each open item they wait on, recursively and each once, with `decision` and then `maintainer` items first; a title no open milestone of R has exits 2 naming it, and a milestone with nothing open prints `milestone T: nothing open` and exits 0
- S-086-7: `impact`, `stalled`, and `path` run against a fake `gh` make only reads, with no mutation and no REST write
- S-086-8: `watch_state.py`'s full report gives a head idle 7 days or more one report-only `CHAIN_STALLED` row with the documented detail and fix, from the same single `chains.py show` run, and no row under `--tier` or `--sweep`; `shipmill status` lists it on its `stalled chains:` line with the same verdict as without it
- S-086-9: `watch_state.py --tier 6` gives each `ISSUES` row an `impact` list of its subjects with `held` of 1 or more, most held first, and a walk that fails gives a CHAIN_UNREADABLE row and empty `impact` lists while the tier's rows still print
- S-086-10: a `Finding` read with `impact` has the same fingerprint and `item_key` as the same row with another `impact` or none, and a malformed `impact` field fails the read
- S-086-11: `walk.order` puts a tier 6 row whose subject holds 3 before a row of an earlier kind holding 1, and that before one holding none; with every row's `impact` empty the order is S-046-12's, an expedite row (S-070-4) still comes before a standard row of higher impact, and tiers 1 to 3 still come before tier 4
- S-086-12: a LAUNCH of an item with impact names its handed subject of highest `held` and its count in the decision's reason and in the prompt's line, and a LAUNCH of an item without impact reads as today
- S-086-13: `fleet.py queue --order impact` sorts rows by `holds`, most first, then oldest first, prints `holds K` on each line and `holds` and `order` in `--json`, and runs one `chains.py impact` naming every fleet repo; without `--order` the output and the commands run are spec 069's; a failed walk prints `IMPACT_ERROR`, keeps the oldest-first order, and exits 2
- S-086-14: `skills/github-ship-watch/SKILL.md`'s Fleet section documents `--order impact`, and `skills/github-issue-triage/SKILL.md` documents `chains.py impact`, `stalled`, and `path`

## Out of scope

- A visual map or a dashboard of the chains: the views are text and JSON (N-4); a picture is a later request outside the core
- Holds read from a triage comment's hold sentence or a `blocked` label with no relation behind it: the counts use the links `chains.py` reads (`Depends on` lines, `blockedBy`, sub-issues), which a session writes with `chains.py link`; reading comments for them is a later spec
- A waiter in a repo no walk reads, linked only by a `Depends on` line there: GitHub doesn't record it on the item it waits on, so it is counted only when that repo is among the starts (`--repo`, the fleet's repos)
- Ordering tier 3 (pull requests to land) by impact: a pull request's weight needs the issues it closes, and landing is quick already; a later spec once this one is built
- Expediting by impact, or proposing a class of service: the maintainer still marks `expedite` (spec 070, N-3); these views only show which outcomes are worth marking
- A config key for the stall threshold: 7 days is fixed in the watch and `--days` sets it by hand
- Time held by a `Depends on` line as a stage metric (spec 066's later spec) and a milestone's specs not yet built (spec 022's MILESTONE_WAITING already names them)
- Telling the people who wait on a milestone (U-3) what holds it: the path is printed for the maintainer; any notice is a later request (D-69)

## Decisions relied on

- D-6
- D-16
- D-32
- D-55
- D-58
- D-87

## Issues

- shipmill/shipmill#1526: S-086-1, S-086-2, S-086-3
- shipmill/shipmill#1529: S-086-4, S-086-5, S-086-6, S-086-7
- shipmill/shipmill#1530: S-086-8
- shipmill/shipmill#1532: S-086-9, S-086-10, S-086-11, S-086-12
- shipmill/shipmill#1533: S-086-13, S-086-14

## Verification

- S-086-1: ran `tests/test_chain_impact.py`'s `test_s086_1_*` against `chains.py show --json` on a fake forge, held 2 and held_direct 1 for a direct and a transitive waiter, another repo's waiter counted, an item's own cycle counting nothing, milestones sorted and once each, all pass
- S-086-2: ran `test_s086_2_untrusted_unreadable_and_closed_issues_add_nothing`, UNTRUSTED, UNREADABLE, and closed waiters leave every held and held_direct unchanged, passes
- S-086-3: ran `test_s086_3_*`, each of the ten waiting_for values read for an issue set up for it in order, and idle_days from the newer of the issue's and its open closing pull request's updatedAt, all pass
- S-086-4: ran `test_s086_4_*` (rows, order, both shapes, exit 0, `--repo` past the first page of 100) and `chains.py impact --repo shipmill/shipmill --trusted-only` against GitHub, which read the repo's open issues and exited 0 with no row, all pass
- S-086-5: ran `test_s086_5_*`, heads idle 7 days or more and with `--days 3` those idle 3 or more, never an `items` or `cycle` item, exit 1 with a row, 0 without, 2 for `--days 0`, all pass
- S-086-6: ran `test_s086_6_*`, the milestone's open issues and what they wait on recursively and once, `decision` then `maintainer` first, an unknown title exits 2 naming it, an empty milestone prints `milestone T: nothing open` and exits 0, all pass
- S-086-7: ran `test_s086_7_the_views_make_only_reads_through_gh` for impact, stalled, and path, every gh call a GraphQL query or a REST GET, no mutation, passes
- S-086-8: ran `tests/test_chain_stalled.py`'s `test_s086_8_*`, one report-only CHAIN_STALLED row with the documented detail and fix from the one `chains.py show` run, none under `--tier` or `--sweep`, and `shipmill status`'s `stalled chains:` line (`src/shipmill/status.py`) with an unchanged verdict, all pass
- S-086-9: ran `tests/test_chain_impact_order.py`'s `test_s086_9_*`, `--tier 6` ISSUES rows carry `impact` most held first, and a failed walk gives CHAIN_UNREADABLE with empty lists while the rows print, all pass
- S-086-10: ran `test_s086_10_*`, the fingerprint and item_key unchanged by `impact`, and each malformed field fails the read, all pass
- S-086-11: ran `test_s086_11_*`, a tier 6 row holding 3 before an earlier kind holding 1 before one holding none, S-046-12's order with empty impact, expedite still first, tiers 1 to 3 before tier 4, all pass
- S-086-12: ran `test_s086_12_*` and read `src/shipmill/gate.py`'s `first by impact` reason and the prompt's `start with it.` line, both from the parsed digits, and a LAUNCH without impact reads as before, all pass
- S-086-13: ran `tests/test_fleet_queue.py`'s `test_s086_13_*` (holds then oldest first, `holds K` on each line, `holds` and `order` in `--json`, one `chains.py impact` naming every fleet repo after the repos' reads, the same output and commands without `--order` or with `--order age`, IMPACT_ERROR with the oldest-first order and exit 2 on a failed or malformed walk) with every spec 069 test unchanged, and `fleet.py queue --order impact --json` over a fleet of shipmill/shipmill against GitHub, which printed `"order": "impact"`, all pass
- S-086-14: read `skills/github-ship-watch/SKILL.md`'s Fleet section (`--order impact`, IMPACT_ERROR) and `skills/github-issue-triage/SKILL.md`'s Chains section (`chains.py impact`, `stalled`, `path`), and ran `test_s086_14_the_skills_document_order_impact_and_the_chain_views`, passes
