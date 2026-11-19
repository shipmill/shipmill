### Added

- A lane with `milestone = true` may set `close_milestone = true` in `.github/shipmill.toml`, `false` when absent; a value that isn't a boolean, or `true` on a lane without `milestone = true`, stops the config naming the key and the lane, and `shipmill doctor` warns when a lane sets it and the caller's land job grants no `issues: write` (spec 068) (#1332)
