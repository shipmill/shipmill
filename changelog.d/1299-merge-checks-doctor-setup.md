### Added

- `shipmill doctor` prints the `merge-checks` lines as a row in a repo with `[agents]`, judged at the configured `[autonomy] land`: the status checks a merge to the default branch requires and what each one's jobs prove, a WARN under `act` when none proves anything, which never changes doctor's exit code; shipmill-setup's Autonomy step shows `merge-checks --land act` beside the `land` choice and its warning beside every option that sets `land = "act"` (spec 080) (#1299)
