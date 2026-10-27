### Changed

- `shipmill gate` prunes landed worktrees after the tick's decision and any launch, only every `[agents] prune_hours` (default 6, 0 for every tick, recorded in the state directory's `prune.json`), and a prune that fails prints `prune failed: <first line>` and leaves the decision, the launch, and the exit code as they are, so one failing `gh` query no longer stops every tick; `--json` gains `"prune": {"ran", "error"}`, `shipmill factory` gains a `prune` line, and a failing prune counts on `shipmill status`'s `factory` line without changing the verdict (spec 045, #741)
