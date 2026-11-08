### Fixed

- `pr_gate.py` reads the pull request's title for closing keywords too: under a squash merge it is the landed commit's subject, so a title naming an issue the body lists as `Part of #N`, or an open issue with a `## Check`, is refused as a commit's keyword is (#987)
