### Fixed

- `shipmill worktrees --prune` no longer keeps a merged pull request's worktree forever when its branch is a local `review-<N>`, `push-<N>`, or `land-<N>` with no upstream, or when its commits are a local rebase of the pull request's that was never pushed: it finds #N by the number in the name and matches each commit by patch id against the pull request's commits, so a commit with a change the pull request never had still keeps the worktree, per D-91 (#1207)
