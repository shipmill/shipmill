### Added

- `shipmill doctor` prints one `identity` row in every repo: with `[agents] app_id`, a PASS naming the App's id, `<slug>[bot]`, and the repo when the token minted for the repo reads it, a FAIL naming the installation page and `shipmill app-install <owner/repo>` when it can't, and a WARN when the key isn't on this host; without it, a PASS for `identity = "host"` or `"none"`, a WARN naming the three choices and the setup line when nothing is recorded in an `[agents]` section, and a PASS without one. Doctor writes nothing (#1281)
