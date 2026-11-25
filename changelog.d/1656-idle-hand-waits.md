### Added

- Gate: an idle hand records the item its subject's newest waits-on marker by the bot names as `waits` in `handed.json`, and the change check reads those items (one GraphQL query per 100, none when no idle hand has `waits`), so an idle subject is handed again on the first tick after what it waits on changes, in any repo; `[agents]` reads `idle_days` (default 3) and `parked_days` (default 7), each 0 to 90, which later builds of spec 092 act on (#1656)
