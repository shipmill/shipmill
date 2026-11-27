### Changed

- `pr_gate.py` refuses an agent's pull request whose plan's `Serves:` names none of the goals the newest trusted `Triage:` verdict of an issue it closes or is `Part of` names (`Serves: quality bar` included), read from the issue threads it already reads; a verdict naming no goal accepts the plan as before. github-issue-resolve, triaging an issue itself, reads the direction's Goals and Non-goals and applies triage's rule (#1767)
