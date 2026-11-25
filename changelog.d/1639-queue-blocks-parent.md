### Added

- Each record of `shipmill queue --json` carries `blocks`, the open issues that wait on the item, in the shape `status --item --json` gives them (`ref`, `bucket`, `waits_on`), and `parent`, the open issue it is a sub-issue of as `owner/name#N` or `null`; `queue --fleet` adds the waiters of every repo it read, `status --item --json` carries `parent` too, `triage_state.py --json` gives an issue's open `parent`, and the schema stays 1 (#1639)
