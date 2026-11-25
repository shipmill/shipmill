### Added

- `shipmill queue [--json] [--fleet]` says who holds each open issue and pull request of a gated repo, why, what clears it, what it waits on, and whether it is an opportunity or plan to accept, built from one read of the repo's facts by the same code as `status --item`; holders are finer than `status --summary`'s four lines (waits on people, waits elsewhere, postponed), the JSON carries `"schema": 1`, and `--fleet` reads every gate job on this host one repo at a time, stopping once GitHub's rate limit is reached (spec 094) (#1620)

### Changed

- `shipmill status --item --json` carries `"schema": 1`, a `holder` on each condition, and the same `holder`, `via`, `accept`, `why`, `clears`, and `waits_on` as `shipmill queue`'s record of the item; `status --summary` reads the open pull requests' checks in one read rather than one per pull request (spec 094) (#1620)
