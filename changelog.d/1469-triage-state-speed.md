### Fixed

- `triage_state.py` takes about 12 s on shipmill/shipmill, from about 21 s, and `shipmill status --item REF` for an open issue or pull request about 14 to 17 s, from about 24 s: each answer's follow-up calls (an issue's older comments and cross-references, the postponed issues' tag compares, the decided pull requests) start on threads while the open issues are still paged, and the run reads every answer in its own order, so its output, stderr, and exit code are unchanged (#1469)
