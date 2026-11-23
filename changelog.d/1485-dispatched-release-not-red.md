### Fixed

- Merge gate: a failed run of a lane's `dispatch` or `after_publish` workflow, dispatched on the default branch for a tag, no longer reads the branch red in `pr_gate.py` and `base_red.py`; every other failed run on the head still does (#1485)
