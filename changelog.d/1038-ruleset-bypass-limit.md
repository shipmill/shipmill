### Fixed

- Docs: `docs/release-lanes.md` (Limits), `docs/install.md` and shipmill-setup no longer tell an organization repository to let `github-actions[bot]` bypass the branch rules, which GitHub refuses there (a ruleset rejects it as a bypass actor, classic protection drops it); they say a rule requiring a pull request or a status check on main blocks landing, that the release commit's CI reports as `ci / checks` rather than `checks`, and to protect main there only against force pushes and deletion for now (#1038)
