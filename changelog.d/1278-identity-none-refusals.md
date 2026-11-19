### Changed

- `shipmill gh`, `shipmill spec open`, and `shipmill app-token --check` read `[agents] identity = "none"`: a write exits 2 saying the repo's owner chose that agents don't write to GitHub here and to hand the text to a person, `--as-host` included, while a read still runs as the host's `gh` login; a write in a repo that chose no identity names the three choices (`app_id` from `shipmill app-create`, `identity = "host"`, `identity = "none"`) and `/shipmill:shipmill-setup <owner/name>`; and `app-token --check` without `app_id` exits 0 for `identity = "host"` (spec 082) (#1278)
