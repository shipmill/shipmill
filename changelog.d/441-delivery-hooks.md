### Added

- Plugin hooks: in a repo whose `.github/shipmill.toml` has `[agents]`, a PreToolUse hook refuses a plain `gh` write while `app_id` is set, a rebase merge, and a force push without a lease pinned to a commit, each with the command to run instead (#441)
