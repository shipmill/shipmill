### Added

- The policy reads an optional `[downstream]` section: the App id, a run timeout, and one table per downstream repository (`repo`, `workflow`, `ref`, `report_only`, `timeout_minutes`), refusing a malformed one with exit 2 naming the key; nothing runs on it yet (#503)
