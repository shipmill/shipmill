### Added

- Spec 087's sandbox probe, macOS half: `docs/design/probe-087/` starts a real `claude -p` with the spec's `sandbox` and `permissions` settings and a canary in `~/.ssh`, and `docs/design/agent-modes.md` records on Claude Code 2.1.330 what it refused, the refusal text the tick reads, and four departures from the spec that wait on a decision (`gh` and a denied `hosts.yml`, user `permissions.allow` widening Edit and Write, no local port, the uv cache under the git dir) (S-087-1) (#1524)
