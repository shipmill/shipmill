### Added

- `shipmill review history <N>` prints the history of the files a pull request touches: reverts on the default branch within `--days` (commits that revert a commit, and merged pull requests with a `Reverts #M` line) and the other open pull requests sharing a file, each with an id `H-n`, at most `--limit` per kind, `--before <sha>` to read it as it stood at a commit, `--json`, and an untrusted author's text left out (#1249)
