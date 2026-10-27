### Added

- A parent issue with a `## Check` section reads VERIFY_DUE, not UNBLOCKED, once its sub-issues close, CHECK_FAILED after a trusted `<!-- shipmill:check-failed -->` comment newer than its last hold's close, and, closed by a pull request, a commit, or the session's bot without a trusted `<!-- shipmill:verified -->` comment, VERIFY_CLOSED instead of SUSPECT_CLOSE, so it closes when its result is seen in production, not when its last child merges (spec 042) (#717)
