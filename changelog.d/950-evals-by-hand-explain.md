### Changed

- Evals: `evals.yml` runs only by hand (no weekly schedule) until the baseline passes 60%, and every run's summary explains each case that did not pass with `shipmill evals explain` (error, failed graders, turns, cost, last message, and a harness or agent verdict), its artifact holding the session traces and each case's `.eval/gh.jsonl` (#950)
