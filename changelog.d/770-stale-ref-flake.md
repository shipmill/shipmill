### Fixed

- The test that doctor asks origin, not the clone's refs, no longer fails under git 2.56, whose push to origin's URL also pruned the stale `origin/shipmill` the test sets up (#770)
