### Fixed

- `pr_gate.py` no longer lands an agent's docs-only pull request that sets a spec's `status:` to `built` without a review: that line claims a feature finished, so the PR reads UNREVIEWED until a review of its head is recorded, read from the patches of the files API call the docs-only check already makes; every other docs-only change keeps its verdict (#1486)
