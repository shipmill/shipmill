### Fixed

- `intake_state.py --plans` reads spec 027's goal report (`retro.py gather --goals`): a goal the report reads stalled gets a `stalled` plan, waiting for room under `--wip` like `no-work`, a goal whose measure it reads met gets no `no-work` plan, and a report that can't be read exits 2 (#1764)
