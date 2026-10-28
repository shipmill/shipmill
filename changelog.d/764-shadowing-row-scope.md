### Changed

- Plugin: a repo's `PLUGIN_SHADOWING` row in `doctor`, `status`, the setup checklist, and the watch counts only the project- and local-scope installs keyed on the repo's checkout, its linked worktrees, or its gate checkouts; `shipmill factory` still counts every one on the host, so a stray install is reported once, there (#764)
