### Fixed

- `shipmill status --item`, `shipmill queue` and `status --summary` read a goal plan the maintainer accepted, with items still to file (`PLAN_ACCEPTED`), as product intake's: it waits on an agent to file its items, not on the maintainer's answer (#1707)
