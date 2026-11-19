### Added

- The watch's full report, for a config with `[trends]`, runs `trends.py` and adds a DRIFT row for each series at the `report` tier, with its diagnosis and the `trends.py` command as its fix; the row is reported and never acted on: it leaves the exit code as it was, no `--tier` or `--sweep` read prints it or runs `trends.py`, and `--no-trends` leaves the read out. `fleet.py report` lists it among a repo's report-only rows, and github-ship-watch's skill documents the four agent quality measures and a new Trends section (S-078-16 to S-078-18) (#1295)
