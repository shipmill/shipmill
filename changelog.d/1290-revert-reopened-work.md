### Added

- `triage_state.py` reads an issue a revert reopened as work again: with the `--bot-login`'s `<!-- shipmill:reverted #N by #R -->` comment, the merged #N no longer makes it DONE_NOT_CLOSED while #R stands; it reads BLOCKED while #R is open and its other state, with `#N:reverted` in its note, once #R merged (#1290)
