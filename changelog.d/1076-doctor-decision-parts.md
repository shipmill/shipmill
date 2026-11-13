### Added

- `shipmill doctor`'s decisions block prints one PASS line per `[decisions.paths.<zone>]` part, naming its zone, glob, and level, and WARNs for a part set below its zone's default; the "Who decides" docs say which zones take parts and that the strictest level among a change's paths wins (#1076)
