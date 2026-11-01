### Added

- `[agents] author` in `.github/shipmill.toml` takes `"app"` or `"decider"` and needs `[agents] app_id`; with it set, `shipmill gh pr merge` names who decided the pull request in `Co-authored-by` whatever `[agents] credit` says, and `shipmill doctor` warns that `author` replaces `credit`. `credit` alone keeps its reading with a deprecation warning naming `author = "app"`, and a config with neither merges as before. Both values write as the App for now (spec 051) (#863)
