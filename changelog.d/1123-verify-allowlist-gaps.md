### Fixed

- `shipmill.verify` now meets a verification command as a headless session does: the commands inside `$(...)` and backticks are judged against the allowlist too (one it can't read is denied, never run), `settings.local.json` is read from the checkout the sessions start in, the wrappers `timeout`, `nohup`, `nice`, `command`, and `xargs` are stripped before a rule matches, the delivery hook gets each part in the directory a `cd` before it set, and a run never waits on a child holding stderr and leaves no child behind (#1123)
