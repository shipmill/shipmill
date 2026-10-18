### Added

- `shipmill status` reports MILESTONE_WAITING, with its reasons, while a lane with `milestone = true` has a milestone with no open issues whose specs aren't built or shipped, and MILESTONE_OVERTAKEN, with the rename to the version the lane cuts next, when a stable tag of an open milestone's version exists while the milestone has open issues; both are read with the release's own planner, which no milestone changes the bump of (spec 022) (#398)
