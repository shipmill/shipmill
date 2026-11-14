# S-058: The decision retro lowers a level on a rate, counts every question, and counts reverted decisions

status: approved
serves: G-1, G-2

## Problem

The decision retro of spec 030 (`retro.py gather --decisions`, S-030-18) proposes moving a
zone from `ask` to `notify` only when every question over `--lower-after` windows, at least 5
(`MIN_ASKS`), took the recommended option. One departure in a month resets it. It counts only
questions with a zone line, and it counts vetoes but not what became of a decision afterwards
(#1009).

Counted on one maintainer's repos on 2026-11-09: of 130 answered `needs-decision` questions
since 2026-10-10, 118 took the recommendation (91%), 9 departed from it, 3 were unclear. 57 of
the 130 have no zone line, so the retro can't see them. 87 items are labelled `decided`, none
with a comment starting `veto`. So the evidence that should lower a level is too strict to
ever fire and misses almost half the questions, and zero vetoes is ambiguous: the agents may
be right, or the maintainer may not be reading (#1046).

This spec changes the retro's lowering rule to a rate over a minimum sample, reports the
questions with no zone line, and counts per zone the `decided` items reverted or reopened
within a set time. The retro still only proposes: a level changes only by the maintainer's
edit of `[decisions]`, a zone fixed at `never` (D-48).

## Behaviour

All changes are in `skills/github-ship-watch/scripts/retro.py gather --decisions` (Python
3.10, standard library) and the Weekly retro section of `skills/github-ship-watch/SKILL.md`.
What spec 030 says of the window, the trusted authors (D-29), the zone line, the decided and
veto-handled markers, how an answer is read (a trusted person's reply or a maintainer's
relay, D-68, D-70), and the `--raise-at` rule stays as it is.

### What changes in the lowering rule

Today (S-030-18): a zone at `ask`, above its floor, is proposed `ask` to `notify` when its
questions over the last `--lower-after` windows number at least 5 and every one was answered
`recommended`. An unanswered question counts as not recommended, so a question still open
blocks the proposal.

After this spec:

- A question is **answered** when its zone line reads `answer=recommended` or `answer=other`,
  or when the first answer after it, read as S-030-18 reads it, exists. An answer that can't
  be read as an option is answered and not recommended. A question with no answer yet is
  left out of the sample
- A zone at `ask`, above its floor, is proposed `ask` to `notify` when its answered questions
  over the last `--lower-after` windows number at least `--lower-min`, and at least
  `--lower-rate` percent of them took the recommended option
- The proposal keeps its title, `Decision policy: <zone> from ask to notify`, and its `why`
  names the counts and the thresholds: `9 of 10 answered questions (90%) over 4 windows took
  the recommended option, at least 90% of at least 10`
- `MIN_ASKS` goes; nothing else in the proposals changes. A zone at its floor is never
  proposed lower, and a zone at `notify` is never proposed `act`

New flags, as spec 030's and spec 027's thresholds are flags and not policy keys:

| Flag | Default | Means |
|---|---|---|
| `--lower-rate P` | 90 | the percent of answered questions that took the recommended option, 1 to 100 |
| `--lower-min N` | 10 | the answered questions a zone needs over `--lower-after` windows, at least 1 |
| `--revert-days N` | 14 | how long after a decided marker a revert or reopening counts against it, at least 1 |

A value out of range exits 2, as `--raise-at` and `--lower-after` do.

`--lower-min` is 10, not 20. The retro counts per repo and per zone over 4 weekly windows, and
a busy zone (`protected` on one repo) had 14 questions in 30 days, so 20 would almost never be
reached. A lower level is still only a proposal the maintainer merges.

Per zone, the report gains `answered_over_windows` beside `asks_over_windows` and
`recommended_over_windows`, and `rate_over_windows`, the percent recommended of answered,
rounded down, or `null` with no answered question.

### Questions with no zone line

A trusted needs-decision question (first line `<!-- shipmill:needs-decision -->`, by a
trusted author as S-030-18 reads it) whose second line is no zone line is counted apart, read
for its answer the same way. The report gains:

- `"unzoned"`: this window's `asks`, `answered`, and `recommended`, the same over the
  windows, and `items`, each such question of this window as `{"kind", "number"}`
- `"all"`: the same counts over every question, zoned and not, with `rate_over_windows`

The text output adds `  no zone line: asks N (A answered, R recommended): #12, #34` and
`  every question over the windows: ...`. Questions with no zone line are reported, never part
of a zone's rate, and never proposed on.

### What became of a decided item

For each trusted decided marker (`<!-- shipmill:decided zone=<id> until=... -->`) posted in
the `--lower-after` windows, the item it sits on is:

- **vetoed** when the item has a trusted veto-handled marker for that zone after it, as
  spec 030 counts vetoes
- **reverted** when it isn't vetoed and, within `--revert-days` after the marker:
  - an issue: a reopening of the issue (its timeline's `ReopenedEvent`), by anyone
  - a pull request that merged: another pull request merged whose body has a line
    `Reverts <owner/repo>#N` or `Reverts #N`, the line GitHub's Revert button writes, or whose
    title is `Revert "<the pull request's title>"`
- **held** when the marker is at least `--revert-days` old and the item is neither vetoed nor
  reverted
- otherwise still within its window, and counted in none of the three

Per zone, the report gains `decided_over_windows`, `vetoed_over_windows`,
`reverted_over_windows`, and `held_over_windows`, and the text line adds `decided D over the
windows: V vetoed, R reverted, H held`. A reverted item is reported, and no proposal reads it:
`--raise-at` still counts vetoes alone.

The fetch reads, beside the comments it reads today, each issue's reopenings and each pull
request's title, merge time, and body, for the issues and pull requests updated since the
oldest window's start.

### The weekly retro

The Weekly retro section of `skills/github-ship-watch/SKILL.md` keeps `--lower-rate` (90),
`--lower-min` (10), and `--revert-days` (14) at their defaults unless the user names others,
and its Decisions section of the tracking comment shows per zone the rate over the windows
and the decided items' outcomes, and one row for the questions with no zone line. A proposal
issue's body cites the zone's rate and sample. The retro still never edits `[decisions]`.

`docs/specs/030-decision-policy.md`'s S-030-18 keeps its counting and its raise rule; the
build issue that delivers S-058-1 rewrites its lowering clause to point to this spec, and its
test with it, so spec 030 stays true to the code on the default branch.

Spec 057's parts change nothing here: the zone line and the markers name a zone, so a
question or a decision on a path a part sets counts under its zone, and a proposal names the
zone's line in `[decisions]`.

## Acceptance criteria

- S-058-1: `retro.py gather --decisions` proposes `<zone> from ask to notify` for a zone at `ask` above its floor whose answered questions over the `--lower-after` windows are 10 with 9 recommended (90%), with a `why` naming 9 of 10, 90%, and the thresholds; and proposes nothing for 17 of 20 (85%) or for 9 of 9 (below `--lower-min`)
- S-058-2: A question with no answer yet is left out of `answered` and doesn't block a proposal; an answer that can't be read as an option, or one that departs from the recommended option, counts as answered and not recommended; a zone line's `answer=recommended` or `answer=other` counts as answered without reading the thread
- S-058-3: A zone at its floor (`scope`, `rule-departure`, `unknown`) is never proposed lower at any rate, and a zone at `notify` is never proposed `act`
- S-058-4: `--lower-rate`, `--lower-min`, and `--revert-days` default to 90, 10, and 14; `--lower-rate` 0 or 101, `--lower-min` 0, and `--revert-days` 0 exit 2
- S-058-5: Per zone the JSON report gives `answered_over_windows` and `rate_over_windows`, the percent rounded down, `null` with no answered question
- S-058-6: A trusted needs-decision question whose second line is no zone line is counted under `unzoned` (`asks`, `answered`, `recommended`, and `items` naming its kind and number), and under `all` with every zoned question; an untrusted author's question counts in neither; the text output prints a `no zone line:` line listing the items
- S-058-7: A decided marker on an issue reopened within `--revert-days` after it counts `reverted` for its zone; one reopened later, or one with a trusted veto-handled marker for that zone, does not (the latter counts `vetoed`)
- S-058-8: A decided marker on a merged pull request counts `reverted` when another pull request merged within `--revert-days` after the marker has a body line `Reverts <owner/repo>#N` or `Reverts #N`, or the title `Revert "<its title>"`; a revert pull request that is open or closed unmerged does not count
- S-058-9: A decided marker at least `--revert-days` old on an item neither vetoed nor reverted counts `held`; a younger one counts in none of `vetoed`, `reverted`, and `held`; per zone the JSON report gives `decided_over_windows`, `vetoed_over_windows`, `reverted_over_windows`, and `held_over_windows`
- S-058-10: Reverted items propose nothing: a zone at `notify` with no vetoes and reverted items of any number gets no proposal, and `--raise-at` reads vetoes alone, as S-030-18 says
- S-058-11: The Weekly retro section of `skills/github-ship-watch/SKILL.md` names `--lower-rate`, `--lower-min`, and `--revert-days` with their defaults, and its Decisions section names the rate, the decided items' outcomes, and the row for questions with no zone line; `retro.py`'s usage text describes the new rule and flags

## Out of scope

- Changing a level by itself: the retro proposes, and the maintainer edits `[decisions]`, a zone fixed at `never` (D-48)
- Proposing `notify` to `act`, or counting reverts toward `--raise-at`: the counts are reported first, so the maintainer sees how often the revert match fires before a rule reads it
- Matching a decision redone by later work that isn't a revert or a reopening (a follow-up fix, a rewrite in another pull request): no reliable signal ties it to the decision
- Adding a zone line to old questions, or placing a question with no zone line in a zone: reported, not guessed
- Counting or proposing per part of a zone (spec 057): the markers name zones alone
- Moving the retro's thresholds into `.github/shipmill.toml`: they stay flags, as spec 030's and spec 027's are

## Decisions relied on

- D-16: only a trusted author's question, answer, or marker counts
- D-29: the trusted marker comments the retro reads
- D-48: the retro only proposes; a level changes by the maintainer's edit of `[decisions]`, never below a zone's floor
- D-68, D-70: the relay `Decision by @<login>` that S-030-18 reads as the maintainer's answer, unchanged here

## Issues

## Verification
