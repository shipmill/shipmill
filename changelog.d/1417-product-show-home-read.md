### Fixed

- A component whose product home can't be read no longer stops the weekly retro or product intake's plans: `retro.py --goals` and `intake_state.py --plans` read the repo's own goals with `shipmill product show --local`, as they only ever used those, and every failure of `product show` still exits 2 (#1417)
