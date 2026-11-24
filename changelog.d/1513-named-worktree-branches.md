### Fixed

- github-pr-triage no longer leaves detached worktrees that `shipmill worktrees --prune` keeps forever: the second-look verifier checks out its own `review-<N>-verify` branch, with the PR's head branch as its upstream when it is in the repo, and a landing worktree, the stacked-branch recipe's included, holds a `land-<N>` branch, so the gate's prune removes them once their PRs land (#1513)
