### Added

- `shipmill gate` stops a hung headless session: one whose log hasn't grown for the new `[agents] stall_minutes` (30 by default, 0..1440, 0 never) reads `STALLED`, gets SIGTERM to its process group while its start time still matches `gate.json`, starts nothing, and its item is retried after `retry_hours`; `shipmill gate --json` adds `running` (session, item, minutes, `log_grew`) on RUNNING and STALLED (#815)
