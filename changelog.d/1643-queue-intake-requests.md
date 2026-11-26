### Fixed

- `shipmill queue`, `status --item`, and `status --summary` no longer hold a user's request triaged as an opportunity as the maintainer's: one no open opportunity issue names yet is the agent's, waiting for product intake to group it, and one an open opportunity issue's body names waits on that opportunity (`waits_on`), so it counts once, through its opportunity; only issues labelled `opportunity` or `goal-plan` keep holder `maintainer` and `accept`, from triage_state.py's new `proposal` and `grouped` keys, read with no new query (S-094-6 and S-088-8 amended) (#1643)
