### Added

- github-pr-triage's `test_proof.py` reads a fix's or a refactor's proof from its pull request's history: a fix's test committed first and alone fails on its own commit and passes on the head with its lines kept, and a refactor leaves the base's test files as they were on a green base; it runs only git and the test command given after `--`, in a temporary detached worktree it removes on every outcome (spec 076) (#1283)
