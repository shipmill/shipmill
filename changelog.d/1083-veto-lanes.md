### Added

- `[gates] veto_lanes` in `.github/shipmill.toml` names the lanes whose release will wait for the veto window of each notify decision it ships (spec 059, empty by default; `hotfix` is refused); a lane it names gets the hourly tick, so `shipmill doctor`'s `schedule` check warns when `release.yml` lacks it, and doctor prints a `gates` line naming the lanes, a warning without `[agents] app_id` (#1083)
