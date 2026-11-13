### Added

- `shipmill gh pr create`, with `[agents] app_id` set and `docs/product.md` on the default branch, checks the body it would send with `pr_gate.py`'s plan rule and exits 2 without running gh when the plan doesn't hold, printing each problem; a body with a `Spec for #N` line needs no plan, a repo without `docs/product.md` on its default branch isn't checked, and `--fill`, `--fill-first`, `--fill-verbose`, `--template`, `--recover`, and an unset `origin/HEAD` are refused there, as spec 055 says (#1091)
