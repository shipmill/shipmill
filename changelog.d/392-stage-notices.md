### Added

- The notices on fixed issues name their stage: a dev or rc tag posts `Released in <tag> (pre-release).` with the pin command and that a plain install gets it with the next stable release, a stable promotion of an rc tells every issue the rc fixed, and each notice starts with a `<!-- shipmill:available: <stage> <tag> -->` marker so a rerun posts nothing; a new optional `[notices]` section in `.github/shipmill.toml` sets the `pin` and `install` commands, with `{version}`, `{tag}`, and `{name}` (spec 021) (#392)
