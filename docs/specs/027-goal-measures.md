# S-027: A measure per goal, and the retro per goal

status: approved
serves: G-7

## Problem

A goal in `docs/product.md` (spec 024) says what the product works toward, never whether it
is reached, and nothing in the delivery loop reports on it. Two things go wrong:

- **Nobody can tell a goal is met.** The retro can count the work that served `G-1` this
  week, but "five issues served G-1" doesn't say whether G-1 holds, so a reached goal stays
  in the direction and keeps steering verdicts and plans (#389)
- **The direction goes stale unnoticed.** Nothing says that no work has moved a goal for
  weeks, how much work was postponed or declined against the direction, or how much merged
  agent work named no goal at all. Agents keep citing a direction the product has left,
  and their decisions look reasoned because they cite it (#387)

Spec 024 left metrics per goal out of scope; the maintainer's own direction now asks for
them (G-7: the loop knows whether each goal is met, from a measure, and proposes changing
the direction when it is). This spec adds the measure as one optional line under a goal, in
the grammar code already parses, and gives the weekly retro a report per goal that ends, at
most, in a proposal issue: only the maintainer changes the direction (D-34).

## Behaviour

### A goal's measure

A goal may carry one measure, on the line right after it, indented by two spaces:

    ## Goals

    - G-1: A connected repository goes from a new issue to an announced release with no human step but the maintainer's decisions
      measure: issue_to_release_median < 1d
    - G-2: Agents' work holds a quality bar the maintainer can trust without reading every diff
      measure: human_touch <= 20%
    - G-3: The person who asked for a change hears where it is available

The line's form is `  measure: <metric> <comparison> <target>`, single spaces between the
parts. This extends spec 024's grammar, which `src/shipmill/product.py` parses, and changes
nothing else in it:

- Only an item of Goals may carry a measure, on the line directly after its item line; a
  measure line under a user, a non-goal, a quality-bar item, a blank line, or another
  measure line is an error
- A goal carries at most one measure; a goal without one stays valid
- The same holds in a Goals section moved to `docs/product/<file>.md`
- Any other indented line in a list section is still an error, as in spec 024

The metrics are a fixed registry in `src/shipmill/product.py`, each one a value
`skills/github-ship-watch/scripts/metrics.py` already computes, with the unit its target
must use:

| Metric | metrics.py measure, value | Target unit |
|---|---|---|
| `deploy_frequency` | Deploy frequency | `<n>/week` |
| `lead_time_median` | Lead time for changes, median | `<n>h` or `<n>d` |
| `lead_time_p90` | Lead time for changes, p90 | `<n>h` or `<n>d` |
| `change_failure_rate` | Change failure rate | `<n>%` |
| `time_to_restore_median` | Time to restore, median | `<n>h` or `<n>d` |
| `issue_to_release_median` | Issue to release, median | `<n>h` or `<n>d` |
| `issue_to_release_p90` | Issue to release, p90 | `<n>h` or `<n>d` |
| `human_touch` | Human touch | `<n>%` |
| `agent_share` | Agent share | `<n>%` |

The comparison is one of `<`, `<=`, `>`, `>=`. `<n>` is a non-negative number with an
optional decimal part (`2.5d`); a percentage lies between 0 and 100. `1d` is 24 hours and
`20%` is a ratio of 0.2, the units metrics.py reports in. `shipmill product check` exits 1
naming the file, line, and rule for an unknown metric (listing the known ones), an unknown
comparison, a target whose unit doesn't fit its metric, or a malformed or misplaced measure
line. A metric joins the registry only together with the metrics.py code that computes it
(the agent quality measures of #384 would join when that is built).

**Only the forge.** A measure names a metric from the registry, all of which GitHub already
holds. A goal that the forge can't measure (adoption, user satisfaction, revenue) carries
no measure and reads "no measure" in the retro; no external source is read. Answering #389's
first open question this way keeps N-2 (no state of shipmill's own) and keeps every
measure checkable by code; a later spec can add an external source declared in
`.github/shipmill.toml` (D-4) when a goal needs one. The maintainer settled this in
chat: GitHub data only for now.

**One window.** Every measure is read over the retro's week, the window its metrics.py runs
already cover; a measure line names no window of its own. The maintainer chose this over a
per-measure trailing window, which stays out of scope.

### `shipmill product show` and the edit commands

`shipmill product show --json` gives each goal a `measure` key: `null` without one, else
`{"metric", "comparison", "target", "unit", "text"}`, where `target` is a number in the
metric's unit (hours, ratio, or per week), `unit` is `hours`, `ratio`, or `per week`, and
`text` is the line's text after `measure: `. Items of the other sections are unchanged. The
text output prints each goal's measure line under it, as written, so it reads as the file
does. `shipmill product ids` is unchanged: one line per id.

An agent changes a measure only through a command, as spec 024 has it for items:

- `shipmill product measure <G-n> "<metric> <comparison> <target>"` writes the goal's
  measure line, or replaces the one it has, and prints it; it exits 2 without writing for
  an id that isn't a goal the direction lists, or a measure `check` would refuse
- `shipmill product measure <G-n> --clear` removes the goal's measure line
- `shipmill product retire <G-n>` removes the goal's measure line together with its item
  line; `shipmill product edit <G-n>` rewrites the item line and keeps the measure;
  `shipmill product add goals` appends after the last goal's measure line when it has one

Each keeps spec 024's rules: it edits the working tree only, the file a moved Goals section
points to, leaves every other line byte for byte, and exits 2 on a file that fails `check`.
The commands live in `src/shipmill/product.py` and `src/shipmill/cli.py`.

### The other readers accept the line

The scripts that read the direction without shipmill accept a measure line under a goal and
read no more from it: `skills/github-pr-triage/scripts/pr_gate.py` (`direction_ids`, which
today stops on any non-item line) and `skills/github-issue-triage/scripts/specs.py` (which
already skips it). So adding a measure never breaks the gate or the spec check.

`skills/shipmill-setup/SKILL.md`: when setup writes the direction, it offers a measure for
each goal from the registry and writes the maintainer's choice with `shipmill product
measure`; a goal the maintainer gives no measure gets none. It never invents a target.

### The retro gathers per goal

`skills/github-ship-watch/scripts/retro.py gather` gains `--goals`, `--checkout DIR`
(default `.`), `--stalled-weeks N` (default 3), and `--met-weeks N` (default 4). With
`--goals`:

- DIR must be a checkout whose `HEAD` is `origin/HEAD`'s commit (the skill fetches it
  first); otherwise exit 2 naming `git fetch` and `git checkout`. A repo whose checkout has
  no `docs/product.md` gets `"goals": {"direction": false}` in its JSON and the line "No
  direction (docs/product.md): no per-goal report" in its text, and exits 0
- It reads the direction with `shipmill product show --json --repo DIR` (`shipmill` on
  PATH, else `uvx --from git+https://github.com/shipmill/shipmill@v0 shipmill`); a
  direction that command refuses stops the gather with exit 2 naming `shipmill product
  check`

**Work that served a goal**, counted for this week and the week before:

- An issue closed as completed in the window serves `G-n` when its latest verdict comment
  names it (`Serves: G-n.` after the bolded verdict, spec 024's verdict line), or when it is
  a build issue listed under `## Issues` of a spec whose `serves:` line names `G-n`. A
  verdict comment counts only when its first line starts `Triage: ` and its author is an
  OWNER, MEMBER, or COLLABORATOR or a `--bot` login, the trust rule of D-29
- A pull request merged in the window serves `G-n` when its body's `## Plan` names it in
  `Serves:`, read by the same rule as `pr_gate.py`
- Work whose verdict or plan says `quality bar` counts on its own row, not under a goal

**Per goal**, in the direction's order: its id and text, the issues and pull requests that
served it (numbers) this week, the counts for the week before, and its measure's status:

- **met**: the metric's value for this week holds the comparison
- **not met**: it doesn't; the report gives the value as metrics.py's text (`median 2.4 d`)
- **no data**: metrics.py says "no data" for the metric this week
- **no measure**: the goal carries none, so the retro can't tell whether it is met

A measure is read from the same metrics.py runs the retro already makes for this week and
the week before; `met_weeks` counts the weeks in a row, back from this one, the goal was
met. The thresholds are flags of `retro.py gather`, not policy keys: a goal is proposed
for retirement after `--met-weeks` (4) weeks met in a row and reported stalled after
`--stalled-weeks` (3) weeks unserved, the defaults the maintainer chose. When a goal has a
measure and `--met-weeks` exceeds 2, gather runs metrics.py for the
earlier weeks too, each with `--until` the later window's start, and runs none when no goal
has a measure.

**Stalled goals:** a goal nothing served (no issue, no pull request) in each of the last
`--stalled-weeks` weeks. A goal whose id first appeared in `docs/product.md` or
`docs/product/` (by `git log` in DIR) less than that many weeks ago is never stalled.

**Off-direction work** (G-5), for both weeks: the issues whose trusted verdict comment
posted in the window reads `Triage: **postponed**: it serves no goal of the direction.`,
and those whose verdict reads `Triage: **won't fix**: it hits N-n`, with the non-goal each
cites and the most-cited `N-n` (ties: the lowest id).

**Unlinked work:** the pull requests merged in the window that metrics.py's agent marks
(`AGENT_MARKS`) call agent-made and whose body has no `## Plan` whose `Serves:` names a
goal the direction lists or `quality bar`. `pr_gate.py` refuses those now, so each one is a
gate that was bypassed or a goal retired after its merge.

The JSON gains one key, `goals`: `{"direction": true, "goals": [{"id", "text", "measure",
"status", "value", "value_text", "met_weeks", "issues", "pulls", "previous": {"issues",
"pulls"}, "stalled", "weeks_unserved"}], "quality_bar": {"issues", "pulls", "previous"},
"off_direction": {"postponed", "wont_fix", "top_non_goal", "previous"}, "unlinked":
[{"number", "title", "url"}]}`. Without `--goals`, the output is as today.

### The retro reports and proposes

`skills/github-ship-watch/SKILL.md`, Weekly retro, gains these steps; the retro stays an
option the user schedules:

1. Gather passes `--goals` and the repo's checkout, fetched and at `origin/<default>`
2. The tracking-issue comment gains a section **Goals**: a row per goal (id, served this
   week and the week before, measure status with its value, stalled), then the quality-bar
   row, the off-direction counts with the most-cited non-goal, and the unlinked pull
   requests. Without a direction it says so in one line
3. The retro proposes a change to the direction as a proposal issue, deduplicated with
   `retro.py dedupe` like its other proposals. Its body cites the week's numbers, links the
   tracking comment, and names the command the maintainer would run (`shipmill product
   retire G-n`, `shipmill product measure G-n "..."`). At most one such issue per goal is
   open at a time; an open one gets a comment only when a week adds evidence. These come on
   top of the at most three proposals for recurring causes, in two cases:
   - A goal met in each of the last `--met-weeks` weeks: titled `Direction: G-n met for N
     weeks`, proposing to retire it or to raise its target
   - A stalled goal: titled `Direction: G-n stalled for N weeks`, proposing to retire it,
     re-word it, or ask for the work that reaches it
4. A high off-direction count or a non-goal cited again and again is reported, never
   proposed on its own: the verdicts already name the goal each request would need, and
   adding a goal is the maintainer's call

The retro never edits `docs/product.md` or `docs/product/`, never runs a `shipmill product`
edit command, and never opens a pull request that changes the direction: only the
maintainer changes it (D-34, N-3).

## Acceptance criteria

- S-027-1: `shipmill product check` accepts a goal followed by `  measure: <metric> <comparison> <target>` with a registry metric, a comparison of `<`, `<=`, `>`, or `>=`, and a target in the metric's unit, in `docs/product.md` and in a Goals section moved to `docs/product/`, and accepts a goal without one
- S-027-2: `shipmill product check` exits 1 naming the file, line, and rule for an unknown metric (listing the known ones), an unknown comparison, a target whose unit doesn't fit its metric or a percentage above 100, a second measure line under one goal, and a measure line under a non-goal, user, or quality-bar item or after a blank line
- S-027-3: `shipmill product show --json` gives every goal a `measure` key, `null` without one and otherwise `metric`, `comparison`, `target` in hours, ratio, or per week, `unit`, and `text`; other sections' items have no `measure` key, and the text output prints each measure line under its goal
- S-027-4: `shipmill product measure <G-n> "<measure>"` writes or replaces the goal's measure line and `--clear` removes it, leaving every other line unchanged, including in a moved Goals section, and exits 2 without writing for an id that isn't a listed goal or a measure `check` refuses
- S-027-5: `shipmill product retire <G-n>` removes the goal's measure line with its item, `shipmill product edit <G-n>` keeps it, and `shipmill product add goals` appends after the last goal's measure line
- S-027-6: `pr_gate.py` reads the goal ids of a direction whose goals carry measure lines, and still stops on any other non-item line in a list section; `specs.py check` accepts a spec serving a goal that carries a measure
- S-027-7: `retro.py gather --goals` without `docs/product.md` in the checkout reports `"direction": false` and exits 0; with a checkout not at `origin/HEAD`, or a direction `shipmill product show` refuses, it exits 2
- S-027-8: `retro.py gather --goals` counts an issue closed as completed in the window under each goal its latest trusted verdict comment names in `Serves:`, or its spec's `serves:` line names when it is a listed build issue, and a merged pull request under each goal its `## Plan` `Serves:` names; a verdict comment by an author that isn't an OWNER, MEMBER, COLLABORATOR, or `--bot` login is ignored, and `quality bar` counts on its own row
- S-027-9: Each goal's status is met, not met with metrics.py's text for the value, no data when metrics.py reports no data, or no measure, compared in the metric's unit (`1d` against 24 hours, `20%` against 0.2), and `met_weeks` counts the consecutive weeks back from this one that the goal was met, running metrics.py for no extra week when no goal has a measure
- S-027-10: A goal is stalled when no issue or pull request served it in each of the last `--stalled-weeks` weeks, and never when its id first appeared in the direction's history fewer weeks ago
- S-027-11: `retro.py gather --goals` lists the window's postponed-for-no-goal and won't-fix-for-a-non-goal verdicts with the non-goal each cites and the most-cited `N-n` (ties to the lowest id), and the agent-made merged pull requests whose plan names no listed goal and not `quality bar`
- S-027-12: The Weekly retro section of github-ship-watch's SKILL.md passes `--goals`, adds the Goals section to the tracking comment, proposes `Direction: G-n met for N weeks` and `Direction: G-n stalled for N weeks` issues deduplicated with `retro.py dedupe`, at most one open per goal, and says the retro never edits `docs/product.md` or `docs/product/`, never runs a `shipmill product` edit command, and never opens a pull request changing the direction
- S-027-13: shipmill-setup offers a measure from the registry for each goal it writes and writes only the measures the maintainer gives, with `shipmill product measure`

## Out of scope

- Measures from outside the forge (downloads, analytics, surveys): a later spec, with a
  source declared in `.github/shipmill.toml`; a goal the forge can't measure carries none
- The agent quality metrics (#384): they join the registry when that issue is built
- A measure's own window: every measure is read over the retro's week; a longer trailing
  window per measure is a later change if weekly values prove noisy
- Planning the work that reaches a goal (#388): this spec reports and proposes a change to
  the direction, never the work
- Goals in `shipmill status` or the fleet report: the retro's comment is the one place
- Changing the direction: only the maintainer does, through the spec 024 commands and a
  pull request they merge
- Measures for shipmill's own goals: building this spec adds none to this repo's
  `docs/product.md`; G-1 to G-7 get a measure only when the maintainer adds it
- Policy keys for the thresholds (an `[agents]` key): the flags of `retro.py gather` hold
  them

## Decisions relied on

- D-4: a later external source would be declared in `.github/shipmill.toml`
- D-29: a verdict comment counts only from a trusted author
- D-34: agents work toward the written direction; only the maintainer changes it

## Issues

- shipmill/shipmill#505: S-027-1, S-027-2, S-027-3, S-027-6
- shipmill/shipmill#506: S-027-4, S-027-5, S-027-13
- shipmill/shipmill#509: S-027-7, S-027-8, S-027-9, S-027-10, S-027-11
- shipmill/shipmill#512: S-027-12

## Verification
