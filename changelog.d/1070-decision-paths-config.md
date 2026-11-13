### Added

- Decisions: `.github/shipmill.toml` accepts `[decisions.paths.<zone>]`, a level by glob for part of the `direction`, `security`, or `protected` zone, refused with exit 2 below the zone's floor or outside its paths, and `shipmill decide levels` lists each part under its zone (`"paths"` in `--json`); `decide classify` doesn't read parts yet, spec 057 (#1070)
