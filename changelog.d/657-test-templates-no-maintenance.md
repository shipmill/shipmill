### Fixed

- Tests: every repo template the suite copies turns off git's detached auto-maintenance, whose lock files vanished mid-copy and failed `pytest -n auto` runs in CI at random (#657)
