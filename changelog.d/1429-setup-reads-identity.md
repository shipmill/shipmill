### Fixed

- The setup checklist and github-ship-watch read the agent identity the owner recorded (D-98): with `[agents] identity = "host"` neither asks for an App any more, and `AGENTS_OK` names the host's login the gate's sessions write as; with `identity = "none"` and a gate prompt, setup reads a new `AGENTS_NO_WRITE` action and the watch's `GATE_NO_APP` says the same, since those sessions stop at their first write, so the agents row no longer contradicts the identity row (#1429)
