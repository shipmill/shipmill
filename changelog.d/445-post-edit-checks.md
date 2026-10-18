### Added

- Delivery hooks: after an edit of `docs/product.md`, a file under `docs/product/`, or a `REVIEW.md`, the PostToolUse hook runs `shipmill product check` or `shipmill review check` and shows a failed check's output to the model (#445)
