### Changed

- Agents queue their full test suites through github-issue-triage's new `suite_lock.py`, run only the touched files' tests while they work, and a reviewer leaves the full suite to CI, so parallel agents no longer starve each other of CPU; shipmill's CI runs its tests with pytest-xdist (#657)

### Fixed

- `specs.py coverage` no longer reads the repo's root `tmp/`, where an agent's stray worktree made the coverage test fail locally (#657)
