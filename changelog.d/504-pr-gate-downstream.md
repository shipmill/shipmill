### Added

- Tests prove the PR gate reads a `downstream: <name>` check like any check: `FAILURE`, `TIMED_OUT`, and `ACTION_REQUIRED` fail it, a running one keeps it pending, and `NEUTRAL` and `SUCCESS` count as green (#504)
