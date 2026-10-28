# S-045: The gate's worktree prune runs after the decision, now and then, and never fails a tick

status: built
serves: G-1

## Problem

`shipmill gate` prunes landed worktrees on each tick (spec 002, S-002-15, D-24), and does it
first: `gate()` in `src/shipmill/gate.py` judges and prunes every worktree right after
`check_checkout`, before the hold, busy, and still-working checks, before the checkout's
refresh, and before the state read. A prune error exits 2 like any other gate error
(S-002-16). Two things follow:

- **One prune error stops the factory.** On 2026-10-26 the judge's merged-PR query overran
  GitHub's 500,000-node limit on a host with 137 agent worktrees (fixed in #709, 0.81.1).
  Every tick for about 11 hours exited 2 with `gh api graphql -F failed: ... possible
  nodes` and decided nothing, started nothing, and never refreshed the gate's checkout,
  though the prune is housekeeping and `decide()` reads no worktree
- **Every tick pays for it.** Measured on 2026-10-27 on the same host with 0.81.1, the
  gate's prune took about 57 s of a 180 s tick and about 2,000 `git` calls (836 `git
  patch-id`, 749 `git show`, and the rest), on RUNNING and WAITING ticks too, where nothing
  else in the tick needs it. Spec 044 drops the second run of the same judging, the one
  behind `WORKTREE_STALE`, and leaves this one unchanged

## Behaviour

### When the gate prunes

`gate()` (`src/shipmill/gate.py`) no longer prunes before the hold check. It prunes once the
tick has its decision, whatever the decision is (HELD, BUSY, RUNNING, WAITING, QUIET,
UNCHANGED, LAUNCH, and the rest), after any session it starts has started. A tick that fails
before it reaches a decision prunes nothing.

It prunes only when a prune is due: when `prune.json` in the gate's state directory (next to
`gate.json`) records no attempt, or its last attempt started `prune_hours` or more ago. A new
`[agents]` key, `prune_hours` (`src/shipmill/agents.py`), an integer from 0 to 168 (a
week, the bound `retry_hours` has), defaults to 6; 0 prunes on every tick, as today. A tick that is not due
prunes nothing and prints nothing about it. `shipmill gate --dry-run` reads `prune.json` and
`prune_hours` through the same due check (#763): when a prune is not due it judges nothing
and prints one line, `prune due at <time>`; when it is due, or there is no `prune.json`, it
judges and lists what it would prune as today. Either way it removes nothing and writes no
`prune.json`. Its `--json` `"prune"` object adds `"due": <bool>` and `"at": <when it is due,
or null with no prune.json>`, and a `prune.json` it can't read is the prune's error line,
as on a tick. `shipmill worktrees --prune --dry-run` lists what a prune would remove anytime.

What the prune removes is unchanged (spec 002, D-24): it is `shipmill worktrees --prune`'s
code, and still runs on a held tick, since it starts no session and removes only landed,
clean work.

### A prune that fails

A prune that fails with a shipmill error (a `gh`, `git`, or `claude` failure, an answer
shipmill can't read, a removal git refuses: what `shipmill worktrees --prune` exits 2 on)
no longer fails the tick:

- the text output prints one line, `prune failed: <the error's first line>`, after the
  decision's lines; the `pruned` lines list nothing for that tick
- `--json` gains `"prune": {"ran": <bool>, "error": <first line or null>}`; `"pruned"` keeps
  its meaning and is `[]` on a failed or skipped prune
- the tick's decision, launch, and exit code are the ones it would have without the prune
- a worktree the prune removed before the failure stays removed; S-002-14 still holds for
  `shipmill worktrees --prune`, which keeps exiting 2

Any other exception, a bug, still ends the tick as it does today.

### prune.json

A due prune writes `prune.json` when it ends, success or failure: `{"at": <when it
started>, "ok": <bool>, "error": <first line or null>, "failing_since": <when the current
run of failures started, or null>, "removed": <count>}`. A success clears `failing_since`.
The next attempt is due `prune_hours` after `at`, after a failure as after a success.

### How a failing prune shows

`shipmill factory` (spec 044, D-55) gains a check, **prune**, after worktrees:

- `last ran <at>, removed N` when the last prune succeeded
- `failing since <failing_since>: <error>; fix: shipmill worktrees --prune` when it failed,
  which is a problem
- `never ran here` when there is no `prune.json`, which is no problem; a `prune.json`
  shipmill can't read prints `ERROR: <first line>`, as any check that fails to run

Unlike the worktrees count, the prune check counts in `shipmill status`'s `factory` line, so
a failing prune reads `factory  1 problem(s): prune failing since ...; shipmill factory`.
It changes no verdict: the gate still works, and the worktrees wait.

### Docs

- `skills/shipmill-setup/SKILL.md`, The gate: the gate prunes after its decision, every
  `prune_hours`, and a failed prune shows in `shipmill factory`
- `docs/install.md`, where it lists the `[agents]` keys: `prune_hours`
- Spec 002, under S-002-15 and S-002-16: a line saying spec 045 moved when the gate prunes
  and what a prune error does to a tick

## Acceptance criteria

- S-045-1: a tick that reports HELD, BUSY, or RUNNING with a due prune prunes after its
  decision, and a prune that removes a worktree prints its `pruned` line after the decision's
  lines
- S-045-2: a tick whose prune would fail still reaches its decision and starts its session:
  with the prune's `gh` failing, a LAUNCH tick launches
- S-045-3: a tick that fails before its decision prunes nothing
- S-045-4: a tick prunes only when `prune.json` records no attempt or one `prune_hours` or
  more ago, and `prune_hours = 0` prunes on every tick
- S-045-5: `[agents] prune_hours` defaults to 6 and the config refuses a value that is not an
  integer from 0 to 168
- S-045-6: a prune that fails with a shipmill error prints `prune failed: <first line>`,
  lists no `pruned` path, and leaves the tick's decision and exit code as they would be
  without it
- S-045-7: `shipmill gate --json` prints `"prune": {"ran", "error"}`, with `ran` false on a
  tick that is not due
- S-045-8: a due prune writes `prune.json` with at, ok, error, failing_since, and removed; a
  success clears failing_since, and a failure after a failure keeps the first one's
- S-045-9: `shipmill gate --dry-run` follows the prune's schedule: not due, it judges no
  worktree and prints `prune due at <time>`; due, it lists what it would prune; either way
  it removes nothing and writes no `prune.json` (#763)
- S-045-10: `shipmill factory` prints a prune line after worktrees: `last ran`, `failing
  since ...` as a problem, or `never ran here`
- S-045-11: a failing prune counts as a problem on `shipmill status`'s `factory` line and
  leaves the verdict as it is

## Out of scope

- What the prune judges and removes, and how fast the judging is (spec 002, D-24, #709): a
  cheaper judge, such as skipping worktrees whose verdict cannot have changed, is its own
  change
- `shipmill worktrees --prune`'s exit codes (S-002-11, S-002-14): run by hand, it still
  exits 2 on an error
- A `shipmill factory --prune`: `shipmill factory` stays read-only (spec 044); the fix it
  names is `shipmill worktrees --prune`
- `watch_state.py`'s other sections failing on their own (a `<SECTION>_UNREADABLE` row in
  place of exit 2, S-008-11): the gate decides from those rows, and a section read as empty
  could hide work from `decide()`; spec 044 already removes the one report-only section that
  read worktrees. Left for its own spec if a second report-only section fails the same way
- A notification for a failing prune: it is shown on `shipmill factory` and `shipmill
  status`, and stops no work

## Decisions relied on

- D-24: the gate's prune owns a worktree once its session has exited, and removes only what
  the checks prove landed
- D-55: `shipmill status` reports the pipeline; the host's machinery is `shipmill factory`'s
- D-56: the gate's prune runs after the tick's decision, every `prune_hours`, and a prune
  error never fails a tick

## Issues

- shipmill/shipmill#741: S-045-1, S-045-2, S-045-3, S-045-4, S-045-5, S-045-6, S-045-7, S-045-8, S-045-9, S-045-10, S-045-11

## Verification

Checked on the default branch plus #731's and #741's changes, by the tests named, all
passing; `shipmill factory` on shipmill/shipmill printed `prune  never ran here` after its
worktrees line, since no gate of this version had pruned there yet.

- S-045-1: `test_s045_1_a_held_waiting_or_running_tick_prunes_after_its_decision`, `test_s045_1_a_launch_prints_its_pruned_line_after_the_launch`
- S-045-2: `test_s045_2_a_launch_tick_whose_prune_fails_still_launches`
- S-045-3: `test_s045_3_a_tick_that_fails_before_its_decision_prunes_nothing`
- S-045-4: `test_s045_4_a_tick_prunes_only_when_prune_hours_have_passed`, `test_s045_4_prune_hours_0_prunes_on_every_tick`
- S-045-5: `test_s045_5_prune_hours_defaults_to_6_and_accepts_0_to_168`, `test_s045_5_the_config_refuses_a_prune_hours_that_is_not_an_integer_from_0_to_168`
- S-045-6: `test_s045_6_a_failing_prune_prints_its_first_line_and_changes_nothing_else`, `test_s045_6_a_removal_git_refuses_is_the_prunes_error`, `test_s045_6_any_other_exception_still_ends_the_tick`
- S-045-7: `test_s045_7_json_prints_whether_the_prune_ran_and_its_error`
- S-045-8: `test_s045_8_prune_json_records_each_attempt_and_the_first_failure`, `test_s045_8_a_malformed_prune_json_is_the_prunes_error_and_stays`
- S-045-9: `test_s045_9_a_dry_run_whose_prune_is_not_due_judges_nothing_and_says_when_it_is_due`, `test_s045_9_a_dry_run_tick_whose_prune_is_not_due_lists_nothing`, `test_s045_9_a_dry_run_whose_prune_is_due_lists_what_it_would_prune_and_writes_nothing`
- S-045-10: `test_s045_10_factory_prints_a_prune_line_after_worktrees`; on shipmill/shipmill, `never ran here`
- S-045-11: `test_s045_11_a_failing_prune_counts_on_the_factory_line_and_keeps_the_verdict`
