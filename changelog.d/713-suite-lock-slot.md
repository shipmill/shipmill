### Fixed

- `suite_lock.py` holds a slot until the suite itself exits, so killing the wrapper no longer lets a second suite start beside one still running, and on Windows every process locks the same byte of a slot's file (#713)
