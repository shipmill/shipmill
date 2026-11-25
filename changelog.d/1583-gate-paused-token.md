### Fixed

- The watch's `GATE_PAUSED` reads the gate's token file as the gate does: a `--claude-token` file that is missing, or a token file the gate refuses (not a regular file, another user's, readable by group or others, not a token), prints no row instead of the login's pause and its `claude auth login` fix; a `gate.json` that isn't a JSON object stops with exit 2, as the gate refuses it (#1583)
