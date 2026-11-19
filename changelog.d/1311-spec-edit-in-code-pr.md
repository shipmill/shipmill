### Fixed

- `pr_gate.py` compares every `approved` or `built` spec a pull request modifies with `specs.py same-approval`, base against head, so a code pull request that changes an approved spec's Behaviour reads NEEDS_DECISION with `spec: <file> changes approved Behaviour` until the maintainer's answer; a change to its format, `status:` line, or Verification alone keeps the verdict (#1311)
