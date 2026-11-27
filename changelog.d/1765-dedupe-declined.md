### Fixed

- `retro.py dedupe` also searches the closed issues by each title's words, and a proposal whose title matches one closed as not planned reads `DECLINED` (a `declined` field in `--json`, exit 1) so the weekly retro no longer reopens a declined `Direction: G-n met` or `stalled` proposal; one closed as completed still reads NEW (#1765)
