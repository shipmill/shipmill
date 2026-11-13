### Added

- `pr_gate.py` reads the land window on a base whose config has `[land.window]`: a green pull request carrying a held label and no bypass label reads QUEUED, exit 10, with a `queued:` line naming the next opening while the window is closed, or the spacing while the next held merge is still to come; a red, pending, refused, or held-for-a-decision one keeps its verdict, and a `shipmill window` that fails exits 2 (spec 056) (#1101)
