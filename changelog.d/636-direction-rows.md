### Added

- The watch asks for a missing direction: for a repo with `[agents]`, `watch_state.py` reports DIRECTION_MISSING (an action for the maintainer) when the default branch has no `docs/product.md` or `shipmill product check --ref` refuses it, and DIRECTION_PENDING (an agent's) with what a session does on the direction question; a closed direction issue is a decline, noted in TRIAGE_MODE, and `triage_state.py` marks a direction issue's `--json` line so the watch keeps it out of the issue rows with no read of its own (#636)
