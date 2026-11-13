# S-066: Issue to release by stage

status: approved
serves: G-7, G-1

## Problem

`metrics.py` reports issue to release as one number (`issue_to_release_median`,
`issue_to_release_p90`, spec 027), so a retro can say G-1 is missed but not where the time
went. Finding that out takes a hand-written GraphQL query (#831).

Done by hand on this repo for 312 issues closed by a merged pull request and filed from
2026-09-30 to 2026-10-30, most of an issue's time to release passed before any pull request
existed (#830). Issue to PR opened had a 93 min median and a 1201 min p90, against 24 min
for PR opened to merged and 19 min for merged to release. It grew from a 54 min median in
the 30 days to 2026-10-19. Issues an agent filed waited longer than issues a person filed
(median 113 min against 34 min). G-1's measure is met today (p90 31 h against 2 d), with
little room. The maintainer accepted the opportunity (#1056).

## Behaviour

### The stages

`skills/github-ship-watch/scripts/metrics.py` measures issue to release in stages, over the
same issues its Issue to release measure counts: each issue a merged pull request closes
(GitHub's closing links) whose merge commit a stable release published in the window first
shipped. For each such issue, the pull request is the one whose release is earliest, as
Issue to release picks it today; a tie goes to the pull request merged first. Its stages:

| Measure | From | To |
|---|---|---|
| Issue to first agent comment | the issue's opening | the first comment on the issue an agent wrote, at or before the release |
| Issue to PR opened | the issue's opening | the pull request's creation |
| PR opened to merged | the pull request's creation | its merge |
| Merged to release | its merge | the release's publication |

- **An agent's comment** carries the agent marker `<!-- shipmill:agent -->` as a line of its
  own (D-62), or its author is a Bot, a login ending `[bot]`, or a `--bot` login, so comments
  from before the marker existed still count. An issue with no agent comment by its release
  isn't counted in that stage; the measure's detail says how many were left out
- **The three stages after the issue's opening add up:** for each issue, issue to PR opened,
  PR opened to merged, and merged to release sum to its issue to release. A pull request
  created before its issue (an issue filed for work already open) counts a negative issue to
  PR opened, so the sum still holds
- **Issue to PR opened by who filed the issue:** two more measures, Issue to PR opened,
  person-filed, and Issue to PR opened, agent-filed. An issue is agent-filed when its body
  carries the agent marker (D-62) or its author is a Bot, a login ending `[bot]`, or a `--bot`
  login; every other issue is person-filed. Each issue counts in exactly one of the two
- Each stage is a duration measure like Lead time: median and p90 (nearest rank) in hours,
  with `p90` and `count` in its JSON. A stage with nothing to measure reads "no data", never 0
- The measures follow Issue to release in the table, the markdown, and the JSON's
  `measures` list; no other measure changes

What it reads beyond today: each pull request's `createdAt`, and for each closing issue its
author, body, and comments. Comments are read oldest first and paged only until the first
agent comment. Nothing comes from outside the forge: no gate log, tick, or host state.

### The registry

Each stage joins the spec 027 registry in `src/shipmill/product.py`, with a median and a p90
metric, target unit `<n>h` or `<n>d`:

| Metric | metrics.py measure, value |
|---|---|
| `issue_to_agent_comment_median`, `issue_to_agent_comment_p90` | Issue to first agent comment |
| `issue_to_pr_median`, `issue_to_pr_p90` | Issue to PR opened |
| `issue_to_pr_person_median`, `issue_to_pr_person_p90` | Issue to PR opened, person-filed |
| `issue_to_pr_agent_median`, `issue_to_pr_agent_p90` | Issue to PR opened, agent-filed |
| `pr_to_merge_median`, `pr_to_merge_p90` | PR opened to merged |
| `merge_to_release_median`, `merge_to_release_p90` | Merged to release |

So a goal can carry `measure: issue_to_pr_p90 < 12h`. `shipmill product check` and
`shipmill product measure` accept them as they accept the registry's other metrics.
`skills/github-ship-watch/scripts/retro.py`'s `METRIC_MEASURES` maps each one to its
measure, so the retro reads its status. `skills/shipmill-setup/SKILL.md` lists them with the
registry it offers.

### The retro names the stage that grew most

`retro.py gather --goals` already runs metrics.py for this week and the week before. When a
goal's measure is a lead-time metric and reads **not met**, the goal's entry gains
`grew_most`, the stage whose value grew most from the week before to this week:

- For `issue_to_release_median` and `issue_to_release_p90`, the candidates are Issue to PR
  opened, PR opened to merged, and Merged to release. For `lead_time_median` and
  `lead_time_p90`, which start at a pull request's first commit, they are PR opened to merged
  and Merged to release
- It compares the measure's own statistic: the median for a `_median` metric, the p90 for a
  `_p90` one
- The change is this week's value minus the week before's, in hours. A stage with no data in
  either week isn't compared. A tie goes to the earlier stage in the order above
- `grew_most` is `{"measure", "statistic", "value", "previous", "change"}`, or `null` when no
  stage can be compared. A goal whose measure is met, has no data, or names another metric
  has no `grew_most` key
- In the text output, and in the Goals section of the retro's tracking comment
  (`skills/github-ship-watch/SKILL.md`, Weekly retro), the goal's row adds `grew most: <measure>,
  <statistic> <previous> to <value>`, or `grew most: no stage to compare`

## Acceptance criteria

- S-066-1: `metrics.py --json` lists Issue to first agent comment, Issue to PR opened, Issue to PR opened, person-filed, Issue to PR opened, agent-filed, PR opened to merged, and Merged to release right after Issue to release, each with a median `value`, `p90`, `count`, and unit `hours`, or "no data" with a null value when nothing is measured
- S-066-2: over a scripted forge, each stage is measured over exactly the issues Issue to release counts, against the pull request whose release is earliest (the earliest merged on a tie): opening to that pull request's creation, its creation to its merge, and its merge to the release's publication
- S-066-3: for every counted issue, its issue to PR opened, PR opened to merged, and merged to release sum to its issue to release, a pull request created before its issue included
- S-066-4: Issue to first agent comment ends at the first comment, at or before the release, that carries the agent marker as a line of its own or whose author is a Bot, a login ending `[bot]`, or a `--bot` login; an issue with none is left out of that stage, and the detail gives how many were left out
- S-066-5: an issue whose body carries the agent marker, or whose author is a Bot, a login ending `[bot]`, or a `--bot` login, counts in Issue to PR opened, agent-filed, and every other counted issue in person-filed; the two counts sum to Issue to PR opened's count
- S-066-6: metrics.py pages an issue's comments only until the first agent comment, and reads no source but GitHub's API through gh
- S-066-7: `shipmill product check` accepts a goal measure naming each of the twelve stage metrics with an `h` or `d` target, refuses one with a `%` or `/week` target, and `shipmill product show --json` gives its unit as `hours`
- S-066-8: `retro.py`'s `METRIC_MEASURES` maps each stage metric to its measure and statistic, so a goal measured on one reads met, not met, or no data from metrics.py's JSON
- S-066-9: `retro.py gather --goals` gives a goal whose `issue_to_release_*` measure is not met a `grew_most` naming the stage, among Issue to PR opened, PR opened to merged, and Merged to release, whose same statistic grew most in hours from the week before, with `value`, `previous`, and `change`; for a `lead_time_*` measure only PR opened to merged and Merged to release are candidates
- S-066-10: `grew_most` skips a stage with no data in either week, breaks a tie toward the earlier stage, is `null` when no stage can be compared, and is absent for a goal whose measure is met, has no data, or names a metric that isn't a lead-time metric
- S-066-11: the Weekly retro section of github-ship-watch's SKILL.md adds the goal's `grew most:` line to its Goals row, and shipmill-setup's SKILL.md lists the stage metrics among the registry it offers

## Out of scope

- **The one-off diagnosis of #830.** Splitting issue to PR opened into its parts (a gate tick, a running session, `[agents] wip`, a `Depends on` hold, `needs-decision`, the implementer's own work) and proposing a fix for the largest part. Most of those parts live in the gate's host state, not the forge, and a diagnosis's result isn't something a test can check. It stays on #830 and is done by hand once this spec is built, with these stage measures as its starting point. The fix it proposes is filed then as its own issue
- Measures of those parts from the forge (time held by a `Depends on` line or by the `needs-decision` label, read from issue timelines): a later spec, if the diagnosis shows they matter
- A stage's own window or a trailing average: every stage is read over the retro's week, as spec 027 has it
- Stages in `shipmill status` or the fleet report: the retro's comment is the one place, as for spec 027's measures
- A measure for any goal of this repo: building this spec adds none to `docs/product.md`; the maintainer adds one if they want it
- A retro proposal issue for a grown stage: the retro reports the stage on the goal's row, and its existing proposals are unchanged

## Decisions relied on

- D-34: only the maintainer changes the direction, a goal's measure included
- D-62: an agent's text is told by its marker
- D-69: issue to release is read from the release and the close, never from a notice

## Issues

- shipmill/shipmill#1089: S-066-1, S-066-2, S-066-3, S-066-4, S-066-5, S-066-6
- shipmill/shipmill#1092: S-066-7, S-066-8, S-066-9, S-066-10, S-066-11

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
