### Fixed

- Worktrees and `shipmill status`: a checkout with more than about 120 local branches no longer fails with GitHub's "exceeds the maximum limit of 500,000" nodes; merged pull requests are read 50 branches per GraphQL query
