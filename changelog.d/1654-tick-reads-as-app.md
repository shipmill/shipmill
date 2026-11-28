### Changed

- Gate: with `[agents] app_id` set, a tick's own GitHub reads (the hold check, the change check, the subjects' reads, and each tier and sweep of `watch_state.py`) run as the App with the tick's read token, in each read command's environment, so they draw on the App's rate limit, not the maintainer's; `gh api user` and the sessions never get it. A failed mint reads as the host and the tick's line ends `; reads as host: <why>`; `tick.json` and `shipmill gate --json` record `reads_as` (#1654)
