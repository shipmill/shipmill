### Fixed

- github-issue-triage's `triage_state.py` now links a pull request to an issue as covering part of it only by a "Part of #N" in its title outside code spans, or at the start of a line or a sentence of its body outside code spans and fences; a "Part of #N" quoted mid-sentence, in backticks, or in a fence no longer makes a merged pull request the issue's own work, so an issue with a `## Check` no longer reads VERIFY_DUE dated against a pull request that only mentions it (#1678)
