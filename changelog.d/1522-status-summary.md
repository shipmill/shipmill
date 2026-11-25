### Added

- `shipmill status --summary [--json]` says in a few lines whether the gate works (its last tick, the session running now, the last result, the last landed pull request) and who holds the open work: you, the agent, needs attention (a session that ended in error, a paused credential, an idle hand), or nobody, each item counted once from the conditions `status --item` gives it (spec 091) (#1522)
