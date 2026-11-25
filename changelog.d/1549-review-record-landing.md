### Added

- `shipmill review record` ends the review it posts with a `## Landing` section: the landing level and one line per piece of evidence (`checks`, `size`, `record`, `kind`) that `decide classify --pr N` gives at the recorded head, by origin/HEAD's levels; the verdict's marker stays the body's first line, and when that classify fails, or reads the pull request at another head, `review record` exits 2 and posts nothing. The "Who decides" docs name the `area-record` zone, `[decisions.earned]`, the four pieces of evidence, and the three ceiling kinds (spec 083) (#1549)
