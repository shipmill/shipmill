### Changed

- `pr_gate.py` reads the checks on the base branch's head commit and reads FAILED, with a `base: red:` line, while one failed there, save for the pull request whose body has a `Repairs: <URL>` line naming that run; a failure from outside the code clears by re-running it on the default branch (D-75) (#963)
