### Added

- product-intake's `intake_state.py --plans` reports PLAN_DUE for a goal with no open plan: `no-work` when no draft or approved spec, triaged issue, pull request plan, open opportunity, or plan item serves it and its newest plan wasn't declined, and `requested in #N` for a trusted `goal-plan` request; with `--wip N` a `no-work` plan waits for room (PLAN_WAITS) and a request never does (#510)
