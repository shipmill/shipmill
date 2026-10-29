### Changed

- The skills' scripts (`chains.py link`, `shipped.py --post`, `setup_state.py --fix`) write through `shipmill gh` in every repo whose `.github/shipmill.toml` has an `[agents]` section, with or without `app_id`, so a write without an App goes out as the host's login with the agent marker under `identity = "host"` and exits 2 otherwise; plain `gh` is left for a repo with no config or no `[agents]` (#799)
