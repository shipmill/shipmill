### Fixed

- `shipmill status --summary` no longer pairs a `SESSION_DEAD` verdict with the session the gate started after it: the gate line names the dead session by its own id, then the one started since, and `--json` carries the dead one as `dead` (#1668)
