### Fixed

- `shipmill worktrees --prune` and the gate's prune no longer remove a worktree whose unpushed commit differs from a landed one only in whitespace, such as re-indented Python lines: patch ids are computed with `git patch-id --verbatim`, and on a git older than 2.40, which lacks it, no commit counts as landed by patch id, so those worktrees are kept (#1213)
