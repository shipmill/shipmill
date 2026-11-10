### Added

- `specs.py same-approval SPEC ANSWERED_HEAD HEAD [--base REF]` compares a spec pull request's own change to its spec at the head a trusted answer was given at and at its head now, leaving out only format (rewrapped text and whitespace, the `status:` line, an empty or placeholder section, the same `D-n` ids in another shape, a claimed `D-n` renumbered): it exits 0 when the answer still covers the spec and 1 listing each other difference by section, so a format-only fix no longer asks the maintainer again, and github-pr-triage quotes that output when it does (#1007)
