### Fixed

- `fleet.py queue` passes each clone's roles, as `shipmill roles --flags` prints them, to `triage_state.py` and `intake_state.py --plans`, so a goal plan the maintainer answered through a relayed decision (D-68) leaves the queue; a failed roles read is that repo's REPO_ERROR line (#1409)
