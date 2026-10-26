### Added

- `shipmill gate` and `shipmill status` pass the resolved `[agents.roles]` to the state scripts as one `--role` flag per role, `maintainer` included; `watch_state.py` takes the flags and passes them to `triage_state.py`, the gate's session prompt tells the session to pass the same flags, and the watch and status list a person's item's teams and read a team-only `WITH_PERSON` line (#640)
