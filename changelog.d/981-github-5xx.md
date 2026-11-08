### Fixed

- `shipmill gate` no longer tells you to rerun `app-install` during a GitHub outage: a 5xx answer to the App check, the token mint, or the repo read is `GITHUB_AUTH` with `GitHub is unavailable (<method> <path> answered <status>)` and the fix to wait for GitHub (https://www.githubstatus.com), since the next tick tries again; the tick still exits 2 (#981)
