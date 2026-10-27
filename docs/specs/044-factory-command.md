# S-044: shipmill factory reports the host's machinery; status keeps to the pipeline

status: built
serves: G-1

## Problem

`shipmill status` answers two questions in one report: whether the factory works and what
waits on whom (issues, pull requests, releases, all read from GitHub), and whether the
machinery on this host is sound (the gate's launchd job and log, the App's key, the plugin
installs, the worktrees). The second half is local to one machine, and any read in it stops
the whole report. On 2026-10-26 `shipmill status` failed on shipmill/shipmill with exit 2
and printed nothing but `gh: This query requests up to 506,520 possible nodes which exceeds
the maximum limit of 500,000`: `watch_state.py` runs `shipmill worktrees --json` for its
`WORKTREE_STALE` row, and the 137 agent worktrees on the gate's host overran GitHub's query
limit (fixed in #709). A report-only row about old worktrees cost the maintainer the verdict
and every queue. On a fresh clone, as `fleet.py report` runs it, the host half has nothing
to read, so the same report means different things on different machines.

## Behaviour

### shipmill status

`shipmill status` (`src/shipmill/status.py`, spec 009) keeps its heading, verdict, and the
lines that read the pipeline: repo, the item lines (needs decision, to triage, to build, in
progress, to land, drafts, parked, and the rest), open issues, pull requests, mode, and
landing. The `gate`, `github app`, and `shipmill` lines are replaced by one `factory` line,
always shown, after landing:

- `factory  OK` when every check of `shipmill factory` but the worktrees passes
- `factory  N problem(s): <the first problem's line>; shipmill factory` otherwise, the
  problems counted the way `shipmill factory` prints them
- `factory  can't check here: <why>` when the host has nothing to check (off a Mac, no
  launchd job for the repo on this Mac), which is no reason for a verdict, as today

The verdict is unchanged: the reasons S-009-3, S-009-4, and S-009-5 take from the host (the
launchd job, its log, the App check, an outdated plugin or CLI, no gate job on this Mac)
still count, now read through the same checks `shipmill factory` runs. A factory check that
fails to run makes the verdict STUCK, with the check's error as the `factory` line's first
problem; it never stops the report.

`shipmill status` never reads worktrees: `watch_state.py` drops `stale_worktrees` and the
`WORKTREE_STALE` row, so github-ship-watch no longer runs `shipmill worktrees`, and needs
`claude` on `PATH` only for the rows that read live sessions.

### shipmill factory

A new command, `shipmill factory` (`src/shipmill/factory.py`, wired in
`src/shipmill/cli.py`), read-only, prints one line per check of this host's machinery for
the repo, a label and a value, in this order:

- **gate**: the `gate` line spec 009 defines (launchd job, interval, last run, last exit,
  the log's last line, `WAITING`, `HELD`, `UNCHANGED`), and the `GATE_SESSIONS_DEAD` and
  `LOOP` facts
- **sessions**: the gate's live sessions (`AGENT_SESSION` rows whose detail starts with
  `gate`), counted, or `none`
- **github app**: the `github app` line spec 009 defines
- **shipmill**: the `shipmill` line spec 009 defines, with the `SHIPMILL_OUTDATED` and
  `SKILL_SHADOWED` fixes after it
- **checkout**: the local default branch against GitHub's, as the repo line reads it
- **worktrees**: `N removable, M kept` from `shipmill worktrees`'s judging, then one line
  per kept shipmill worktree created over 7 days ago, its path, its reason, and the fix
  `stale_fix` gives today (`WORKTREE_STALE`'s content, moved)

Each check runs on its own. A check that fails to run (a `gh`, `git`, `launchctl`, or
`claude` failure, a malformed answer) prints its line as `ERROR: <the error's first line>`,
and the checks after it still run. Exit codes: 0 when every check passes, 1 when a check
finds a problem or fails to run. `--json` prints one JSON object, `{"checks": [{"check",
"ok", "value", "fixes"}]}`, in the same order. Off a Mac the launchd checks read `can't
check here: no launchd`, which is no problem.

### Docs

- `skills/github-ship-watch/SKILL.md`: the `WORKTREE_STALE` row and its paragraph move to a
  pointer at `shipmill factory`
- `skills/shipmill-setup/SKILL.md`, The gate: `shipmill factory` checks the gate's host;
  `shipmill status` is the pipeline
- `README.md` and `docs/install.md`, where they list the commands
- Specs 002 (The report), 009 (Each line: gate, github app, shipmill), and 011, where they
  name the rows and lines this spec moves: a line saying spec 044 moved them

## Acceptance criteria

- S-044-1: `shipmill status` prints a `factory` line after landing and no `gate`, `github
  app`, or `shipmill` line
- S-044-2: the `factory` line reads `OK` when every factory check but the worktrees passes,
  and `N problem(s): <first problem>; shipmill factory` otherwise
- S-044-3: the verdict is the one spec 009 gives for the same host facts (S-009-3, S-009-4,
  S-009-5), read through the factory checks
- S-044-4: a factory check that fails to run makes the status verdict STUCK with its error
  on the `factory` line, and `shipmill status` still prints every other line and exits as
  spec 008 says
- S-044-5: `shipmill status` and `watch_state.py` never run `shipmill worktrees`, and no
  `WORKTREE_STALE` row is printed
- S-044-6: `shipmill factory` prints the gate, sessions, github app, shipmill, checkout, and
  worktrees lines in that order, each with spec 009's values where spec 009 defines them
- S-044-7: the worktrees line counts removable and kept worktrees, and one line follows per
  kept shipmill worktree created over 7 days ago, with its reason and fix
- S-044-8: a factory check that fails to run prints `ERROR: <first line>` and the checks
  after it still run
- S-044-9: `shipmill factory` exits 0 when every check passes and 1 when one finds a problem
  or fails to run
- S-044-10: `shipmill factory --json` prints `{"checks": [...]}` with check, ok, value, and
  fixes per check, in the printed order
- S-044-11: off a Mac, the launchd checks read `can't check here: no launchd` and are no
  problem, in both commands

## Out of scope

- Counting the queues by stage in `shipmill status`: its item lines stay as spec 009 has
  them
- A fleet-wide factory report: `fleet.py report` keeps running `status`'s rows on clones,
  which have no host machinery to check
- Changing what `shipmill worktrees` judges or what the gate's prune removes (spec 002, #709)

## Decisions relied on

- D-55: `shipmill status` reports the pipeline; the host's machinery is `shipmill
  factory`'s, whose checks fail one at a time

## Issues

- shipmill/shipmill#731: S-044-1, S-044-2, S-044-3, S-044-4, S-044-5, S-044-6, S-044-7, S-044-8, S-044-9, S-044-10, S-044-11

## Verification

Checked on the default branch plus #731's change, on the gate's Mac, against
shipmill/shipmill, beyond the tests named.

- S-044-1: `test_s044_1_status_prints_a_factory_line_after_landing_and_no_gate_app_or_shipmill_line`, passing; `shipmill status` on shipmill/shipmill printed `factory` as its last line after `landing`, and no gate, github app, shipmill, or claude auth line
- S-044-2: `test_s044_2_the_factory_line_reads_ok_or_the_problems_with_the_first`, passing
- S-044-3: `test_s044_3_the_verdict_is_spec_009s_read_through_the_factory_checks`, passing, with spec 009's own tests (S-009-3, S-009-4, S-009-5) unchanged and passing
- S-044-4: `test_s044_4_a_check_that_fails_to_run_is_stuck_and_the_report_goes_on` (a launchd plist that isn't one) and `test_s044_4_a_failed_gate_cli_read_is_the_shipmill_checks_error`, passing; #745: `test_s044_4_a_failed_host_section_read_is_its_checks_error_and_the_report_goes_on` (a failing `watch_state.py --host sessions` or `--host shipmill` read, as `claude agents --json` or `claude plugin list` failing), `test_s044_4_the_host_sections_rows_and_exit_code_join_the_pictures`, and `test_s044_4_no_host_leaves_the_host_sections_to_status_and_goes_without_host`, passing
- S-044-5: `test_s044_5_the_watch_never_runs_shipmill_worktrees_nor_prints_worktree_stale`, `test_s044_5_status_reads_no_worktree_row`, and the command list in `test_s044_4_a_check_that_fails_to_run_is_stuck_and_the_report_goes_on`, passing
- S-044-6: `test_s044_6_factory_prints_its_checks_in_order_with_spec_009s_values`, passing; `shipmill factory` on shipmill/shipmill printed gate, claude auth, sessions, github app, shipmill, checkout, and worktrees in that order
- S-044-7: `test_s044_7_the_worktrees_line_counts_and_lists_kept_shipmill_ones_over_seven_days` and `test_s044_7_the_factory_lists_kept_shipmill_worktrees_over_seven_days` (real worktrees), passing; on the gate's host it read `0 removable, 139 kept` with 40 stale lines, each with its fix
- S-044-8: `test_s044_8_a_check_that_fails_to_run_prints_its_error_and_the_rest_still_run` and `test_s044_8_watch_states_host_rows_that_fail_are_the_checks_error`, passing
- S-044-9: `test_s044_9_factory_exits_1_on_a_problem_or_a_failed_check`, passing; the run above exited 1 on the stale worktrees
- S-044-10: `test_s044_10_json_prints_each_check_with_ok_value_and_fixes_in_order`, passing
- S-044-11: `test_s044_11_off_a_mac_the_launchd_checks_cant_check_here_and_are_no_problem`, passing
