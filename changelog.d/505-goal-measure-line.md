### Added

- A goal in `docs/product.md` may carry one measure on the line under it, `  measure: <metric> <comparison> <target>`, naming a metric from a fixed registry (`deploy_frequency`, `lead_time_median`, `human_touch`, ...) and a target in its unit: `shipmill product check` refuses an unknown metric or comparison, a target in the wrong unit, and a misplaced or second measure line with its file, line, and rule; `shipmill product show --json` gives every goal a `measure` key, and the PR gate and `specs.py check` accept the line (spec 027) (#505)
