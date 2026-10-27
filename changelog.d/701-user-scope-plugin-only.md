### Changed

- Plugin: one install of `shipmill@shipmill` at user scope (spec 039). Every fix shipmill prints names `--scope user`, never a per-folder update or reinstall; `doctor`, `status`, the setup checklist, and the gate's tick report every project- and local-scope install on the host as one `PLUGIN_SHADOWING` row; and the new `shipmill plugin-clean` lists them, and with `--apply`, from a person's terminal only, removes them while restoring each folder's `.claude/settings.json` and `settings.local.json` byte for byte (#701)
