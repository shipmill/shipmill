### Fixed

- `intake_state.py --projects` reads a project head with more than 20 sub-issues, or a check issue with more than 10 parts, in full with a follow-up query on that issue, instead of failing the whole repo's read (#1827)
