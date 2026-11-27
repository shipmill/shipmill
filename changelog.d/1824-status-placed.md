### Fixed

- `shipmill status` gives every state the watch prints a deliberate place: the App's held drafts leave the "other" line for the drafts line, the `--item`-only rows are silent, and the rows it still shows under "other" (a plan due, a red default branch, a land window's queue, and the rest no other line says) are named on a list with why, which a test checks against `watch_state.py`'s rows (#1824)
