### Added

- A stable release by a lane with `close_milestone = true` closes the open milestone titled its version once tagged and published, first moving its open issues to the open milestone titled the lowest stable version above it; with open issues and no such milestone it writes nothing. The Release run's summary says `milestone 1.5.0 closed; #12, #14 moved to 1.6.0`, and a milestone write that fails fails the land job after the release, naming the `shipmill gh api` command that does it (spec 068) (#1335)
