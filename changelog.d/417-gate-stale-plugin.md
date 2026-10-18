### Changed

- `shipmill gate` starts no session while the `shipmill@shipmill` install a session in its
  checkout would load is older than the latest release (D-35, superseding D-23's "the
  session still starts"). It reads that install at any scope, user scope included, as
  Claude Code picks it (the most specific scope installed for the checkout's project: local,
  project, user, then managed; a linked worktree's project is its main checkout), after the
  daily `plugin_update` when that is on. The tick reads `PLUGIN_STALE: ...` with the
  install's version and scope, the latest release, and the command that updates it, stops
  and starts no session, and the next tick with a current install launches; a failed read
  is printed and the session starts. `gate --json` adds `loaded`. `shipmill status` shows a
  paused gate as waiting on you with that command, and github-ship-watch's
  `SHIPMILL_VERSION` (so `status`, `doctor`, and the setup checklist) names the install a
  session loads, warning when it is behind (#417)
