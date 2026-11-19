### Fixed

- Merge gate: a base check rerunning after it failed on the base's head reads PENDING with a `base: pending: <check> rerunning on <base>@<sha7>` line instead of letting a pull request read READY, so landing resumes only once the rerun is green (D-75); the base's check runs are read with every attempt, in the same one read (#1310)
