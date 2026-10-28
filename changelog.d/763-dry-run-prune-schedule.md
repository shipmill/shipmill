### Changed

- `shipmill gate --dry-run` follows the prune's schedule, every `prune_hours`: when a prune isn't due it judges no worktree and prints `prune due at <time>`, so a dry run no longer spends most of its time judging worktrees or lists removals a tick wouldn't make; when one is due it lists `would prune` as before, and `--json`'s `"prune"` adds `"due"` and `"at"` on a dry run (#763)
