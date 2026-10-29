### Changed

- A RUNNING tick names the session's item, how long it has run, and, for a headless session, how many minutes ago its log last grew; `gate.json` records the launch's item, and one written before reads `item not recorded`. Headless sessions start with `--output-format stream-json --verbose`, so their log grows while they work, and a session ended with a result only when its log's `result` event has `is_error` false; a log written before is read as before (S-048-14, S-048-15, S-048-17) (#814)
