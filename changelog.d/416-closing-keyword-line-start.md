### Fixed

- `triage_state.py` links a PR to an issue by a closing keyword only in the PR's title outside backticks or at the start of a body line outside a code fence, the rule `shipped.py` reads, so a PR that quotes "Closes #N" mid-line no longer reads as the issue's fix or makes DONE_NOT_CLOSED close it (#416)
