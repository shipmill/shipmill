### Fixed

- The merge gate reads the newest trusted answer to a needs-decision question, not the first: a bare `1` after a reply with words takes the recommended option, and a reply with words after a bare `1` holds the item again; the retro's answer count keeps reading the first answer (#1199)
