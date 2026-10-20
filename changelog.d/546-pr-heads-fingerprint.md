### Fixed

- `shipmill gate` with `[agents] prs = true` starts a session when a push lands on an open pull request a session already looked at, instead of waiting out `retry_hours`: `watch_state.py --json` adds each listed pull request's head SHA to its `PRS_OPEN` row, and the gate's fingerprint counts it (#546)
