### Added

- `shipmill project add|focus|unfocus|resume <n> --by <login>` record the maintainer's move on a project as a relay, then move its label (`project`, `focus`, `held`), and `shipmill project hold` now labels the head `held` after its comment; each refuses a move the head's reader wouldn't count, and `resume` waits for a free slot under `[agents] projects` (spec 108, #1810)
