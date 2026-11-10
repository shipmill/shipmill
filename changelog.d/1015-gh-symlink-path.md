### Fixed

- The session's gh helper runs gh at the path PATH names, such as `/opt/homebrew/bin/gh`, not its symlink's versioned target, so a `brew upgrade` during a session no longer breaks every gh call with exit 126 (#1015)
