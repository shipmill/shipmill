### Added

- Product intake holds a new outcome while `[agents] outcomes` has no room: `intake_state.py` reads a request with intake's held comment HELD, `held since <date>`, which never sets exit 1; once room comes back held requests read NEW_FEEDBACK first, oldest held first, and the maintainer's `propose` reply asks for one by name past the limit; the skill gains the HELD state, the hold in its workflow, a hard rule, the room in its report, and the held comment's template (spec 101) (#1733)
