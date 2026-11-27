### Fixed

- `shipmill status` no longer lists the watch's report-only PLAN_FILED row under "other": an accepted plan waiting on its items with another parent stays silent in the summary, since it waits on its work rather than on you, and `shipmill status --item` still says what it waits on (#1787)
