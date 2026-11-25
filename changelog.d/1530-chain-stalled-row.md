### Added

- The watch's full report gives each chain's head idle 7 days or more (an open issue that holds 1 or more and waits for neither `items` nor `cycle`) a report-only `CHAIN_STALLED` row, `holds K open issue(s), no event for D day(s), waits for <waiting_for>`, with `chains.py show` on it as its fix, from the walk it already makes; no `--tier` or `--sweep` read prints it, it changes no exit code, and `shipmill status` lists it on a `stalled chains` line without changing the verdict (spec 086) (#1530)
