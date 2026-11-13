### Added

- `shipmill land --app-key <path>` pushes the release commit to the default branch, a hotfix to `release/X.Y`, and the sync commit as the App in `[agents] app_id`, with one token limited to the repository and `contents` and `workflows` write, minted before any push; the tag and the work branch keep the workflow token, and a push a branch's rules refuse (`GH013`, `protected branch`) names `shipmill doctor` and the docs as the fix (#1075)
