### Added

- `shipmill init --downstream` writes `.github/workflows/downstream.yml`, the workflow that runs the `[downstream]` repositories' tests on each pull request through shipmill's reusable `downstream.yml`; it refuses a policy without `[downstream]` and an existing file without `--force` (#513)
