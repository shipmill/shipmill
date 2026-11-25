### Changed

- Spec 087 follows the macOS sandbox probe (D-105): a sandboxed session gets its own `GH_CONFIG_DIR` while `~/.config/gh/hosts.yml` stays denied, its uv cache moves outside the git dir, a `permissions.allow` entry widening Edit or Write fails the launch (S-087-13), and tunnels (S-087-10, #1589) wait for a probe of local ports (#1588) (#1524)
