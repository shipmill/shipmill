### Added

- An `evals` workflow that runs the agents' eval suite with `claude plugin eval` on a pull request touching the skills, the plugin, `evals/`, or the gate's session paragraphs, weekly, and by hand, and compares a pull request's run against the default branch's baseline (or its merge base's when the baseline is missing, stale, or another model's); a fork's pull request fails naming `gh workflow run evals.yml -f pr=<N>`, and `shipmill evals check --gate` names the kinds short of the first suite's counts; until the suite holds them, the pull request job reports and exits 0 (#448)
