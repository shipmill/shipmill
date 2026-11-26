### Fixed

- `shipmill product measure` checks the direction it would leave, as `product add` and `product edit` do: a measure line under a goal of kind goal is refused with exit 2 and `product check`'s lines, writing nothing, instead of leaving `docs/product.md` failing `product check` (#1759)
