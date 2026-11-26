### Changed

- `pr_gate.py` prints a `no checks: none ran on <sha7>` line under a PENDING PR whose head ran no checks at all, so a repository that runs no CI on pull requests no longer reads as CI still running; the verdict and its exit code are unchanged (#1776)
