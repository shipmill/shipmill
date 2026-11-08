### Fixed

- CI lints the workflows with the official actionlint release, pinned and checked by sha256 and cached, instead of an unpinned actionlint-py whose sdist build downloaded the binary from GitHub releases and failed release runs when that answered 504 (#977)
