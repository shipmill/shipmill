### Changed

- A headless gate session's rule of one allowlisted command per Bash call names the form that passes: set a variable with `uv run env VAR=value <command>`, never a `VAR=value uv run` or `env VAR=value` prefix, and import the package through `uv run pytest`, not `PYTHONPATH=.`; the implementer and reviewer briefs, `github-issue-resolve`, and the needs-decision reference carry it (#842)
