### Added

- `[agents.sandbox] local_ports = true` opens every local port to a sandboxed headless session on a macOS gate, and `[agents.sandbox.grant]` declares what a trusted person's `sandbox:<kind>` label may open for one launch; on Linux `local_ports` and tunnels are dropped and named until the Linux probe, a grant's `read` or `write` entry may not reach a credential store, no key opens a Unix socket, and `decide classify` asks for a pull request that adds a grant entry or sets `local_ports` to true (#1649)
