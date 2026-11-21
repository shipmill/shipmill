### Fixed

- A compare incident in a repository whose environments declare probes but no `health` URL now holds the lanes in `[gates] blocker_lanes` as a health incident does, and `shipmill doctor` wants the operate caller, with `issues: write`, and a deploy workflow that starts it once an environment declares probes; a repository with neither reads as before (#1453)
