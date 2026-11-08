### Fixed

- `pr_gate.py` reads a commit message's closing keyword wherever GitHub closes by it, mid-line, in backticks, and in a fence too, with `#N` or the repo's own `owner/repo#N`, so a commit saying `... and fixes #N` no longer slips past the gate and closes a `Part of` issue or one whose `## Check` hasn't run; the title and the body keep their reading (#988)
