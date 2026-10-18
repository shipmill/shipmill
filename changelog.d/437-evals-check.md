### Added

- Evals: `shipmill evals check [--repo DIR]` validates the agents' eval suite, `evals/`, without a model, exiting 1 with one line per case naming the rule it breaks (an unlisted case or a listed one with no directory, a skill not under `skills/`, tags not naming it, a malformed source, an unknown kind, a commit that does not resolve, no deterministic grader outside a finding case, `max_turns` above 40 or `timeout_seconds` above 900); a repository with no `evals/` passes, and CI runs it on every pull request (#437)
