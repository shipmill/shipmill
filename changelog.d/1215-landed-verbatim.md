### Fixed

- github-pr-triage's `landed.py` no longer reads a commit as landed when it differs from a landed one only in whitespace, such as re-indented Python lines: patch ids are computed with `git patch-id --verbatim`, and on a git older than 2.40, which lacks it, no commit counts as landed by patch id, so such commits read NOT LANDED and their worktrees and branches are kept (#1215)
