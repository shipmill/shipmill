### Changed

- product-intake's `intake_state.py` no longer reads an issue triage postponed as a request to group, until a newer triage verdict hands it over, and each NEW_FEEDBACK and ACCEPTED line of its `--json` output now carries the opener's `author` and `association` and `handed`, when triage handed the issue over (#1252)
