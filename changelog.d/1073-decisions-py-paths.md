### Added

- Decisions: `decisions.py`'s `policy()`, which `retro.py gather --decisions` and `decisions.py add --zone` read, accepts `[decisions.paths.<zone>]` with the package's refusals and leaves every zone's level as it is; on Python 3.10 it refuses the table with its "use 3.11+" message, spec 057 (#1073)
