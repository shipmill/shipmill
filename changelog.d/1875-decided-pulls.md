### Added

- `metrics.py --json` lists the merges behind Decided work credited and Decided work written as the decider: each measure carries `pulls`, one entry per decided pull request merged in the window, sorted by number, with its merge commit's sha and whether it was credited and written as the decider, so a checker can compare the counts with GitHub merge by merge; the table and markdown output are unchanged (#1875)
