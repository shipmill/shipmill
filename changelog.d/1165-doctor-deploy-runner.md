### Added

- `shipmill doctor` warns, in a `deploy runner` row, of a job whose `actions/checkout` sets no `path:` and runs on a self-hosted runner a deploy job deploys from, since its checkout cleans the workspace the deploy left; a PASS row names the deploy jobs checked, and a repo with no deploy job on a self-hosted runner sees no row (#1165)
