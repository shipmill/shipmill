### Added

- `shipmill ruleset` prints a branch ruleset for `gh api -X POST repos/<repo>/rulesets --input -`: the default branch (and `release/*` with a hotfix lane) needs a pull request and a check per job of the CI workflow the release workflow calls, with `[agents] app_id` as its one bypass actor; it exits 2 without `[agents] app_id` (#1081)
