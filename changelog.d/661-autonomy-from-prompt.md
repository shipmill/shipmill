### Added

- For one minor release, a config with `[agents]` that sets none of `[autonomy]` `triage`, `fix`, and `land` reads `land = "act"` from an `[agents] prompt` that says "merge when green" or "land", shown with source `prompt` by `shipmill autonomy` and warned about by `doctor`; the `agent-autonomy` upgrade (`shipmill upgrade --apply agent-autonomy`) writes the three keys with those levels, keeping the rest of the file byte for byte (#661)
