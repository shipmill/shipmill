### Changed

- `pr_gate.py` refuses a pull request whose title, commit, or body has a closing keyword naming another open pull request (`closes #N, an open pull request`), or whose title or a commit writes a Dependabot alert as `#N` (`writes Dependabot alert #N: write alert N or its URL`), since GitHub reads that `#N` as the repo's own issue or pull request and its merge closed unrelated ones; github-issue-resolve and the implementer brief tell agents to write `alert N` or the alert's URL (#1321)
