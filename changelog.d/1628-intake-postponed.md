### Fixed

- product-intake's `intake_state.py` no longer reads an issue labelled `postponed`, `human`, or `role:<name>` as NEW_FEEDBACK, whatever its comments say, matching how `triage_state.py` reads it (POSTPONED, or a person's item), so github-ship-watch's FEEDBACK_DUE stops launching intake on it (#1628)
