### Fixed

- `test_proof.py` reads a plan's `Tests changed: none` (any case, alone or followed by prose such as `none; only new tests`) as naming no file instead of exiting 2; `none` on a line that also holds a backticked path, with or without its reason, still exits 2, and its message now says the line may be `none` (#1507)
