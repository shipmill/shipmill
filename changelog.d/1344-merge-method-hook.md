### Added

- The plugin's delivery hook reads `[agents] merge` and gains the `merge-method` rule: under `"merge"` it refuses `gh pr merge --squash` (or `-s`, bundled too, through `shipmill gh` as well) and a `gh api` merge with `merge_method=squash`, naming D-96 with the `--merge` command to run instead; under `"squash"` or no key both methods pass, so a stack's base still takes `--merge`. The `rebase-merge` rule cites D-96 and its `Instead:` line takes the setting's method, and a malformed `[agents] merge` refuses every guarded command with the config's error (spec 072) (#1344)
