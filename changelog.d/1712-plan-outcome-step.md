### Added

- A finished goal plan reports its outcome (spec 097): the watch lists PLAN_DONE in the PLANS row as an action, so `shipmill gate` starts product intake for it; product-intake's skill and plan.md give its step, checking the Order's end state against trusted text, closing an open plan as completed, and posting the `<!-- shipmill:plan-outcome -->` comment with its `Holds:` and `Still missing:` lists; the goal's next plan writes `Follows: #P` after `Measure:`, which `plans.py check` accepts once there and refuses anywhere else, and answers each missing line (#1712)
