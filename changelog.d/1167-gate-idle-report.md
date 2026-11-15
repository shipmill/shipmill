### Added

- github-ship-watch's `watch_state.py` lists each issue or pull request the gate keeps idle as a GATE_IDLE row, read from `handed.json` in the gate folder's state directory: `idle since <time> UTC (<age> ago): session <id> wrote nothing on it; waits for a change`, oldest first, in the full report and `--no-host`, never an action or an agent's row, and a malformed `handed.json` exits 2 naming its path; the postpone templates carry a `Revisit on:` line, and the triage, setup, and watch docs say how the gate hands subjects one by one (spec 061 is built) (#1167)
