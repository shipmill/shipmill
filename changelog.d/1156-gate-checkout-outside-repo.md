### Changed

- shipmill-setup and `docs/install.md` put a gate's checkout at `~/.local/share/shipmill/gates/<owner>/<repo>`, a detached worktree outside the repo, so a cleanup of the repo's `tmp/` no longer deletes it. A gate under `tmp/shipmill-gate` keeps working and reading as before; setup_state.py warns about it as `GATE_IN_TMP` and shipmill-setup offers to move it once you agree. github-ship-watch reads a gate checkout at the new place as the gate's, and its `GATE_CHECKOUT_MISSING` fix adds one there back as a worktree of your checkout (#1156)
