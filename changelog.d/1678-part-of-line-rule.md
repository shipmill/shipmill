### Fixed

- github-issue-triage's `triage_state.py` now links a pull request to an issue as covering part of it only by a "Part of #N" in its title outside code spans or starting a line of its body (after an optional list bullet) outside a code fence, the rule it reads closing keywords by; a "Part of #N" quoted mid-line, in backticks, or in a fence no longer makes a merged pull request the issue's own work, so an issue with a `## Check` no longer reads VERIFY_DUE dated against a pull request that only mentions it (#1678)
