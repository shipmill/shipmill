### Added

- Spec 087's sandbox probe records how a sandboxed command reaches one local port: `"127.0.0.1:<port>"` in `sandbox.network.allowedDomains` opens that port alone, only through the sandbox's proxy, and `allowLocalBinding` opens every local port (Claude Code 2.1.330, macOS) (#1588)
