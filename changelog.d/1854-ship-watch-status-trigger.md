### Fixed

- github-ship-watch's description names the status questions ("what's the status", "what's open", "who holds what", "why is an issue not moving") and `shipmill status` (`--summary`, `--item N`), so an agent asked for the status routes to the skill that knows the command instead of assembling it from `gh issue list` (#1854)
