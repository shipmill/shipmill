### Fixed

- `shipmill prune` and the gate no longer fail with `Fragment merged was defined, but not used` when a batch of merged pull requests holds only numbers: such a query now leaves out the fragment it does not use, so stale worktrees are cleaned up again
