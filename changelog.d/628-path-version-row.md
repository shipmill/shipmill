### Fixed

- A `shipmill` on PATH whose `--version` exits 0 with anything but `shipmill X.Y.Z` is now the `SHIPMILL_OUTDATED` `shipmill on PATH` row, quoting the first line it printed with `uv tool upgrade shipmill` as its fix, instead of making `watch_state.py` exit 2 and stopping every gate tick (#628)
