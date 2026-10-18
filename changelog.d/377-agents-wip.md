### Deprecated

- Config: `[roadmap]` is deprecated (D-32). A config with it still loads and the policy validates it, but nothing reads it, and `doctor` warns that the work-in-progress limit is now `[agents] wip`; the next minor release refuses `[roadmap]` (#377)

### Added

- Config: `[agents] wip = N` (1..100) is the work-in-progress limit github-issue-triage reads (`triage_state.py --wip N`): at most N issues in progress at once; without it there is no limit (D-32) (#377)

### Removed

- Product intake: the roadmap plan is gone (D-32). The skill no longer proposes, ranks, or creates milestones; `roadmap_state.py` and the milestone-proposal template are removed, and a milestone is the maintainer's own list of what a version must hold. Grouping requests into opportunities stays (#377)
