### Added

- `shipmill gate` checks the GitHub identity a session writes as before it starts one: on a LAUNCH, after the Claude Code preflight, it mints the App's installation token and reads the repo with it (never cached), or reads `gh api repos/<repo>` as the host's login without an App. A failure, or a failing App check before the state read, is the new `GITHUB_AUTH` decision with the reason and fix spec 048 gives, starts and stops no session, and exits 2 as the bare App check error did (#813)
