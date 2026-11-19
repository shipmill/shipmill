### Fixed

- `shipmill roles` and `shipmill status` work in a gate session on a repo whose `[agents.roles]` lists no maintainer: they read the gate's `SHIPMILL_MAINTAINER` before `gh api user`, which answers 403 under the App's installation token, and a malformed value exits 2 naming the variable; outside the gate the host's `gh` login is read as before (#1314)
