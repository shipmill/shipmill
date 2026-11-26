### Added

- product-intake's `intake_state.py` counts the product's outcomes in flight under `[agents] outcomes`: every open opportunity of the repo, or of the product's home and its listed repos (read through `shipmill gh --product`, one call per owner; a component reads the limit from its home's config), printed as `outcomes in flight: K of N` and as an `outcomes` key on `--json`'s first line; without the key its output is unchanged, and the watch accepts the new key and makes no FEEDBACK_DUE row for a held request (#1728)
