### Changed

- Implementers and reviewers run the fast checks and the touched files' tests and leave the full suite to the PR's CI, so parallel agents no longer starve each other of CPU; in a repo whose CI doesn't run the full suite, they queue it through github-issue-triage's new `suite_lock.py`. shipmill's CI runs its tests with pytest-xdist (#657)

### Fixed

- `specs.py coverage` no longer reads the repo's root `tmp/`, where an agent's stray worktree made the coverage test fail locally (#657)
