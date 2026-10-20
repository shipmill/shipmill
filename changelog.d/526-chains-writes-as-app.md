### Fixed

- github-issue-triage's `chains.py link` writes as the App: run from a checkout whose `.github/shipmill.toml` sets `[agents] app_id`, the native blocked-by or sub-issue relation and the `Depends on` line it adds to the body go through `shipmill gh` (from PATH, else through uvx), and a `shipmill gh` exit 2 stops the link with its message, never retried with plain `gh`; reads stay on plain `gh`, and without app_id nothing changes. Before, both writes ran as the maintainer's gh login (D-14) (#526)
