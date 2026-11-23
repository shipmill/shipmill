### Fixed

- An unknown key in `~/.config/shipmill/private.toml` is named by its line and the keys the file takes, never by its text: a table or key named after a private term no longer reaches a refused write's message, a refused push, or `shipmill doctor`'s `leaks` FAIL (spec 081, S-081-4 amended) (#1416)
