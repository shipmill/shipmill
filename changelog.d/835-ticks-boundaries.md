### Changed

- Tests: the schedule check's reading of a workflow's crons is pinned at its boundaries (minute 60, hour 24, weekday 7 as Sunday), `needed` at the 366 days after the given date, and a policy window at `24:00` or `07:60` at its `is not a time of day` error (#835)
