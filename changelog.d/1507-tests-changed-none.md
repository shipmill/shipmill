### Fixed

- `test_proof.py` reads a plan's `Tests changed: none` (any case, alone or followed by prose such as `none; only new tests`) as naming no file instead of exiting 2; `none` mixed with a `` `path`: reason `` entry still exits 2, and its message now says the line may be `none` (#1507)
