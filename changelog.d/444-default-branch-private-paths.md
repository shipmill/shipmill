### Added

- Delivery hooks: the PreToolUse hook refuses a `git push` to the default branch (`default-branch-push`, off with `[hooks] default_branch = false`) and a `cp`, `mv`, or `rsync` of a `[hooks] private` path out of the repo (`private-paths`) (#444)
