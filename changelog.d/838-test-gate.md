### Changed

- `github-issue-resolve` and `github-pr-triage`'s reviewers prove a fix with the cheapest check that fails on the old code, by a new test gate (`references/test-gate.md`): an existing test that fails on the revert, the repo's type checker, or a strict model at the boundary, and a new regression test only when none of them catches the bug; the PR's Test plan names the proof and shows it failing (#838)
