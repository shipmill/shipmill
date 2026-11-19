### Added

- `shipmill app-install <owner/repo> --app-id <id> --check` opens no page and waits for nothing: it mints the token the gate's preflight mints for the repo and reads the repo with it, exiting 0 with `App <id> (<slug>[bot]) can read <owner/repo>`, 1 naming the repo, the App's installation settings page, and `shipmill app-install <owner/repo>` when the App isn't installed or can't read it, and 2 for a missing or open key or GitHub out of reach; the token is neither printed nor cached, and `--json` prints `app_id`, `slug`, `repo`, `reads`, and `page` (#1276)
