### Added

- `retro.py gather --reviews` counts the `--bot` logins' review records of the window, read from GitHub alone: the refusals `verified` by a second look (a findings line right after the marker) or `unverified` (with their pull requests), the merges with a findings line as `overturned`, the confirmed, rejected, and minor totals, and `first_reviewer_wrong`, the percent rejected, rounded down, or `no data`; `--json` holds them under `reviews` (#1275)
