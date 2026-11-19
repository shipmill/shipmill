### Fixed

- Merge gate: a trusted veto of a decision taken at notify, on the pull request or on an issue it closes, reads BLOCKED with a `decided: vetoed by @<login> at <time>, not handled` line until a veto-handled comment answers it, read as triage_state.py reads VETOED (#1309)
