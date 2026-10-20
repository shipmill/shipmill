### Fixed

- A release proposal, an issue, a comment, or release notes too long for one command-line argument no longer fails with `Argument list too long`: shipmill passes every body to `gh` on stdin, and one over GitHub's limit (65,536 characters for an issue or comment, 125,000 for release notes) is cut to fit and ends with a line linking the changelog that holds the full text (#499)
