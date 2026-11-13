### Added

- `[agents] verify` lists the commands a headless session relies on for verification, and `shipmill.verify` checks each one as such a session would meet it: the allowlist, the delivery hook, and a run through `$SHELL -c` with the gate's PATH, in a worktree at `origin/<default>` that it removes when it ends; the gate and doctor read the result in later changes (#1072)
