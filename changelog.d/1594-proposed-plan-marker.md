### Fixed

- `pr_gate.py` reads a `Proposed plan:` written under its `<!-- shipmill:needs-decision -->` and zone lines, as `fix = "propose"` writes it, as the issue's allowed files: the leading `<!-- shipmill:... -->` lines are skipped, so an agent's pull request changing a file outside the plan's `Files:` line is held instead of reading READY (#1594)
