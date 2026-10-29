### Changed

- Config deprecations no longer end on a release count (D-63): `[agents] prs` and `[roadmap]` keep loading with a `doctor` warning, and a config that sets none of `triage`, `fix`, and `land` keeps reading `land` from `[agents] prompt` ("merge when green" or "land"), so a connected repo that never took the `agent-autonomy` upgrade keeps landing. The warnings name the replacement instead of a release that refuses (#735)
