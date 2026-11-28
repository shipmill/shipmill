### Fixed

- `retro.py gather --goals` and `--decisions` read the direction, the specs, and the config at the checkout's `origin/HEAD` commit, so a shared main copy that lags a fetch no longer fails `status` with exit 2 (#1876)
