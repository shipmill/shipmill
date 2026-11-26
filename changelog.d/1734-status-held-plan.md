### Changed

- `shipmill status --item N`, its record, and the summary give a goal plan whose hold was met, its re-check due (spec 098's PLAN_HOLD_MET), to the agent that re-checks it instead of the maintainer; once re-checked it waits on the maintainer as an unanswered plan does (#1734)
