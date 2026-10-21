### Fixed

- A gate whose launchd job runs a pinned `--tool` or the pre-org `@v0` source is told to rewrite its job with `uvx shipmill@latest --repo <checkout> launchd <repo>` when its CLI lags, not `uv tool upgrade shipmill`, which never changes the job; a job on `shipmill@latest` is told to run now with `launchctl kickstart` (#570)
