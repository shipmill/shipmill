### Changed

- shipmill-setup's `setup_state.py --fix` now removes a committed `shipmill@shipmill` from `.claude/settings.json` in a repo whose `[agents] plugin` is `"host"` (the default): it deletes the `enabledPlugins` entry and, when no other enabled `<name>@shipmill` uses it, the `shipmill` marketplace, keeps every other key and the file's indent, and deletes the file when nothing is left; set `plugin = "repo"` to keep it (D-60) (#778)
