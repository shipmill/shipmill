### Changed

- The skills follow roles (spec 036): github-issue-triage files a step only a person can do labelled `role:<name>` and assigned that role's users at once (`role:maintainer` when none fits, never `human`), assigns an ASSIGN_DUE item with no comment, reads NO_ASSIGNEE as a state read without the `--role` flags instead of asking who does it, and mentions a role's teams in the hand-off; shipmill-setup documents `[agents.roles]` and its `role:<name>` labels (#643)
