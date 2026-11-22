### Fixed

- The gate's change check pages its open issues, pull requests, and incidents at 20 instead of 100, so each tick costs GitHub 1 rate-limit point instead of 6: GitHub charges a query for its worst case, which the nested labels, assignees, and links made 18,420 nodes; `issue_updates` keeps its page of 100 (#1458)
