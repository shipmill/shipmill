### Fixed

- The skills list a pull request's files without `gh pr diff --name-only`, which GitHub refuses with HTTP 406 past 300 files: github-issue-resolve checks its pull request's files with `git diff --name-only origin/<default>...HEAD` in its worktree, and github-pr-triage's reviewer brief reads them for the review rubric through the paginated files API (#632)
