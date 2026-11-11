### Fixed

- The gate's App check no longer reads the App's bot account anonymously on every tick, which spent the host's shared 60-an-hour limit: it keeps the bot's id in its state folder's `bot-ids.json`, by App id and slug, and reads GitHub only on a miss; a dry run, `shipmill status`, and `shipmill factory` read that file but never write it, and a malformed one exits 2 naming it (#1034)
