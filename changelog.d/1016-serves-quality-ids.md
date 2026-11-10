### Added

- An agent's pull request plan may name the quality-bar ids it serves: `pr_gate.py` accepts `Serves: Q-6` and `Serves: quality bar (Q-4, Q-6)` when docs/product.md's Quality bar lists them, refuses an unlisted one like an unlisted goal id, and the weekly retro counts such a pull request under the quality bar (#1016)
