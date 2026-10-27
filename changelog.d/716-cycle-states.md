### Added

- `triage_state.py` reads CYCLE, an action, for an open issue on a cycle of the repo's open issues whose holds it reads, its note `cycle <loop>`; the others on a loop wait as BLOCKED, `cycle <loop> waits on owner/repo#N`, while one of them reads MALFORMED_DEPENDS or is labelled `needs-decision`. github-ship-watch counts CYCLE and MALFORMED_DEPENDS as triage actions and reports CHAIN_CYCLE, a person's action, once per cycle through another repo's items; `shipmill status` and `fleet.py` count both (spec 041) (#716)
