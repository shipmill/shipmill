### Changed

- Tests: the suite takes about half the CPU; git fixtures are built once and copied per test, and most delivery hook cases call the hook's `main` in process (#667)
