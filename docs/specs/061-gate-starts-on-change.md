# S-061: The gate starts a session only when something changed that it can act on

status: approved
serves: G-1

## Problem

"The gate keeps starting sessions on items where nothing has changed and nothing can be done"
(shipmill/shipmill#969). Across 14 connected repos, 126 of 595 gate sessions wrote nothing to
GitHub. Three patterns made most of them:

- `VERIFY_DUE` on one issue started 13 sessions in four days: its `## Check` waits on an
  artifact that doesn't exist yet, and each session concluded the same
- `PRS_OPEN` where every open pull request waits on the maintainer: 24 of 59 sessions in one
  repo, 7 of 41 in another
- `HANDOFF_DUE` that no longer held when the session read it: 13 sessions in one repo, one of
  them eight minutes after the hand-off. The cause was not established

Sessions that do write repeat too: "`triage_state.py` raises REVISIT for every postponed issue
on each new stable tag" (shipmill/shipmill#1013). Since 2026-11-01, four postponed issues here
each got 26 comments saying the release didn't touch them, all postponing again; one session
posted eight in 11 minutes. A repo runs one gate session at a time, so an idle one delays real
work, and the repeated comments bury the threads the maintainer reads.

On the default branch today (spec 046, `src/shipmill/walk.py`): a tick hands a session the
first item not handed within `retry_hours` (default 24) with the same fingerprint, and the
fingerprint of a tier 6 item covers every issue in its triage state (`VERIFY_DUE #842 #900`),
so one issue joining or leaving the state hands all of them again. After `retry_hours` an
unchanged item is handed again whatever its last session did. `PRS_OPEN` already leaves out a
pull request whose needs-decision question waits (`watch_state.py`), and a person's pull
request with an assignee (PRS_PARKED), but not one labelled `shipmill-ready` that waits on the
maintainer's merge under `[autonomy] land = "propose"`. `triage_state.py` reads REVISIT
whenever the newest triage comment of a postponed issue is older than the newest stable tag.

The opportunity is shipmill/shipmill#1052.

## Behaviour

This spec extends spec 046 (the walk and `handed.json`), spec 040 (`land = "propose"`), and
spec 048 (`tick.json`). A tick keeps spec 046's order: hold, busy, still working, the change
check, the walk, the decision, then the prune (D-56).

### Subjects

An item of tier 3, 4, or 6 (`PRS_OPEN`, `AGENT_DRAFT`, `VETOED`, and each `ISSUES` row of a
triage state) names issues or pull requests in its detail: `#842 #900`, or `VERIFY_DUE #842
#900`. Those are its **subjects**, read as `#N` with `N` digits only. An item of tier 1, 2, 5,
or 7 has none and is handed by its fingerprint as spec 046 says, unchanged: production and the
release lane keep `retry_hours`.

### Handing by subject

`handed.json` (`src/shipmill/walk.py`, `Handed`) records a handed subject under the key
`<kind> #<N>`, such as `ISSUES VERIFY_DUE #842` or `PRS_OPEN #12`, with `session` and `at` as
today, and for a pull request its `head` (the head SHA) and `rollup` (the head's check rollup
state) from the change check. A kind is the item's kind (`Finding.kind`), so the same issue in
another triage state is another subject: a state change is new work.

A walk takes an item with subjects as the item **cut to its subjects not taken**: its detail
keeps only those `#N`, and its fingerprint is the cut item's. An item whose every subject is
taken is no item, and the walk goes on as it does past a handed item today. A LAUNCH records a
hand for each subject of the cut item.

The prompt (`src/shipmill/gate.py`, `prompt`) names a cut item's subjects after its brief, as
`- ISSUES VERIFY_DUE shipmill/shipmill: #900 (tier 6)`. The numbers are digits the gate parsed,
never the detail's other text (#114), and one line under the list says: `Work on the numbers
named; the others were handed to an earlier session and nothing changed on them since.`

### A subject is taken

A subject is **taken** when its hand is:

- **within `retry_hours`**, as spec 046 holds an item today, or
- **idle**: past `retry_hours`, its session didn't end dead (S-046-15), and nothing changed on
  the subject since the hand: its `updatedAt` on GitHub is earlier than the hand's `at` less
  `CURSOR_OVERLAP` (5 minutes), and for a pull request its head SHA and check rollup state equal
  the hand's

A session that commented on, labelled, or pushed to its subject moved `updatedAt` past the
hand, so its subject is not idle: past `retry_hours` it is handed again, as today. A session
that wrote nothing on it left `updatedAt` where it was, so its subject waits, past
`retry_hours`, until someone or something changes it: a comment, a label, an edit, a close, a
push, or a pull request's checks finishing. The 5 minutes keep a skew between the host's clock
and GitHub's from reading a session's own write as no change; a subject updated just before its
launch costs one more session, never a missed one.

**Where it is read.** A pull request's `updatedAt`, head, and rollup come from the change
check's query (S-046-3), which reads them already. An issue's `updatedAt` comes from one
GraphQL query (`src/shipmill/walk.py`), `issueOrPullRequest(number: N) { ... on Issue {
updatedAt } }` aliased once per issue, at most 100 per query, for every issue subject past
`retry_hours` the walk meets; a walk that meets none runs none.

**What the gate remembers, and where (N-2).** The facts that decide are GitHub's: a subject's
`updatedAt`, head, and rollup. `handed.json` keeps only which subjects the gate handed and
when, as it does under D-58, in the gate's state directory beside `cursor.json`. It is a cache
of the gate's own launches, not state another reader needs: deleted, every subject reads not
taken and is handed once more, never missed. The gate writes nothing new to GitHub for this.

**Dropping a hand.** An idle hand stays in `handed.json` past `retry_hours`. It drops when its
subject changed (the walk then hands the subject again and records the new hand), when a walk
that read every tier no longer finds the subject (#926: the issue closed, or left that triage
state), and when its session ended dead (S-046-15).

**The gate's side of the change check.** A hand past `retry_hours` is a change (S-046-2) on the
first tick after its `retry_hours` runs out, as today. The walk that finds it idle marks it
`idle: true` in `handed.json`, and an idle hand is no change on later ticks: a change to its
subject shows in the change check itself (an updated issue, a pull request's head, labels, or
rollup), so a tick with nothing else new stays QUIET.

**UNCHANGED.** When the walk reaches the end and every item it found is taken, the tick reads
UNCHANGED as S-046-14 says. When the first such item's subject is idle, the reason reads
`every item was handed; the first, <kind> #<N>, went to session <id>, which wrote nothing on
it; it waits for a change`.

### PRS_OPEN leaves out what waits on the maintainer's merge

Under `[autonomy] land = "propose"`, a session reviews a pull request and labels it
`shipmill-ready` for a person to merge (spec 040); after that it waits on the maintainer.
`watch_state.py` lists such a pull request in PRS_PARKED as `TO_MERGE #N`, beside its
`WITH_PERSON` part (`WITH_PERSON #4 (@a); TO_MERGE #12`), not in PRS_OPEN, in tier 3's read
and in the full report. It needs no read beyond the labels tier 3 already has. Under `act` and
`observe` a labelled pull request is listed as today. `shipmill status` already reports these
as waiting on you to merge (S-040-11) and is unchanged.

### A hand-off is read again before its session starts

Before a LAUNCH whose item's kind is `ISSUES HANDOFF_DUE`, after the preflights (spec 035, spec
048, the hooks self-test), the gate runs tier 6's read again (`watch_state.py --json --tier 6`
with the change check's data, S-046-7) and cuts the item to the subjects that still read
HANDOFF_DUE. A dry run reads again too.

- **Some still read HANDOFF_DUE:** the session starts for those alone, and the hands record
  those alone
- **None does:** the tick starts no session and writes no `cursor.json` or `handed.json`, so
  the next tick walks again. Its decision is QUIET, `HANDOFF_DUE #N read again: no longer due;
  the next tick walks again`, and `tick.json` records it, so the next case leaves its evidence
  for the cause #969 couldn't establish

### A postponed issue comes back when what it waits on changed

**The recorded form.** A postpone comment (`skills/github-issue-triage/references/comments.md`,
Postpone and Postpone (no goal)) may carry one line naming the paths the decision depends on,
each in backticks, separated by commas:

```markdown
Revisit on: `src/shipmill/gate.py`, `skills/github-ship-watch/**`
```

A path is relative to the repo's root; `**` matches any run of characters, `/` included, `*`
any run without `/`, and `?` one character other than `/`; anything else matches itself. The
Postpone (no goal) template carries `` Revisit on: `docs/product.md`, `docs/product/**` ``, since
a goal added to the direction is what it waits on. A postpone that waits on another issue or
pull request already has its form: a `Depends on` line in the body, which `triage_state.py`
reads as BLOCKED until it closes and UNBLOCKED then (spec 017); this spec adds no other kind of
condition.

**The reading.** `triage_state.py` (`skills/github-issue-triage/scripts/triage_state.py`) reads
a postponed issue whose newest triage comment has a `Revisit on:` line:

- **REVISIT**, `postponed before <tag>; <path> changed`, when the newest stable tag is newer
  than the comment and a file that changed between the base and the newest stable tag matches
  one of the paths. The base is the newest stable tag created before the comment
- **POSTPONED**, its note `waits on <paths>`, when none matches
- **REVISIT** as today, `postponed before <tag>`, when there is no stable tag before the
  comment, or GitHub's compare can't list every changed file: a missed revisit is worse than
  one more session
- **REVISIT**, `revisit line unreadable: <the line, cut to 100 characters>`, when the line
  names no path in backticks, so a session rewrites it

The changed files come from `gh api repos/<repo>/compare/<base>...<newest>`, paged with
`per_page=100`, read once per base tag in a run whatever the number of issues that share it.
A postponed issue whose newest triage comment has no `Revisit on:` line reads REVISIT and
POSTPONED as today, so an issue postponed before this spec isn't lost; the session that takes
up its next REVISIT adds the line when it postpones again.

### Docs

- `skills/github-issue-triage/references/comments.md`: the `Revisit on:` line in both postpone
  templates, and when to use a `Depends on` line instead
- `skills/github-issue-triage/SKILL.md` (the REVISIT bullet) and
  `skills/github-issue-triage/references/triage-rubric.md` (the REVISIT row): REVISIT comes
  when a recorded path changed, or on every stable tag without one
- `skills/shipmill-setup/SKILL.md`, The gate: a tick hands an item's issues and pull requests
  one by one, and one whose last session wrote nothing on it waits until it changes
- `skills/github-ship-watch/SKILL.md`: PRS_PARKED's `TO_MERGE` part
- Spec 046, under S-046-2 and S-046-13: a line saying spec 061 hands an item's subjects one by
  one and keeps an idle hand past `retry_hours`

## Acceptance criteria

- S-061-1: A LAUNCH of an item of tier 3, 4, or 6 records in `handed.json` one hand per `#N` its detail names, keyed `<kind> #<N>`, with session and at, and for a pull request its head SHA and check rollup; a LAUNCH of an item of tier 1, 2, 5, or 7 records its fingerprint as before
- S-061-2: With `ISSUES VERIFY_DUE #842 #900` found and `#842` handed within `retry_hours`, the tick launches the item cut to `#900`, its prompt names `#900` and not `#842`, and its new hand is for `#900` alone
- S-061-3: An item whose every subject is handed within `retry_hours` is no item: with no other item the tick reads UNCHANGED naming it, as S-046-14 does
- S-061-4: An issue subject whose hand is past `retry_hours`, whose session didn't end dead, and whose `updatedAt` is earlier than the hand's at less 5 minutes is handed to no session, and its hand stays in `handed.json` marked idle
- S-061-5: A pull request subject whose hand is past `retry_hours`, with the same head and check rollup as the hand and an `updatedAt` earlier than the hand's at less 5 minutes, is handed to no session; with a new head, a new rollup, or a later `updatedAt` it is handed again on that walk and its hand replaced
- S-061-6: An issue subject whose hand is past `retry_hours` and whose `updatedAt` is at or after the hand's at less 5 minutes is handed again on that walk, and its hand replaced
- S-061-7: A walk that meets issue subjects past `retry_hours` reads their `updatedAt` in one GraphQL query per 100 of them; a walk that meets none runs no such query, and a pull request's `updatedAt` comes from the change check alone
- S-061-8: A hand past `retry_hours` makes the first tick after its `retry_hours` runs out walk; once that walk marks it idle, a tick with no other change reads QUIET with no tier read
- S-061-9: An idle hand drops from `handed.json` when a walk that read every tier no longer finds its subject, and when its session ended dead
- S-061-10: An UNCHANGED tick whose first taken item's subject is idle reads `every item was handed; the first, <kind> #<N>, went to session <id>, which wrote nothing on it; it waits for a change`
- S-061-11: Under `land = "propose"`, `watch_state.py --json --tier 3` and the full report list an open pull request labelled `shipmill-ready` in PRS_PARKED as `TO_MERGE #N` and not in PRS_OPEN; under `act` and `observe` they list it as before
- S-061-12: Before starting a session for an `ISSUES HANDOFF_DUE` item, on a real tick and a dry run, the gate runs `watch_state.py --json --tier 6` again and starts the session, and records hands, for the subjects that still read HANDOFF_DUE only
- S-061-13: When no subject still reads HANDOFF_DUE on that read, the tick starts no session, writes no `cursor.json` or `handed.json`, and decides QUIET with `HANDOFF_DUE #N read again: no longer due; the next tick walks again`, which `tick.json` records
- S-061-14: `triage_state.py` reads a postponed issue whose newest triage comment has `` Revisit on: `src/a/**` `` as POSTPONED with the note `waits on src/a/**` when no file under `src/a/` changed between the newest stable tag before the comment and the newest stable tag, and as REVISIT naming the changed path when one did
- S-061-15: The compare is read once per base tag in a run, however many postponed issues share it, and paged with `per_page=100`; a compare that can't list every changed file, and an issue with no stable tag before its comment, read REVISIT as today
- S-061-16: A postponed issue whose newest triage comment has no `Revisit on:` line reads REVISIT and POSTPONED exactly as before this spec
- S-061-17: A `Revisit on:` line that names no path in backticks reads REVISIT with the note `revisit line unreadable: <the line>`
- S-061-18: A `Revisit on:` path matches with `**` across `/`, `*` and `?` within one path segment, and every other character as itself: `src/**` matches `src/a/b.py`, `src/*.py` matches `src/a.py` and not `src/a/b.py`
- S-061-19: `skills/github-issue-triage/references/comments.md`, `skills/github-issue-triage/SKILL.md`, `skills/github-issue-triage/references/triage-rubric.md`, `skills/shipmill-setup/SKILL.md`, `skills/github-ship-watch/SKILL.md`, and spec 046 say what the Docs list says

## Out of scope

- Telling every write a session made: whether it wrote is read from the subject's own
  `updatedAt`, so a session that wrote only elsewhere (a new issue that doesn't touch the
  subject) leaves its subject idle. A triage state that such a write changes (a pull request
  that makes an issue IN_PROGRESS) moves the item out anyway
- A ceiling on how long an idle subject waits: it waits until it changes (Decisions for you)
- Idle hands for tiers 1, 2, 5, and 7: production, the release lane, upgrades, and the
  direction keep `retry_hours`; their items have no issue or pull request to read a change from
- A pull request held only by a hold comment: reading every open pull request's comments on
  each tier 3 read costs what S-046-6 keeps out; after one session that finds it held and writes
  nothing, it waits as an idle subject until it changes
- The cause of the stale HANDOFF_DUE sessions: this spec reads the hand-off again and records a
  disagreement in `tick.json`; a fix of the cause, once that evidence names it, is its own issue
- A `Revisit on:` condition other than paths, such as a dependency's release: a postpone that
  waits on another item uses a `Depends on` line; any other condition keeps today's reading
- How QUIET's in-flight part words a `shipmill-ready` pull request (spec 048): it still counts
  as waiting to land
- `shipmill status` and `shipmill factory`: they report as before

## Decisions relied on

- D-16: unattended sessions work only on trusted authors' items; the cut item and its prompt
  name digits the gate parsed, never an issue's text
- D-56: the prune runs after the decision, whatever it is, the re-read QUIET included
- D-58: a tick checks for change first, walks the tiers in order, and keeps its cursor and its
  handed items in the state directory; this spec keeps an idle hand there past `retry_hours`
  (Decisions for you proposes the rule that refines D-58)

## Issues

The build issues, filled in once they are filed: one `- owner/repo#N: S-NNN-1, S-NNN-2` per
line, naming the criteria that issue delivers. Each criterion belongs to exactly one.

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
