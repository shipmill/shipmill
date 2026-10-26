### Fixed

- Worktrees and `shipmill status`: a checkout with more than about 120 worktree branches no longer fails with GitHub's "exceeds the maximum limit of 500,000" nodes; merged pull requests are read 50 branches per GraphQL query (#709)
- Worktrees: GitHub is asked only about the worktrees the local checks leave undecided (not ones kept as young, dirty, in a live session, or not shipmill's), and never about the default branch a work branch tracks (#709)
