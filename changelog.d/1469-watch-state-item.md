### Added

- `watch_state.py --item N` prints only the full report's rows `shipmill status --item N` reads (HOLD, NEEDS_DECISION, PRS_OPEN, PRS_PARKED, and the agent and GATE_IDLE rows naming #N), exactly as the full report prints them, skipping the sections none of them can come from and reading the rest at once (#1469)

### Fixed

- `shipmill status --item REF` for an open issue or pull request takes about a third of the time it did (about 23 s, from about 62 s, on shipmill/shipmill): it passes `--item` to `watch_state.py`, so the chains, the deployments, the active runs, the work branches, the tags, and the other sections no row of the item comes from are no longer read; its output is unchanged (#1469)
