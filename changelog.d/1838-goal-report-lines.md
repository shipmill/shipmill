### Added

- `intake_state.py --plans --goals --json` prints a `goal-report` line per goal of the direction, in its order, with the goal's kind, its measure's status and value, the weeks met in a row, whether it stalled, and whether it ended, read from the one spec 027 report its plan triggers read; a report that can't be read exits 2 (spec 110) (#1838)
