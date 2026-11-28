# S-109: How much of the work a person decided GitHub credits to them, per repository

status: approved
serves: G-8

## Problem

G-8 asks that each person's profile credit the work they decided, and that the record still
tell their words from their agents'. Specs 049 and 051 write that credit: autonomous mode names
the decider in a `Co-authored-by` trailer on the merge commit, and assisted mode makes the
decider the merge commit's author with the App's bot as co-author (D-73). Nothing reads it
back. Whether G-8 holds on a connected repository is today a hand count: open each merged pull
request, work out who decided it, and look the merge commit up on their profile. The live
check of spec 051 (#870) did that for one merge.

The accepted plan for G-8 (#990) filed this as its item W-2 (#1769): the maintainer sees, for
each connected repository, how much of the work they decided GitHub credits to their profile,
and how much of it was written as them by an agent, so G-8 can be read as met or not from a
number rather than a hand count. Its Order says W-2 does not wait on W-1 (#1768, the live check
of a merge written as a person), and its Notes say G-8 has no measure in `docs/product.md`: this
spec gives it a registry metric its Check can cite, and that a measure G-8 leaves behind once
met (spec 105) can name. Rewriting G-8's Check, or adding that measure, stays the maintainer's
change (D-34).

## Behaviour

### Two measures in metrics.py

`skills/github-ship-watch/scripts/metrics.py` gains two measures, over the pull requests merged
in the window (the ones Human touch and Agent share count), listed right after Agent share in
the table, the markdown, and the JSON's `measures` list. No other measure changes.

- **A decided pull request** is a merged pull request that names at least one decider. Its
  deciders are the people spec 049's sources name (spec 049, Who is a decider), in its order and
  with its limits: an approver (their latest review is `APPROVED`), an answerer (a trusted reply
  to a needs-decision question, or the login a `Decision by @<login>` or ``Decision by
  `@<login>` `` comment by a Bot, a login ending `[bot]`, or a `--bot` login names), the author
  of an issue it closes, and the person who added `planned` to an `opportunity` issue it closes,
  each on the pull request, the issues it closes, and those issues' parents as spec 049 reads
  them. A trusted person is an `OWNER`, `MEMBER`, or `COLLABORATOR` (D-16), or for a label event
  a person with `write`, `maintain`, or `admin` permission; never a Bot, a login ending `[bot]`,
  a `--bot` login, or the pull request's author. A record whose body carries the agent marker
  `<!-- shipmill:agent -->` as a line of its own names no decider, save the `Decision by` relay
  spec 049 reads (D-62)
- **Credited:** GitHub credits a merge commit to the accounts its `authors` connection names
  (the git author and each `Co-authored-by` trailer GitHub resolves to an account). A decided
  pull request is credited when every one of its deciders' logins is among those accounts.
  Nothing is guessed from an email: a trailer GitHub doesn't resolve to an account credits no one
- **Written as the decider:** a decided pull request whose merge commit's git author resolves to
  one of its deciders and whose message carries a `Co-authored-by` trailer whose email ends in
  `[bot]@users.noreply.github.com`, the form spec 051 writes (S-051-11), so the record names the
  agent beside the person

The measures:

| Measure | Value | Unit |
|---|---|---|
| Decided work credited | credited decided pull requests / decided pull requests | `ratio` |
| Decided work written as the decider | written-as-the-decider decided pull requests / decided pull requests | `ratio` |

- Each reads "no data", never 0, when no decided pull request merged in the window, with the
  detail `no decided PR merged in the window`
- Decided work credited's detail reads `<credited> of <decided> decided merges credited to every
  decider; <merges> merged, <undecided> with no decider`. Written as the decider's reads
  `<written> of <decided> decided merges written as the decider with the agent as co-author`
- Each measure's JSON carries `decided`, `credited`, `written_as_decider`, and `merges`, and a
  `people` list, one entry per decider login, sorted by login: `{"login", "decided",
  "credited", "written_as_decider"}`, counted over the pull requests that person decided, so
  each person's own share can be read
- In the table and markdown output a login is never written bare: the `people` list is JSON
  only (D-61)

What it reads beyond today, for the pull requests merged in the window only: each merge
commit's `authors` and message, each review's author association and submission order, the
pull request's comments, and for each issue it closes the author association, the parent, the
comments, and the label events, read through gh as metrics.py reads everything else. Nothing
comes from outside the forge (N-2): no gate log, host state, or stored token.

### The registry and the retro

Both join the spec 027 registry in `src/shipmill/product.py` with unit `ratio`, target `<n>%`:

| Metric | metrics.py measure |
|---|---|
| `decided_credited` | Decided work credited |
| `decided_written_as_decider` | Decided work written as the decider |

So a measure (`Held: ...`, spec 105) can carry `measure: decided_credited >= 90%`; `shipmill
product check` and `shipmill product measure` accept them as they accept the registry's other
ratio metrics. A goal of kind goal still takes no `measure:` line (spec 105): its Check names
the number in prose.
`skills/github-ship-watch/scripts/retro.py`'s `METRIC_MEASURES` maps each to its measure's
`value`, so the weekly retro of each connected repository reads a measure held on one as met,
not met, or no data. `skills/shipmill-setup/SKILL.md` lists them with the registry it offers,
and `skills/github-ship-watch/SKILL.md` names the two measures where it lists metrics.py's.

## Acceptance criteria

- S-109-1: `metrics.py --json` lists Decided work credited and Decided work written as the decider right after Agent share, each with unit `ratio`, a `value`, and the keys `decided`, `credited`, `written_as_decider`, `merges`, and `people`; with no decided pull request merged in the window each reads "no data" with a null value and the detail `no decided PR merged in the window`
- S-109-2: over a scripted forge, a merged pull request counts as decided exactly when spec 049's sources name a decider for it: an approver whose latest review is `APPROVED`, a trusted needs-decision answerer, the login a `Decision by` comment by a bot names, the trusted author of an issue it closes or of that issue's parent, or the person with write, maintain, or admin permission who added `planned` to an `opportunity` issue it closes or to its parent
- S-109-3: a Bot, a login ending `[bot]`, a `--bot` login, an untrusted account, the pull request's author, and a record whose body carries the agent marker as a line of its own (other than a bot's `Decision by` relay) name no decider, and a pull request with only those counts in `merges` and not in `decided`
- S-109-4: a decided pull request counts as credited only when every decider's login is among its merge commit's `authors`; a decider named only by a trailer GitHub doesn't resolve to an account, or not named at all, leaves it uncredited
- S-109-5: a decided pull request counts as written as the decider only when its merge commit's git author resolves to one of its deciders and its message carries a `Co-authored-by` trailer whose email ends in `[bot]@users.noreply.github.com`; a person's own merge with no such trailer, and an App-authored merge naming the decider as co-author, don't count
- S-109-6: the `people` list has one entry per decider login, sorted by login, whose `decided`, `credited`, and `written_as_decider` count the pull requests that person decided; the table and markdown output name no login
- S-109-7: metrics.py reads the records these measures need only for pull requests merged in the window, and from no source but GitHub's API through gh
- S-109-8: `shipmill product check` accepts a measure's `measure:` line naming `decided_credited` or `decided_written_as_decider` with a `%` target and refuses one with an `h`, `d`, or `/week` target, and `shipmill product show --json` gives its unit as `ratio`
- S-109-9: `retro.py`'s `METRIC_MEASURES` maps `decided_credited` and `decided_written_as_decider` to their measures' `value`, so a measure held on one reads met, not met, or no data from metrics.py's JSON
- S-109-10: `skills/shipmill-setup/SKILL.md` lists both metrics among the registry it offers, and `skills/github-ship-watch/SKILL.md` names both measures where it lists metrics.py's

## Out of scope

- Rewriting G-8's Check to cite the number, or adding the measure a met G-8 leaves behind, in
  `docs/product.md`: the direction changes only by the maintainer (D-34); the plan's Notes
  leave it to them
- Issues and pull requests opened as the person (spec 051's other two writes), which a profile
  also counts: this spec reads merge commits, the work that reaches the default branch
- A table across every connected repository at once (the fleet report or `shipmill status`):
  each repository's weekly retro reads its own, as spec 066 has it for the stages
- An agent writing as a person without shipmill's trailer: `AGENT_AS_PERSON` (spec 051,
  S-051-14) reports a marked record a person's token made without the App
- The live check of a merge written as a person (#1768, W-1): these measures read whatever
  GitHub records, and that check settles what it records
- Rewriting merge commits already on the default branch

## Decisions relied on

- D-16
- D-34
- D-61
- D-62
- D-65
- D-73

## Issues

- shipmill/shipmill#1834: S-109-1, S-109-2, S-109-3, S-109-4, S-109-5, S-109-6, S-109-7
- shipmill/shipmill#1835: S-109-8, S-109-9, S-109-10

## Verification
