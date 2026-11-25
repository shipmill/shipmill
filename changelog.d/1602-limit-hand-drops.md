### Fixed

- `shipmill gate` drops a hand whose session ended `limit` or `auth` on every tick, not only on the tick that records the end, so the hands 0.167.0 saved with their end after a capped run of usage limits no longer hold their pull requests until `retry_hours` (#1602)
