### Changed

- The plugin pins its CLI: the skills, their scripts, and the hooks run `uvx shipmill==<the version in the plugin's plugin.json>` from PyPI instead of the `@v0` tag's source or a `shipmill` on PATH, and a missing or malformed `plugin.json` exits 2 naming it; the wheel ships `shipmill/.claude-plugin/plugin.json`. The marketplace entry names the release tag, which each release's stamp moves with `plugin.json` and every pinned line, and the gate, `doctor`, `status`, and `watch_state.py` read the latest release from that ref instead of `gh release view` (spec 031) (#548)
