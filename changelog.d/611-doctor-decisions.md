### Added

- `shipmill doctor`, for a config with `[agents]`, prints a `decisions` block: the veto window and one line per zone with its level and source, and a WARN for each zone `[decisions]` sets below its default, for an unset `[agents] app_id`, and for a repo without the `decided` label; a config with `[decisions]` and no `[agents]` gets one WARN that nothing reads the section. `setup_state.py` wants the `decided` label with `[agents]`, so `LABELS_MISSING` names it and `--fix` creates it (spec 030, S-030-19, S-030-20) (#611)
