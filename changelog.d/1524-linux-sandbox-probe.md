### Changed

- `docs/design/agent-modes.md` records the Linux half of spec 087's sandbox probe, run on Claude Code 2.1.332 on Ubuntu 24.04, beside the macOS half, with where Linux differs: a refused path reads `No such file or directory` or `Read-only file system` instead of `Operation not permitted`, `gh api` ran, and git warns it can't read `.gitmodules` (#1524)
