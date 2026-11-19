### Added

- `fleet.py queue` lists an open spec pull request that nothing lands by itself as a `SPEC_TO_MERGE` row, read with `pr_gate.py`'s readers: no question waiting, no trusted answer taking every recommendation, and no App decided comment at `accepted-spec`, or one that edits the product's direction; github-ship-watch's Fleet section documents the queue, its rows, and a `/schedule` routine for it; spec 069 is built (#1246)

### Fixed

- `fleet.py report` and `queue` read a `PRS_OPEN` row that carries its pull requests' heads instead of refusing it as not a row (#1246)
