### Fixed

- `shipmill status --item REF` for an open issue or pull request takes about 13 to 14 s on shipmill/shipmill, from about 14 to 15 s: the App's bot login is read beside the item's own state, the item's own checks and review beside `watch_state.py` and `triage_state.py`, and `triage_state.py` and `watch_state.py` start as soon as the login is in hand; a closed or missing number still exits 2 at once, waiting on none of the other reads, and the output, stderr, and exit codes are unchanged (#1469)
