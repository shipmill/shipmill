### Changed

- Under `[autonomy] land = "propose"`, `watch_state.py` lists an open pull request labelled `shipmill-ready` in PRS_PARKED as `TO_MERGE #N` (`WITH_PERSON #4 (@a); TO_MERGE #12`), not in PRS_OPEN, in `--tier 3` and the full report, so the gate starts no more sessions on a pull request that waits on the maintainer's merge; under `act` and `observe` nothing changes, and `shipmill status` reports it to merge as before (#1162)
