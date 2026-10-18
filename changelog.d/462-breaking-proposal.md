### Added

- A breaking stable candidate gets its `Ready to release` issue, with the breaking entries listed first, even in a run that releases rc or dev, and only a person's hand start releases it: `shipmill plan --actor` (from `$GITHUB_TRIGGERING_ACTOR`) skips stable for a `[bot]` login or a run naming no actor, and land closes the issue once the release is tagged (#462)
