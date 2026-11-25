### Changed

- Gate: an item whose headless session ended `error` is handed again 15 minutes after the death, then 1 hour after the next, then 4 hours after the third; the fourth `error` end in a row holds it for `retry_hours` and reads SESSION_DEAD, where three dead sessions in a row held it before. The run is kept on the item's hand in `handed.json` (`errors`, and `until` while it waits), so it survives another item's session in between, an `ok` end resets it, and a hand whose session ended `error` never turns idle (#1554)
