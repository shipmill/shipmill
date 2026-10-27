### Fixed

- `shipmill status` no longer exits 2 with no report when one of the host's own reads fails (`claude agents --json`, `claude plugin list`, or the marketplace's latest release): it reads the sessions and shipmill sections on their own, as `shipmill factory` does, so the failure is that check's error on the `factory` line, the verdict reads STUCK, and every other line still prints; `watch_state.py --no-host` leaves those rows out of the full run (#745)
