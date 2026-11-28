### Fixed

- A session landing or triaging PRs messages about a pull request only the session that owns its branch, the one in the worktree that has it checked out or the agent it dispatched to open it, naming the branch and the commit; when no session matches, it writes the note in the PR's status comment instead of messaging every session listed, so an offer to hold a PR or a note about a late push no longer reaches a session that never touched it (#1872)
