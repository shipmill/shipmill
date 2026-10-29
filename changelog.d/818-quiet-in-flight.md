### Added

- `shipmill gate`'s QUIET line ends with what is in flight: the open pull requests waiting on CI, waiting to land, and failing CI, the last landed pull request, and the last session that ended with a result (`last-result.json`), all from the change check's one query, which now also reads the default branch's last 10 commits' merged pull requests; `--json` and `tick.json` carry it as `in_flight` (#818)
