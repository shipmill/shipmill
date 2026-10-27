### Added

- shipmill-setup's `setup_state.py` reads a Product row: with `[agents] app_id` and no `[product]`, it lists the owner's repos whose `.github/shipmill.toml` sets the same `app_id` as `PRODUCT_SIBLINGS`, or `PRODUCT_LISTED` with the `home` line to write when one of them lists this repo in `[product] repos`; `PRODUCT_OK` otherwise, and `--fix` leaves the row (#721)
