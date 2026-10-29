### Added

- `shipmill gate` says why a tick failed where status can read it: every real tick writes `tick.json` beside `gate.json` with its decision, or `ERROR` and a shipmill error's first line, its fix, and since when and how many ticks in a row failed; a failing tick (`CLAUDE_AUTH`, now the login's too, `GITHUB_AUTH`, `HOOKS_FAILED`, or a shipmill error) exits 2, every other tick 0 (#816)
