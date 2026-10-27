### Added

- The coordinator's `upstream_state.py` reads an `upstream` report with a `## Check` whose children all landed as VERIFY_DUE in place of CLOSE_DUE `completed`, and as CHECK_FAILED after a trusted `<!-- shipmill:check-failed -->` comment newer than its newest child close; both exit 1, and the watch's UPSTREAM_DUE row names them, so the report closes when its fix is seen in production (spec 042) (#718)
