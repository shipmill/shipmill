### Added

- `triage_state.py` reads an issue labelled `decided` whose decided marker is followed by a trusted comment starting `veto`, and no newer `<!-- shipmill:veto-handled -->` comment, as `VETOED`, an action read right after `DECIDED`, for closed issues updated in the last 14 days too; `watch_state.py` lists such issues and pull requests, open, closed, or merged, in a `VETOED` row that starts a gate session (spec 030, S-030-14 to S-030-16) (#608)
