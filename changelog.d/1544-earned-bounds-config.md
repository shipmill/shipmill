### Added

- `.github/shipmill.toml` takes an optional `[decisions.earned]` table (the lowest level a pull request may earn in `protected` and `security`, never below the zone's floor, and `max_lines`, 1 to 10000, default 200) and `[decisions] clean_releases` (1 to 20, default 3), and the zone table gains `area-record` after `protected`, defaulting to `act` with no floor; `shipmill decide levels` shows each zone's bound (`"earned"` in each JSON row, `null` without one), and a config without either key reads as before; nothing earns a level or reads an area's record yet (spec 083) (#1544)
