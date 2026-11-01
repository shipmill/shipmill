### Changed

- Gate: a tick on a config that sets a refused key runs as it would without it; its decision line ends with `; refused: <key> (spec NNN)` for each, `tick.json` and `shipmill gate --json` list them under `"refused"`, and the tick is never an ERROR tick (spec 052) (#861)
