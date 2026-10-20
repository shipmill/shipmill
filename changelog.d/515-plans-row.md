### Added

- `watch_state.py` reports a PLANS row, from `intake_state.py --plans`, listing the goals whose plan is due and the plan issues that are malformed, answered, or accepted, and `shipmill gate` starts a session for it; with `--trusted-only` a plan issue the `--bot-login` didn't open is UNTRUSTED and starts none. Intake never reads a `goal-plan` issue as feedback, and triage reads a plan carrying intake's `Triage: **plan**` comment as TRIAGED (#515)
