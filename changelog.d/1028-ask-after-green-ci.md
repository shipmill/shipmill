### Fixed

- A gate session no longer asks the maintainer to decide on a pull request while its CI is failing or still running: `pr_gate.py --wait` keeps polling while a NEEDS_DECISION pull request has a pending check on its head (its exit codes and verdict ranking unchanged), the needs-decision protocol asks only once the head's checks finished and handles a failed one as red CI first, and the question states the head's CI state (#1028)
