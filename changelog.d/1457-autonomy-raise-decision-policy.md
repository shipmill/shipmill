### Changed

- `shipmill decide classify --pr` puts a pull request that raises an `[autonomy]` stage's level (observe < propose < act, resolved as `shipmill autonomy` resolves it) in `decision-policy`, so it is `never` and the maintainer merges it by hand, whatever `security` is set to; a change that only lowers or keeps the levels stays `security` (D-99) (#1457)
