### Added

- github-issue-triage describes a parent's `## Check`: it closes the parent only once the check holds in production, with the verified comment; on a failure it posts the check-failed comment and files the fix as a new child; a check it can't run goes to the maintainer; a check never writes to production. The spec gate asks for a check on a feature issue whose build deploys and then leaves `Fixes #<feature>` out of the last build pull request, and an `upstream` report may carry a check for its coordinator (#719)
