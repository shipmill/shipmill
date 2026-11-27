### Fixed

- `shipmill status --item <n>` reads no plan, goal, or retro for an item that isn't a plan, a goal proposal, or an opportunity: `watch_state.py --item` runs `intake_state.py` with `--projects` alone, and starts its intake and triage reads before the default branch's fetch. On a repo with 120 open items a project head's answer took 17 to 19 seconds and about 22 GraphQL points instead of 405 seconds and 398 (#1831)
