### Added

- `[agents] outcomes` in `.github/shipmill.toml`: the most outcomes (open opportunities) the product keeps in flight at once, from 1 up to `[agents] wip`'s ceiling; a bad value is refused naming the key, and a component (`[product] home`) that sets it is refused naming the home, where the product's limit is set (spec 101) (#1727)
