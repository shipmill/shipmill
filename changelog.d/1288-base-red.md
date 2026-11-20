### Added

- Merge gate: `skills/github-pr-triage/scripts/base_red.py` reads a red default branch from GitHub and the merges that may have turned it red: GREEN, RERUN_DUE with each first-attempt run to re-run, CULPRIT or CANDIDATES from each failed check's last green and first red on the first-parent history (each candidate's pull request and whether it is revertable: merged by the `--bot-login` and in no tag), or NO_GREEN, then the open repair pull requests and the question issue; a check rerunning after a failure reads PENDING, never GREEN, as `pr_gate.py` reads it (#1288)
