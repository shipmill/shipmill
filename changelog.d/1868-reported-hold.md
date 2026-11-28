### Fixed

- A comment that reports on another item's hold no longer holds the issue carrying it: `triage_state.py` reads a hold phrase in quotes or a code span as quoted words, and a sentence that names an item before its hold phrase as that item's hold, so a check result quoting a label's "put on hold" beside another item's link reads as no hold (#1868)
