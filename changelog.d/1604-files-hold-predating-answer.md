### Fixed

- `pr_gate.py` no longer lifts an agent's `files:` lines on the maintainer's answer on an issue given before the pull request opened; that answer still lifts the other asks, and only an answer whose question names the judged head, or a head with the same change, lifts a `files:` line (S-085-14, D-109) (#1604)
