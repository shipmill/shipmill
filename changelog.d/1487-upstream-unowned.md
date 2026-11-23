### Fixed

- An `upstream` report with no link to an issue in another repo and no assignee no longer waits on nobody: without a coordinator, `triage_state.py` reads it `UPSTREAM_UNOWNED` (not an action), `fleet.py queue` lists it as an `UPSTREAM` row for the maintainer to report it where it belongs until it is linked or assigned, and `shipmill status --item` says so; the queue now passes the clone's `[product] home` to `triage_state.py` as `--home`, as the watch does (#1487)
