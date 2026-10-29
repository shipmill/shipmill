### Changed

- `triage_state.py` and `watch_state.py` no longer read a comment carrying the agent marker `<!-- shipmill:agent -->` on any line, or a deleted account's comment, as a reply to a needs-decision question or as a veto, so without the App an agent's comment after the question no longer reads as the maintainer's decision (spec 050) (#800)
