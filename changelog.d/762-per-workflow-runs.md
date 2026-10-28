### Changed

- The gate's change check reads each watched workflow's own 10 newest runs (the release workflow and each `[operate]` workflow), concurrently when there are more than two, instead of the repo's 100 newest runs of every workflow: a quiet tick spends about 2 s less on it, and a release run that finished behind 100 newer CI runs is now seen as a change (#762)
