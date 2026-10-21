### Deprecated

- `[agents] plugin_update` (spec 031): gate sessions load the installed plugin and report its lag, so the gate ignores the key whatever its value and runs no `claude plugin update`; `doctor` warns naming it, and the next minor release refuses it. `shipmill upgrade` no longer offers `plugin-update`, `shipmill init` no longer writes it, and a release closes an open `plugin-update` upgrade issue as withdrawn; `gate --json` drops the `plugin` field of the daily update (#552)

### Changed

- The install guide, the policy reference, and the shipmill-setup and github-ship-watch skills describe the pinned CLI, the marketplace serving release tags, gate sessions loading the installed plugin, `requires`, and the `plugin_update` deprecation, and no longer describe a gate paused on a stale plugin (#552)
