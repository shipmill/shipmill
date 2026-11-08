### Changed

- The evals of the agents' instructions stopped (D-74, superseding D-72): `evals.yml` stays `workflow_dispatch` only, no pull request needs an `evals` check, D-37's gate is retired with no baseline that brings it back, and github-pr-triage and spec 025 say so; every skill's "Improve the skill" section and the postmortem template now put a rule that must hold into code instead of asking for a case under `evals/`; the suite and `shipmill evals` stay in the tree (#972)
