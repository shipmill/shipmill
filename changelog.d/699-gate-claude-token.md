### Added

- The gate's sessions authenticate with a long-lived Claude token, the one `claude setup-token` prints, read from `~/.config/shipmill/claude-token` (mode `600`) or the file `shipmill gate --claude-token <path>` names; `shipmill launchd --claude-token <path>` writes the path, never the token, into the job. The token goes only into the environment of the `claude -p` or `claude --bg` that starts a session, and of the preflight's `claude auth status --json`, as `CLAUDE_CODE_OAUTH_TOKEN` with `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` and without `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`; a file the gate refuses is `CLAUDE_AUTH` with exit 2, never a fallback to the login. `shipmill status` and `shipmill doctor` print a `claude auth` line (spec 035) (#699)

### Changed

- The gate tick's `--json` key `auth` is now the credential's kind, `"token-file"` or `"login"`; the preflight's verdict it held moves to a new `preflight` key, so a reader of `auth` as an object must read `preflight` instead (spec 035) (#699)
