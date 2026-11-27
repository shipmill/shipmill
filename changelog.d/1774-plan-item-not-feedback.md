### Fixed

- Product intake no longer lists a filed plan item, or an issue labelled `project`, as NEW_FEEDBACK until triage gives it a verdict: an issue whose body's first line is the plan-item marker, written by the `--bot-login` or an OWNER, MEMBER, or COLLABORATOR, is the maintainer's accepted work, and an outsider's copy of the marker changes nothing (#1774)
