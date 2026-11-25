### Fixed

- `pr_gate.py` no longer lets an issue's allowed files widen after an agent's pull request opened: a `Triage: **implement**` or `Proposed plan:` comment edited since holds the pull request with `files: the allowance on #N changed after this pull request opened` until the maintainer's answer lifts it (#1570)
