### Added

- A busy self-hosted runner no longer reads as a stalled one: each RUNS_ACTIVE row of github-ship-watch's report ends with what the run's jobs do (`running: <job> since HH:MM UTC`, `no job started`, `no job running`, or `jobs unreadable` when GitHub refuses the read), and each `pending:` line of github-pr-triage's gate says `(queued)`, `(running since HH:MM UTC)`, or `(pending)` (#1014)
