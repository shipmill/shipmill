### Added

- github-pr-triage: `pr_gate.py` reads the maintainer's answer to the needs-decision question from GitHub, on the pull request or, without one there, on the issue it closes or is part of, and lifts an `ask` zone or a Protected areas match to CI alone only for a head the answer covers: the head it was given at, or one whose own change is the same (`specs.py same-approval` for a spec pull request); otherwise it prints why the question stays open (#1088)
