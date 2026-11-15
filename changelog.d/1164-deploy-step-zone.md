### Added

- The `deploy-step` zone (default `ask`, no floor): `shipmill decide classify --pr N` names each changed job of a deploy workflow (one an `[environments]` table names, or with an `environment:` key) that no run on the pull request's `Proof:` line ran at the head's content of the file, and `--files` names each deploy workflow, so `pr_gate.py` reads such a pull request as NEEDS_DECISION until the maintainer accepts it; classify only reads the runs, with GETs (spec 063) (#1164)
