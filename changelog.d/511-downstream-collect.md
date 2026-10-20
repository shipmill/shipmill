### Added

- `shipmill downstream collect` finds each downstream run `downstream start` dispatched by the `shipmill-id` in its run-name, links it as the check's details URL, and concludes the check: `success`, `failure` naming the run's conclusion, or `timed_out` for a required downstream, always `neutral` with the result in the title for a report-only one, and a failure naming the run-name rule when no run shows within 2 minutes; the summary names the tested SHA, links the run, and lists its failed jobs, never a log line (#511)
