### Added

- An expedite outcome is taken first (spec 070): with `[agents]`, `watch_state.py --tier 3` and `--tier 6` mark as expedite the rows naming an accepted opportunity whose `expedite` label a person added, one of its sub-issues, or a pull request closing one, and the gate's walk takes them before every standard row of the tier; `triage_state.py --wip N` lists those issues first among the ready ones and counts them in progress like any other (#1250)
