### Changed

- Gate: a tick that reads a config whose `[agents]` sets a refused key runs as it would without it; its decision line ends with `; refused: <key> (spec NNN)` for each, `tick.json` and `shipmill gate --json` list them under `"refused"`, and the tick is never an ERROR tick (spec 052) (#861)
