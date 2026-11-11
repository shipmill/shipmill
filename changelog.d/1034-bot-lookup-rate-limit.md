### Fixed

- `shipmill gate` no longer tells you to rerun `app-install` when GitHub rate-limits it: a 403 or 429 saying a rate limit was exceeded, to the App check, the token mint, or the repo read, is `GITHUB_AUTH` with `GitHub rate-limited the call (<method> <path> answered <status>)` and the fix to wait for the limit to reset, since the next tick tries again; the tick still exits 2, and a 403 without a rate limit reads as before. A merge's Co-authored-by now reads the App's bot account with the App's token, not anonymously under the host's shared per-IP limit (#1034)
