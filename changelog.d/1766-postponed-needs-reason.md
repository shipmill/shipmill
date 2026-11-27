### Fixed

- An issue labelled `postponed` with no `Triage:` comment by an OWNER, MEMBER, or COLLABORATOR or the `--bot-login` reads NEW in `triage_state.py`, its note `postponed label without a triage comment`, so a session triages it instead of skipping it for good; `intake_state.py` reads the label the same way, and an issue postponed with a trusted triage comment reads POSTPONED or REVISIT as before (#1766)
