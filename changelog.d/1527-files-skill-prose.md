### Changed

- The skills write and keep to an issue's allowed files: triage's Implement verdict carries a `- Files:` line with paths in backticks (a spec's build issue lists its spec file), a `Proposed plan:` writes its `Files:` paths in backticks, the implementer brief passes the allowed files and calls a file outside them a decision for you, github-issue-resolve's plan stays within them, landing asks a `files:` hold with the needs-decision question naming each file outside, and `pr_gate.py`'s docstring names the `files:` lines, their exit 5, and how the answer lifts them (#1527)
