### Added

- `chains.py show` marks each open issue on a dependency cycle `CYCLE (a -> b -> a)`, its shortest loop from the least reference (`"cycle"` in `--json`, null on every other row), ends a row whose issue has a malformed `Depends on` line with `MALFORMED_DEPENDS line <n>: <the line>` (`"malformed"` in `--json`), and exits 1 for either; `chains.py link` refuses, before any write, a link that would close a cycle, with `closes a cycle:` and the loop (spec 041) (#715)
