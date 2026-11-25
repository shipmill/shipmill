### Fixed

- `shipmill gh` no longer lets every write to a public repo through on a machine without `~/.config/shipmill/private.toml`: a write naming an `owner/name` repo the token at hand reads as private exits 2 (`private-repo`), with or without the file, and in a checkout with `[agents]` a write to a public repo exits 2 until the file exists, an empty one being enough; doctor's `terms` row names the `touch` step (D-102, S-081-18, S-081-19) (#1480)
