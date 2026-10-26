### Fixed

- The gate's prune and `shipmill milestones` read the branch releases land on from the config at origin's default branch, as the gate's refresh does, never from a checkout a session left on a pull request's branch (#697)
