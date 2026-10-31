### Fixed

- A repo that uses only the agent side (`mode = "off"` and no release workflow) runs a gate: the ship watch reads it as having no release bot (`BOT_NONE`, `releases off`) instead of stopping with `neither release.yml nor release-bot.yml calls a bot`, and `shipmill doctor`'s `workflow` check passes with a note that no release workflow is needed; a missing release workflow under `mode = "release"` or `"dry-run"` still stops the watch and fails doctor (#852)
