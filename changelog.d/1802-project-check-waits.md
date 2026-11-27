### Fixed

- A started project's head is no longer held on its own check issue: a head with no parts is built like any issue, its pull requests saying `Part of #<head>`, and once its work is done it reads BLOCKED on its check; the check issue reads BLOCKED until then and VERIFY_DUE after, never NEW, and product intake reads no check issue as feedback (spec 106, S-106-29, #1802)
