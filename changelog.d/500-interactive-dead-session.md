### Fixed

- An interactive gate session (`claude --bg`) that `claude agents` lists as `failed`, or as `done` within 60 seconds of its launch, no longer counts as an attempt toward `retry_hours`: the next tick reads `SESSION_DEAD`, names the session and its state with `claude logs <id>` as the fix, starts another, and holds the same findings for `retry_hours` after 3 dead in a row, as a headless one does (#500)
