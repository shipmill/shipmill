### Fixed

- Triage: an open issue with a `## Check` and no sub-issue reads by its check once its own pull request merged, as a parent does: VERIFY_DUE, CHECK_FAILED after a trusted check-failed comment, or WITH_PERSON after a trusted check-waiting one, when a merged pull request links it (a closer, or `Part of #N`, not reverted); it read UNBLOCKED, DONE_NOT_CLOSED, NEEDS_PR, TRIAGED, or NEW. Without such a pull request, its holds all closed, it still reads UNBLOCKED, work to build (a feature issue whose spec pull request merged is split first), and a `postponed` one reads POSTPONED (#1671)
