### Added

- A PR reviewer's REFUSE gets a second look before it is recorded or handed back: the reviewer lists each unfixed finding as `F-n`, `blocking` or nit; a fresh agent, given the blocking findings and not the verdict, marks each `confirmed` with a failure scenario, `rejected` with the code that handles it, or `minor`; the PR is refused only on a confirmed finding, the record carries a "Second look" part and `--findings` counts, and the weekly retro passes `--reviews` (#1279)
