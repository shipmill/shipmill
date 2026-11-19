### Added

- A pull request's `## Plan` may say `Kind: fix` or `Kind: refactor` and name the existing test files it had to edit on a `Tests changed:` line; github-issue-resolve commits a `Kind: fix` change's test first and alone and leaves existing test files alone in a `Kind: refactor` change, and github-pr-triage's reviewer runs `test_proof.py <kind>` on a plan with a `Kind:` line, reporting `UNPROVEN` and a `NO_TEST` fix as findings, `BASELINE_RED` as the base's failure, and a "Test proof" line in its report; `pr_gate.py` reads neither line (spec 076) (#1286)
