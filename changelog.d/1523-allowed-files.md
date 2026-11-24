### Added

- `pr_gate.py` holds an agent's pull request that changes a file outside what its issues allow: the `Files:` lines of each named issue's newest `Triage: **implement**` or `Proposed plan:` comment by the `--bot-login` or a trusted person, written before the pull request opened, read with spec 061's grammar, the default branch's `[changelog] fragments` folder always allowed; such a pull request reads NEEDS_DECISION, exit 5, with `files: <path> is outside what #<n> allows` lines, and fails closed on a `Files:` line it can't read or a thread cut off at 100 comments (#1523)
