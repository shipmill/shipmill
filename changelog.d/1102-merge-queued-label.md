### Added

- `shipmill gh pr merge` of a pull request `pr_gate.py` reads QUEUED adds the land window's `queued_label` to it as the App and exits 2 without merging, and a merge that exits 0 removes that label from the pull request carrying it (S-056-8) (#1102)
