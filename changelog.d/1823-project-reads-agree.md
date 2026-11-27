### Fixed

- `shipmill status --item` no longer reads a started project's head as waiting on its own check issue: the check issue waits on the head's work, then the head on its due check, and `intake_state.py --projects` reads a head whose `Part of #<head>` pull requests merged as closing, so it stops counting against `[agents] projects` (spec 106, S-106-30)
