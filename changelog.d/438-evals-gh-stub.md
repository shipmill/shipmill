### Added

- Evals: eval cases run offline with no token: `evals/bin/gh` answers reads from a case's recorded fixture, logs every read, write, and miss to `.eval/gh.jsonl` without contacting GitHub, and records reads with `EVAL_GH_RECORD=1`; `evals/scaffold.sh` sets a case's workspace at its commit with its fixture at `.eval/`, and the shared `no-miss` grader fails a run that read anything unrecorded (#438)
