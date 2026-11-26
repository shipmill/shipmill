### Added

- Product intake: the maintainer holds a goal plan with `hold until <YYYY-MM-DD | #N | owner/repo#N | release>`; `intake_state.py --plans` reads it PLAN_HELD, no action, and once the condition is met PLAN_HOLD_MET, an action the watch's PLANS row lists, until the App's `<!-- shipmill:plan-recheck -->` comment returns it to PLAN_OPEN `hold met: ...`; `--json` rows carry `hold` (`until`, `met_at`), and `--stable-tag-regex` sets which tags are a release (spec 098) (#1729)
