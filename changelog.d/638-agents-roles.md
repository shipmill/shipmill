### Added

- `[agents.roles]` in `.github/shipmill.toml` maps role names to the GitHub logins and `@org/team` entries who receive the steps an agent can't do, with the maintainer defaulting to the host's gh login and an empty role falling back to the maintainer; `shipmill roles` prints them resolved, with `--json` and `--flags`, and a malformed table exits 2 from every reader of the config, `shipmill doctor` included (spec 036) (#638)
