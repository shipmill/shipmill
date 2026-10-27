### Changed

- Gate: a tick checks GitHub for a change first (one GraphQL query and one read of the newest runs, against the cursor in `cursor.json`) and reads nothing more when nothing changed; on a change it walks the eight work tiers in order and hands a session the first item no session was handed within `retry_hours` (`handed.json`), with its tier and fix line, so one stuck item never holds back the next. The timed sections come from a sweep every `[agents] sweep_hours` (default 6); `--json` adds `walk` and `item`, and `--walk` and `--sweep` force them (spec 046, #757)
