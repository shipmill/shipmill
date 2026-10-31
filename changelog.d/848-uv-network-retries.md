### Fixed

- The gate's launchd job gives uv 8 HTTP retries (`UV_HTTP_RETRIES`, about a minute), so the first tick after a FileVault login still reaches PyPI, and a run whose uvx found no network (uv's `Failed to fetch` on a DNS or connect error) reads `offline at last tick, next in N min` with `launchctl kickstart` as its fix instead of STUCK `failed: exit 2`; run `shipmill launchd <repo>` again to give an existing job the retries (#848)
