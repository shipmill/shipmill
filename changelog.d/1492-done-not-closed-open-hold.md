### Fixed

- Triage: a merged closing pull request no longer reads an issue DONE_NOT_CLOSED while one of its holds is still open; it reads BLOCKED, and a parent with a `## Check` reads VERIFY_DUE once its last child closes (#1492)
