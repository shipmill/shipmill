### Changed

- product-intake's `intake_state.py --plans` reads a comment by the `--bot-login` whose first line is the needs-decision relay (``Decision by `@<login>`, relayed by Claude Code``) as the maintainer's answer to a goal plan when the login is a maintainer given with the new `--role` flags, newer than the plan's newest revision, its accept, decline, or edit read from the next line; `watch_state.py` passes its `--role` flags through, and the skill relays an answer given in the session (D-68) (#917)
