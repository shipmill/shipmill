### Fixed

- `shipmill gate`: a `needs-decision` question a session asked on a pull request and the maintainer answered while that session still ran is handed on the first tick after the session ends, instead of waiting out `retry_hours`; the tick drops the ended session's hand of each pull request the change check reads labelled `needs-decision`, and leaves every other hand as it was (#1447)
