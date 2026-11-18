### Changed

- A relayed answer is read by one relay grammar: lines after a `Note:` line are not read, a `Basis:` line is recorded only, and `own: <text>` is the maintainer's own words; a relay with any other line past its answer is no longer read as the maintainer's own words but refused with `needs-decision: relay not counted: format`, and the session that asks again says why under the question's zone line. A direct reply and a one-line relay take the same options as before (#1222)
