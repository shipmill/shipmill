### Added

- `watch_state.py`'s full report prints a report-only `GOALS` row with each goal's measure reading (status, value, weeks met, its spec 106 state, stalled weeks), and a `DIRECTION_DUE` action for a goal met for 4 weeks or stalled whose `Direction:` proposal isn't open or declined by a trusted author; the gate hands it in tier 7 right after PLANS, from the sweep, and a malformed `goal-report` line stops the watch with exit 2 (spec 110) (#1839)
