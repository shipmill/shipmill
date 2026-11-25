### Added

- Before a sandboxed headless launch the gate fails the tick, and starts no session, when a `.claude/settings.json`, `.claude/settings.local.json` or `~/.claude/settings.json` would widen the session's sandbox or a Linux host can't confine (no `bwrap` user namespace, or no `socat`); `shipmill doctor` gains a `sandbox` row in headless mode listing what the sandbox opens and grants, and `doctor --sandbox` checks it for a gate that isn't a launchd job (#1534)
