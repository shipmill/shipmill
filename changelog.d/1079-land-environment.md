### Added

- `land.yml` takes a `land-environment` input: set, its `land` job runs in that environment, writes the environment's `SHIPMILL_LAND_KEY` secret, masked, to a mode 0600 file, and runs `shipmill land --app-key` with it, failing before land when the secret is empty; empty, it lands as before. `shipmill init --land-as-app` writes `land-environment: shipmill-land` on the release workflow's `land` job, and exits 2 when the config sets no `[agents] app_id` (#1079)
