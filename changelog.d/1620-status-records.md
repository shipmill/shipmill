### Added

- `shipmill status --summary --json` lists each open issue and pull request with its holder, why, what clears it, what it waits on, and whether it is an opportunity or plan to accept, built by the same code as `status --item --json`, which now carries the same fields; `status --summary --host [--json]` summarizes every gate job's repo on this host from its checkout, so tools read one JSON instead of parsing the text or the gate's files (spec 094) (#1620)

### Changed

- `shipmill status --summary` splits "waits on nobody" into waits on people (an assignee, the reporter), waits elsewhere (another repo's item, an upstream report, labelled blocked), postponed (postponed, or a parent moving through its children), and nobody; its JSON and `status --item --json` carry `"schema": 1`, and each condition its `holder` (spec 094) (#1620)
