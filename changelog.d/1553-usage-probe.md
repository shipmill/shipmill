### Added

- Gate: while a usage limit pauses the sessions' credential, each tick runs `claude -p "/usage"`, which calls no model, with that credential (the token file's token as `CLAUDE_CODE_OAUTH_TOKEN`, never the host login), and lifts the pause on the first tick whose output shows every window under 100% used; one showing a window full holds it. When the probe exits non-zero, doesn't answer in 60 s, or its output names no window, the pause lifts at the log's `resetsAt`, or after `retry_hours` without one (#1553)
