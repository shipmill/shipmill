### Fixed

- Triage: a relayed answer out of its grammar on an item with the `needs-decision` label off reads RELAY_REFUSED, an action the gate hands in tier 6, so a session asks again; the watch's upgrade and direction rows say `relay not counted: <reason>; ask again` instead of taking it as answered (#1302)
