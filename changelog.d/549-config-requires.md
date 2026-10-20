### Added

- `requires = ">=X.Y"` at the top of `.github/shipmill.toml` names the oldest shipmill the config is written for: an older CLI, `watch_state.py`, or `setup_state.py` exits 2 with the bound, its version, and how to update, before it refuses a key it doesn't know; `shipmill init` writes it, and `shipmill upgrade --apply` raises a lower one (#549)
