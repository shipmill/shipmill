### Fixed

- A `~/.config/shipmill/private.toml` that isn't valid TOML no longer prints a private term: the error every refused write, push, and `shipmill doctor`'s `leaks` FAIL show names the file's line and column instead of the parser's message, which quoted the file's keys, and a file that isn't UTF-8 names only the byte offset (#1407)
