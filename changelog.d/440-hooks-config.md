### Added

- The policy reads an optional `[hooks]` section in `.github/shipmill.toml`: `default_branch` (true or false, default true) and `private` (a list of globs, default none), refusing any other key or a wrong type with exit 2 naming the key (#440)
