### Added

- `triage_state.py` reads a build issue of a spec approved at `notify` (zone `accepted-spec`, spec 067) BLOCKED, noted `veto window of #<spec PR> until <time>`, until `veto_hours` after the spec pull request's merge, and noted `#<spec PR> vetoed by @<login>` while a trusted veto of it is unanswered; then as before. The skills take up such a veto by reverting the spec to `draft` in a pull request, closing its build issues as not planned, and asking on the feature issue in `scope` (#1192)
