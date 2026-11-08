### Changed

- `shipmill gh pr merge` and the merge API `PUT` now refuse, as the App, a pull request still labelled `needs-decision`, and in every mode a `--match-head-commit` or `sha` field that isn't the full 40-character SHA, naming `gh pr view <n> --json headRefOid -q .headRefOid` (#960)
