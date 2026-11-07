### Changed

- The agents' evals no longer run on a pull request: `evals.yml` runs weekly and when the maintainer dispatches it, until the default branch's baseline passes 60% of its runs (D-71), and github-pr-triage waits on no `evals` check meanwhile unless one was dispatched for the head (#947)
