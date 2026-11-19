### Added

- `fleet.py queue` lists a person's item handed to the reader (`--login`, else `gh api user`'s login) as a `YOUR_ITEM` row from `triage_state.py`, and an opportunity waiting for accept or decline, an open goal plan, and an opportunity declined with no reason as `OPPORTUNITY`, `PLAN`, and `NO_REASON` rows from `intake_state.py` (with `--plans` when the repo has `docs/product.md`), each with how long it has waited; the kind column is one character wider to fit `OPPORTUNITY` (#1245)
