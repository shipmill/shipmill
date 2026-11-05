### Changed

- Evals: `evals.yml` authenticates through Anthropic's Workload Identity Federation, trading the job's GitHub OIDC token for a short-lived Anthropic one, and reads no `ANTHROPIC_API_KEY` secret (#442)
