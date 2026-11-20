### Fixed

- `shipmill gate`: a `needs-decision` question a session asked on a pull request and the maintainer answered while that session still ran is handed on the first tick after the session ends, instead of waiting out `retry_hours`; the tick drops the ended session's hand of each pull request the change check reads labelled `needs-decision` and updated since the hand, and leaves every other hand as it was, so a labelled pull request the session left untouched still waits (#1447)
