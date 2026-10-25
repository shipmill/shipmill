### Added

- `shipmill --version` prints `shipmill <version>`. `doctor` (a WARN) and `shipmill status` (waiting on you) report a `shipmill on PATH` whose version differs from the plugin install a session loads: `uv tool upgrade shipmill` when it is older, predates `--version`, or doesn't answer it (a 10 s timeout, or it can't start), the plugin's update when it is newer; `watch_state.py` reads it as one `SHIPMILL_OUTDATED` row, asking the first `shipmill` on PATH outside its own environment with only PATH and HOME (spec 031, S-031-25 to S-031-29) (#583)

### Changed

- `README.md` and `docs/install.md` give `uv tool install shipmill` as the one way to get the CLI, with `uv tool upgrade shipmill` after each plugin update, and `uvx shipmill <command>` for a run without the install, in place of the `@v0` git form (S-031-30) (#583)
