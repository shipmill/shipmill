### Changed

- Deprecated config keys and readings are catalogued in `src/shipmill/deprecations.py`: `[agents] prs`, the `[agents] prompt` reading of `land`, `[roadmap]`, and `[agents] credit`, each with the release that deprecated it, its replacement, its migrating upgrade (`agent-autonomy` for spec 040's two), and a check over the parsed config; `shipmill doctor`'s deprecation warnings come from it, with the same text, row, and WARN as before (spec 047) (#905)
