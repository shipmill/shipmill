### Changed

- `shipmill gh` in a repo without `[agents] app_id` now refuses a write with exit 2, naming the repo and the two ways to allow it, and still runs a read as your `gh` login; set `[agents] identity = "host"` to let the repo's writes go as your login, or pass `shipmill gh --as-host` for one call a person approved (spec 037) (#700)
