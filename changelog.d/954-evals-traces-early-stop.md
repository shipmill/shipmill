### Fixed

- Evals: a dispatched run keeps its session traces and each case's `.eval/gh.jsonl` (the eval run's `TMPDIR` is under the job's temp, which the breakdown step reads), `shipmill evals explain` reads a session that stopped within a quarter of its case's `max_turns` with no gh write as **harness**, `the session stopped early after N turns`, reading each failed case's limits from the suite at `--repo`, and the run's budget is 25 USD instead of 15, so a full run of the suite fits (#954)
