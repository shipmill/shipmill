### Fixed

- github-ship-watch reports a gate job on this Mac whose checkout is gone as `GATE_CHECKOUT_MISSING`, an action for a person with the fix that adds the folder back and restarts the job: launchd stops such a job before `shipmill gate` runs, so it had stopped unreported. Every watch on the host reads every gate job, and `shipmill factory`'s sessions check fails on it (#1155)
