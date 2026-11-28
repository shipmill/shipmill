### Fixed

- `shipmill status --summary` reads only the sections its lines come from: watch_state.py's new `--open-items` reads the sections `--item` reads, for every open item at once, and skips the releases, deployments, postmortems, chains, drift, active runs, and the host's rows, so the summary no longer waits as long as the full report; its output is unchanged (#1855)
