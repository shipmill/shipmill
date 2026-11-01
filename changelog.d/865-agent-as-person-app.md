### Changed

- `AGENT_AS_PERSON` in `shipmill doctor` and `shipmill status` skips an agent-marked record a person authored through the repo's App, whose `performed_via_github_app` id is `[agents] app_id` (spec 051's assisted mode), and still flags one a person's own token or another App made; GraphQL doesn't expose the field, so each record the search would flag is read once more with `gh api`, and one that can't be read that way stays flagged (#865)
