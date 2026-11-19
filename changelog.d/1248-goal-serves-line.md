### Added

- A component's goal names the product goals it serves on a `  serves: G-n[, G-n ...]` line under its item or measure line: `shipmill product check` refuses a misplaced or malformed one, and any in a repo whose config sets no `[product] home`; `product show --json` gives each goal a `serves` list; `shipmill product serves G-n <ids>` writes it and `--clear` removes it; `product check` and `product show` take `--local`; and the skill scripts read a direction holding the line as before (spec 071) (#1248)
