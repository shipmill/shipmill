### Added

- `shipmill doctor` prints a `leaks` block in a repo with `[agents]`: `terms` with how many private terms `~/.config/shipmill/private.toml` lists (never a term), or off, a WARN when the repo is public; `secrets` with each secret file and how many values it gave (never a name or a value); `scanner` with gitleaks' version or its absence; and a FAIL naming the fix for a private file that doesn't load. `docs/leaks.md`, linked from `docs/install.md`, documents the private file, the four detectors, and both refusals (spec 081) (#1319)
