### Fixed

- Triage: an open issue with a `## Check` and no sub-issue reads by its check once its work merged, as a parent does: VERIFY_DUE, CHECK_FAILED after a trusted check-failed comment, or WITH_PERSON after a trusted check-waiting one, once its holds all closed (it read UNBLOCKED) or, with no hold and no open pull request, once a `Part of #N` pull request merged (it read NEEDS_PR, TRIAGED, or NEW); a `postponed` one still reads POSTPONED (#1671)
