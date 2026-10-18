### Changed

- `shipmill init` writes a stable lane that releases after every batch of merges (`quiet_minutes = 30`), with no `promote_from`, `min_soak_days`, `schedule`, or `milestone`, and the rc lane only as comments, so the `release.yml` it derives has no schedule; `shipmill upgrade --apply stable-every-batch` takes `min_soak_days` out of `[lanes.stable]`, keeps `promote_from`, and adds `quiet_minutes = 30` only to a table with no trigger, every other byte left as it was (#461)
