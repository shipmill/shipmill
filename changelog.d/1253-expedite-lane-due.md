### Added

- A merge that completes an expedite outcome (the pull request that closed the last open sub-issue of an accepted opportunity whose `expedite` label a person added) makes the stable lane due at once with the reason `expedite #N complete`, or the rc lane when stable promotes, without waiting for `quiet_minutes` or a schedule window; every gate still applies, an outcome a release already shipped makes nothing due again, and a config without `[agents]` reads nothing new (spec 070) (#1253)
