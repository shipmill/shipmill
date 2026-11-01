### Added

- With `[agents] author = "decider"`, `shipmill gh issue create`, `pr create`, and `pr merge` run with the decider's user access token stored by `shipmill app-login`, refreshed first when it has expired, and as the App after one stderr line saying why when there is no decider, no stored token, or a token GitHub refuses; a refused refresh deletes the stored file, and every other command stays the App's. `shipmill gh issue create --decided-in <n>` names the issue or pull request that decided it, and the flag never reaches gh (#866)
