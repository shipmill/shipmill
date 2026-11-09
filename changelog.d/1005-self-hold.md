### Fixed

- A hold sentence in an issue's own comment that names the issue itself ("#126 keeps waiting on #125" on #125), as `#N`, `owner/repo#N` or its URL in any case, no longer holds it: triage read such an issue BLOCKED on itself forever, and ship-watch held an agent's draft on its own number the same way (#1005)
