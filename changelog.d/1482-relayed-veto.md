### Fixed

- A maintainer's veto relayed by a session through the App now stops a merge: the App's relay after an item's decided marker, in the relay grammar, naming the maintainer, whose answer line is `own: veto [<text>]` or starts with `veto`, reads as that maintainer's veto, so `triage_state.py` reads the item VETOED (naming the maintainer, read from the `--role maintainer` flag) and `pr_gate.py` holds the pull request until a veto-handled comment follows it; a relay naming anyone else, out of the grammar, or answering an option is no veto (#1482)
