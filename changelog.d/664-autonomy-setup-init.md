### Added

- Setup reads and writes autonomy levels: `setup_state.py` reports `AUTONOMY_IMPLICIT` for a config with `[agents]` whose `[autonomy]` sets none of `triage`, `fix`, and `land`; `shipmill init` writes `[autonomy]` uncommented with `release` at its default, and `init --operate` adds `rollback` and each `deploy.<env>` the policy doesn't set, at their defaults (#664)
