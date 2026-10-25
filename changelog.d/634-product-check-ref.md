### Added

- `shipmill product check --ref REF` checks `docs/product.md`, and the files its moved sections link, as committed at a git ref instead of the working tree: exit 1 with `no docs/product.md at <ref>` when the file is absent there, and 2 for a ref git can't resolve (spec 034) (#634)
