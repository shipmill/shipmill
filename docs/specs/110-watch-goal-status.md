# S-110: The watch report shows each goal's measure status and a goal due for a direction proposal

status: built
serves: G-7

## Problem

G-7 asks that the loop know whether each goal is met and each measure held, and propose
changing the direction when it is. Spec 027 built the report that says so (each goal's
measure met, not met, no data, or no measure, the weeks in a row it was met, and whether it
stalled), but only the weekly retro reads it, and the retro is a routine the user has to
`/schedule` (github-ship-watch's Weekly retro). A repository whose maintainer never
scheduled it, this one included, has no reader of the report: nobody sees that G-1's measure
has held for a month, and no `Direction: G-n met for N weeks` proposal ever opens.

This is W-4 of the accepted plan shipmill/shipmill#566 (Plan for G-7), filed as
shipmill/shipmill#1770. The plan's Order puts it after W-2 (shipmill/shipmill#1764:
`intake_state.py --plans` reads spec 027's report, so a stalled goal gets a plan and a met
goal stops getting one), "so the watch and intake read one report the same way", and says W-4
"makes the goal report part of the loop, not an optional routine". The plan's Notes record
that W-4 changes spec 027's choice that the retro is an option the user schedules, and that
this spec states it: the goal report and the direction proposals move into the watch, which
the gate already runs on every sweep; the rest of the retro stays an option.

Spec 106 already gives the watch each goal's state (GOAL_WRITTEN, GOAL_PLANNED, GOAL_MET,
GOAL_DROPPED, GOAL_OVERDUE) for a goal of kind goal, in an `--item` read and through the
PLANS row's GOAL_OVERDUE action. It reads no measure: a goal's state is the maintainer's
record and its horizon, never the metric under it. This spec adds the measure's reading
beside it and builds on spec 106's rows rather than repeating them.

## Behaviour

### One report, read once

`skills/product-intake/scripts/intake_state.py --plans --goals --json` gains one line per
goal of the direction, in the direction's order, with `"kind": "goal-report"`, read from the
same spec 027 report that its `stalled` and met triggers read after shipmill/shipmill#1764,
in the same run: the report is computed once per run, never a second time for these lines.
Each line carries:

- `goal`: the id (`G-n`)
- `goal_kind`: the goal's `kind` from `product show --json` (spec 105): `"goal"`,
  `"measure"`, or null
- `status`: spec 027's `met`, `not met`, `no data`, or `no measure`
- `value_text`: metrics.py's text for the value (`p90 1.2 d`), null for `no measure`
- `met_weeks`: the weeks in a row back from this one the measure was met, up to `--met-weeks`
- `stalled` and `weeks_unserved`: as spec 027's report gives them
- `ended`: the goal's `state` from `product show --json` (spec 106: `"met"`, `"dropped"`, or
  null)

The thresholds are the report's defaults, `--met-weeks` 4 and `--stalled-weeks` 3 (spec
027); `intake_state.py` passes the same values its triggers use. Without `docs/product.md`
there are no such lines, as there are no plan rows. A report that can't be read stops the
run with exit 2 naming what failed, as #1764 has it for the triggers; it never reads as
`no data`. The text output prints none of these lines.

### The GOALS row

`skills/github-ship-watch/scripts/watch_state.py` already runs intake with `--plans --goals
--projects` (spec 106) on a sweep. It reads the `goal-report` lines from that run and prints
one report-only row, `GOALS`, in the full report: one entry per goal, in the direction's
order, separated by `; `:

    GOALS  G-1 met (p90 1.2 d), 4 weeks; G-2 not met (7%); G-3 no measure, written; G-5 no measure; G-6 no measure, planned, stalled 3 weeks

- `G-n <status>`, then ` (<value_text>)` when it has one, then `, <K> weeks` when `met_weeks`
  is above 0
- For a goal of kind goal, `, <state>` from its spec 106 GOAL_* row in the same run
  (`written`, `planned`, `overdue`, `met`, `dropped`), so a goal's check-based state stands
  beside its measure reading
- `, stalled <N> weeks` when `stalled` is true, N being `weeks_unserved`

The row adds nothing to the exit code, is no agent's row, and is in no `--tier` or `--sweep`
read: the maintainer reads it, and a session starts only from DIRECTION_DUE below. A repo
without `docs/product.md` has no GOALS row (DIRECTION_MISSING, spec 034, covers a repo with
`[agents]` that lacks one). The watch checks each `goal-report` line as it checks spec 106's
rows: a status outside the four, a missing key, a goal id `GOAL_ID` doesn't match, or a
`met_weeks` or `weeks_unserved` that isn't a non-negative integer stops the watch with exit 2,
naming the line, as for any row intake could not print.

### The DIRECTION_DUE row

A goal is due for a direction proposal, in the two cases of spec 027's Weekly retro step 4:

- **met**: a goal with a measure line (`status` is `met`, `not met`, or `no data`) whose
  `met_weeks` reached `--met-weeks`: `G-n met for 4 weeks`
- **stalled**: a goal of kind goal or of no kind whose `stalled` is true: `G-n stalled for
  3 weeks`. A standing measure (kind measure) is never stalled for this row: spec 105 plans it
  only on request, so weeks with no work serving it are its normal course

A goal whose `ended` is `met` or `dropped` is never due. A goal met and stalled at once is
due once, as met, as the retro does.

`watch_state.py` prints the due goals as one row, `DIRECTION_DUE`, `G-1 met for 4 weeks;
G-6 stalled for 3 weeks`, an action (exit 1) and an agent's row, except a goal already
proposed: one with an issue titled `Direction: G-n met for N weeks` or `Direction: G-n
stalled for N weeks` (N the flag's value, the titles the retro opens) that is open, or that is
closed as not planned (a decline, D-10), read by the rule `retro.py dedupe` applies once
shipmill/shipmill#1765 is built (DUPLICATE or DECLINED). Only an issue opened by an OWNER,
MEMBER, or COLLABORATOR or by the `--bot-login` counts; one by anyone else leaves the goal
due. The titles are read with one `gh issue list --state all --search` per sweep, and only
when a goal is due. An issue closed as completed doesn't count, so a goal still met after the
maintainer acted on a proposal (a raised target that still holds) is proposed again.

`src/shipmill/walk.py` places DIRECTION_DUE in tier 7 right after PLANS and adds it to
`SWEPT`, so it runs only on a sweep and its tier reads the sweep's stored rows (D-58); the
gate starts one session for the row. With `--trusted-only` the row is unchanged: it names
goal ids of the default branch's direction and no outsider's text (D-16).

### The session

`skills/github-ship-watch/SKILL.md` gains a DIRECTION_DUE step: for each goal the row names,
open its proposal issue as the App, as the Weekly retro's step 4 says: titled as above, its
body citing the goal's reading from the GOALS row (status, value, weeks met or unserved),
naming the command the maintainer would run (`shipmill product retire G-n`, `shipmill
product measure G-n "<metric> <comparison> <target>"`, `shipmill product met G-n`), and saying
the direction changes only by the maintainer. It checks the title with `retro.py dedupe`
first and opens nothing on a DUPLICATE or DECLINED. It writes nothing else: no tracking-issue
comment, no edit of `docs/product.md` or `docs/product/`, no `shipmill product` edit command,
and no pull request (D-34, N-3). The proposal is an issue, no work in progress, so it takes no
room under `[agents] wip` (D-32).

The Weekly retro section says the watch now reads the goal report and opens the direction
proposals on its own, so a repo needs no scheduled retro for them; a scheduled retro still
reports the Goals section in its tracking comment, and its step 4 finds the watch's issue
through `retro.py dedupe`. The rest of the retro (metrics beside last week's, rule proposals,
decision-policy proposals, the review records) stays an option the user schedules. This
changes spec 027's "the retro stays an option the user schedules" for the goal report and the
direction proposals only. `docs/flow.md` lists the two rows where it lists the watch's goal
rows.

## Acceptance criteria

- S-110-1: `intake_state.py --plans --goals --json` on a checkout with `docs/product.md` prints one `"kind": "goal-report"` line per goal of the direction, in its order, carrying `goal`, `goal_kind`, `status` (`met`, `not met`, `no data`, or `no measure`), `value_text`, `met_weeks`, `stalled`, `weeks_unserved`, and `ended`, read from the same report run its `stalled` trigger reads (one report per run), and prints none without `docs/product.md` or in its text output
- S-110-2: when the goal report can't be read, `intake_state.py --plans --goals` exits 2 naming what failed and prints no `goal-report` line reading `no data` in its place
- S-110-3: `watch_state.py`'s full report prints a `GOALS` row with one `; `-separated entry per goal in the direction's order, as `G-n <status>`, ` (<value_text>)` when it has one, `, <K> weeks` when `met_weeks` is above 0, `, <state>` from the goal's spec 106 row for a goal of kind goal, and `, stalled <N> weeks` when stalled; a repo without `docs/product.md` has no GOALS row
- S-110-4: the GOALS row adds nothing to the exit code, is no agent's row, and is in no `--tier` or `--sweep` read
- S-110-5: `watch_state.py` exits 2 naming the line for a `goal-report` line with a status outside the four, a missing key, a goal id that isn't `G-<n>`, or a `met_weeks` or `weeks_unserved` that isn't a non-negative integer
- S-110-6: a goal with a measure line whose `met_weeks` reached 4 reads `G-n met for 4 weeks`, and a goal of kind goal or of no kind whose `stalled` is true reads `G-n stalled for 3 weeks`, in a `DIRECTION_DUE` row that is an action (exit 1) and an agent's row; a goal of kind measure is never due as stalled, a goal whose `ended` is `met` or `dropped` is never due, and a goal both met and stalled is listed once, as met
- S-110-7: a due goal leaves the DIRECTION_DUE row while an issue titled `Direction: G-n met for N weeks` or `Direction: G-n stalled for N weeks`, opened by an OWNER, MEMBER, or COLLABORATOR or the `--bot-login`, is open or closed as not planned; the same title by another author, or closed as completed, leaves it due, and the titles are read with one issue list per sweep only when a goal is due
- S-110-8: `walk.py` places DIRECTION_DUE in tier 7 right after PLANS and in `SWEPT`, and `shipmill gate` starts a session for a DIRECTION_DUE row read from the sweep
- S-110-9: github-ship-watch's SKILL.md gives DIRECTION_DUE's step (open each named goal's `Direction:` issue as the App after `retro.py dedupe`, its body citing the goal's reading and the command the maintainer would run, and no other write, no direction edit, no `shipmill product` edit command, no pull request), and its Weekly retro section says the watch opens the direction proposals without a scheduled retro while the rest of the retro stays an option the user schedules
- S-110-10: `docs/flow.md` gives the GOALS and DIRECTION_DUE rows, and spec 027's choice that the retro is an option the user schedules is stated there as changed for the goal report and the direction proposals

## Out of scope

- Running a goal's check (the prose `Check:` of a goal of kind goal): spec 106 reads it again when a planned goal's last project closes; the GOALS row shows that goal's state, never a check's result
- Making the whole weekly retro due from the watch (the tracking comment, rule proposals, decision-policy proposals): it stays an option the user schedules
- Thresholds as policy keys: `--met-weeks` and `--stalled-weeks` keep spec 027's defaults, 4 and 3; an `[agents]` key is a later change
- Goals in `shipmill status --item G-n`, `fleet.py`, or `shipmill queue`: `--item` keeps spec 106's state, and a measure's reading there is a later change
- Measures read from outside the forge (shipmill/shipmill#1446), and a goal's measure line on a goal of kind goal (spec 105 refuses it)
- Changing the direction: the session only proposes; only the maintainer edits `docs/product.md` (D-34)

## Decisions relied on

- D-10: a declined proposal is not proposed again
- D-16: the row names only the default branch's goal ids; a proposal issue counts only from a trusted author or the App
- D-32: the proposal is an issue, not work in progress under `[agents] wip`
- D-34: only the maintainer changes the direction; the session opens an issue, never an edit
- D-58: DIRECTION_DUE is a timed section of tier 7, read on a sweep from the same intake run as PLANS
- D-62: the proposal issue carries the agent marker, so it is no filing of the maintainer's

## Issues

- shipmill/shipmill#1838: S-110-1, S-110-2
- shipmill/shipmill#1839: S-110-3, S-110-4, S-110-5, S-110-6, S-110-7, S-110-8
- shipmill/shipmill#1840: S-110-9, S-110-10

## Verification

Checked on the default branch plus #1840's pull request: the code of `intake_state.py`'s
`goal-report` lines, `watch_state.py`'s GOALS and DIRECTION_DUE rows, and `walk.py`'s tier 7
read, the skill's and `docs/flow.md`'s text read, and the tests `specs.py coverage --spec 110`
lists, all passing. Neither script's GitHub reads were checked against a live repository
beyond the tests: their forge and spec 027's report are scripted there.

- S-110-1: `test_s110_1_*` reads one `goal-report` line per goal in the direction's order with its eight keys, the report run once per run whether or not a trigger reads it, and no line without `docs/product.md` or in the text output, holds
- S-110-2: `test_s110_2_*` reads exit 2 naming what failed for a report that can't be read, a line the report doesn't carry, and a goal it leaves out, with no `no data` line printed, holds
- S-110-3: `test_s110_3_*` reads the GOALS row's entries in the direction's order, each goal of kind goal with its spec 106 state, and no row without a `goal-report` line, from intake_state.py's own lines, holds
- S-110-4: `test_s110_4_*` reads GOALS leaving the exit code at 0, outside `AGENT`, and in no `--tier` or `--sweep` read, which prints DIRECTION_DUE alone, holds
- S-110-5: `test_s110_5_*` reads exit 2 naming the line for a status outside the four, a missing key, a goal id that isn't `G-<n>`, and a week count that isn't a non-negative integer, and a well-formed line read, holds
- S-110-6: `test_s110_6_*` reads `G-1 met for 4 weeks; G-6 stalled for 3 weeks` in an action and agent's row, no stalled measure and no ended goal due, and a goal met and stalled listed once as met, holds
- S-110-7: `test_s110_7_*` reads a trusted open or declined proposal under either title leaving the row, an outsider's or a completed one leaving the goal due, one search only when a goal is due, and an unreadable search line stopping the watch, holds
- S-110-8: `test_s110_8_*` reads DIRECTION_DUE right after PLANS in tier 7 and in both `SWEPT` sets, and a gate tick launching a session for it from the stored sweep, holds
- S-110-9: `test_s110_9_*` reads the skill's Direction proposals step deduping both titles as `watch_state.direction_titles` spells them before opening the issue as the App, the body's reading and the three commands, the writes it never makes, the DIRECTION_DUE row pointing at the step, and the Weekly retro leaving the direction proposals to the watch while the rest stays an option the user schedules, holds
- S-110-10: `test_s110_10_*` reads `docs/flow.md`'s Goals, plans, and projects giving the GOALS and DIRECTION_DUE rows, the titles, tier 7 after PLANS, and the change to spec 027's choice for the goal report and the direction proposals only, holds
