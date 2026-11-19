### Fixed

- github-pr-triage's reviewer brief rebases a pull request onto its own base branch (`{base}`, its `baseRefName`) and runs `test_proof.py` with `--base origin/{base}`, so a pull request stacked on another is read from its own commits and its base pull request's first commit is no longer taken for its test commit; an unstacked pull request's base is the default branch, as before (#1410)
