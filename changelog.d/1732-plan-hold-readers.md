### Changed

- `fleet.py queue` times a goal plan re-checked after its hold was met from the later of its newest revision and the hold's `met_at`, so a plan held for a month doesn't come back as the oldest item; a held plan, and one whose re-check is due, stay off the queue. product-intake's skill and the plan's triage line give the `hold until <a date, #N, or release>` answer, and the ship-watch skill's Fleet section says a held plan is no `PLAN` row until its condition is met (spec 098) (#1732)
