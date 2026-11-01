### Changed

- Docs: `docs/release-lanes.md` says how shipmill retires a config key: a refused key turns off only its feature, refusing one is the maintainer's decision under D-63 no sooner than 14 days after its deprecating release (D-64), and a refusal is an entry in `src/shipmill/refused.py`; the `min_soak_days` and `plugin_update` paragraphs no longer describe an exit 2 (spec 052) (#862)
