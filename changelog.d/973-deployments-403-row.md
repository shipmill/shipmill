### Fixed

- The watch no longer ends on a repo with `[environments]` when the gate's GitHub App has no `deployments: read`: GitHub's `Resource not accessible by integration (HTTP 403)` on a deployments or deployment-statuses read is one `DEPLOYMENTS_FORBIDDEN` notice row naming the environments not read and the permission to accept, and the rest of the report (issues, pull requests, every other section) stands; any other failure of those reads still exits 2 (#973)
