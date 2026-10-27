### Changed

- shipmill's own releases publish before they move their references (D-50): the stable and hotfix lanes list `move-major-tag.yml` under `after_publish`, so `@v0` and the plugin marketplace `ref` move only once `publish.yml`'s run passed and PyPI serves the release; the release commit no longer writes the marketplace `ref`, and `.github/shipmill.toml` sets `requires = ">=0.70.0"`. A newest-series hotfix now moves `@v0` and the `ref` too (#617)
