### Fixed

- A shipmill command run while the host's directory service fails to resolve the account's uid now stops with one `shipmill:` line naming the uid and saying to retry, and exits 2, instead of a `KeyError` traceback; the private file's home still never falls back to `$HOME` (#1673)
