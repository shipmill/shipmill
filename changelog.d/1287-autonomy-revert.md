### Added

- Autonomy: `[autonomy] revert` (`observe` by default, `propose`, or `act`) sets how far shipmill backs out a merge that turned the default branch red; `shipmill autonomy`, `shipmill doctor`, and `shipmill status` print it, an open `shipmill-hold` reads `act` as `propose`, setup's checklist wants the `revert` label once it isn't `observe`, and `pr_gate.py` holds the App's revert pull request (a `Reverts #N` and a `Repairs:` line) as BLOCKED for a person to merge below `act` (#1287)
