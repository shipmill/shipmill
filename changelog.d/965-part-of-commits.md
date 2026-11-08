### Changed

- `pr_gate.py` refuses a pull request whose commit's closing keyword names an issue its body lists as `Part of #N`, or whose commit's or body's closing keyword names an open issue with a `## Check`; `triage_state.py` reads VERIFY_CLOSED for any issue with a `## Check` a pull request or a commit closed before its check ran, not only a parent (D-76) (#965)
