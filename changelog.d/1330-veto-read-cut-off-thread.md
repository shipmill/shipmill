### Fixed

- Merge gate: a thread cut off at its newest 100 comments no longer reads READY when they hold a trusted veto whose decided marker is older than them; the pull request reads BLOCKED with a `decided: the thread of #N is cut off at 100 comments: a veto in it can't be ruled out handled or not, so a person looks` line, while a complete thread, or a cut-off one with no unanswered veto in the window, reads as before (#1330)
