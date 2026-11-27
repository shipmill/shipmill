### Added

- `specs.py contradictions [--base REF] [--decisions F] [--json] SPEC` reports what a spec's Behaviour and Acceptance criteria name in code spans that the code at REF (default `origin/main`, read through git only) or the decisions log lacks: a missing path, command, flag, or decision, a superseded decision, and, while the spec is not on REF, a name its `Adds:` line declares that REF already has; one `<spec>:<line>: <kind>: <name>: <other side>` line each, exit 1 with findings, 0 with none, 2 on bad input. `specs.py check` and CI don't run it (spec 099, #1698)
