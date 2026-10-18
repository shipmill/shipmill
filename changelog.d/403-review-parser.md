### Added

- `shipmill review check` exits 1 naming the file, line, and rule when a `REVIEW.md`'s Important, Nits, or Protected areas section breaks its format, at the root or in a subdirectory, and passes free sections and a repo without one; `shipmill review show [--path FILE ...] [--json]` prints the rubric for the changed files, the root's and their directories' merged, each item with its file and the smallest cap (#403)
