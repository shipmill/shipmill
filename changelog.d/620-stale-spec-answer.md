### Fixed

- github-pr-triage lands a spec pull request on a trusted answer only while the spec is the one the maintainer answered on: it compares the pull request's own change to the spec file at the answered head and at the current head, lands through a rebase or a renumbered `D-n`, and asks again with a new needs-decision question after any other change to the spec (#620)
