### Added

- `shipmill gh issue comment <n> --status` and `pr comment <n> --status` write a session's progress into the item's one status comment, creating it once and editing it after, so a maintainer a question subscribed gets no email per step; `triage_state.py` reads no hold from a status comment, and the four skills post their progress this way (spec 090) (#1591)
