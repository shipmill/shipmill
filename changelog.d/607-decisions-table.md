### Added

- `.github/shipmill.toml` takes an optional `[decisions]` section (spec 030, D-48): each key a zone id set to `act`, `notify`, `ask`, or `never`, and `veto_hours` for the notify window (1 to 168, default 24); a zone left out keeps its default, and a level below a zone's floor, a fixed zone, a release-side zone `[autonomy]` sets, or an unknown key stops the run with exit 2. Nothing reads the levels yet (#607)
