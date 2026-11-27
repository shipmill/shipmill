### Fixed

- `shipmill project add`, `focus`, and `hold`, and `opportunity accept`, create the label they add when the repository lacks it, before the relay, so a missing `project`, `focus`, `held`, or `planned` label no longer leaves a posted relay with its label step failed, and a rerun no longer posts a second relay; a label that can't be created exits 2 with nothing written, and `--dry-run` names it as its own step (#1828)
