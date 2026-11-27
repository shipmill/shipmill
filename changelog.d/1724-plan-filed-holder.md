### Fixed

- `shipmill status --item` and `shipmill queue` no longer show the maintainer as the holder of an accepted goal plan whose kept items all have another parent: the watch carries such a plan in a report-only PLAN_FILED row, `#N(another parent: #a, #b)`, that starts no session, and the plan reads as waiting on those open items, then on product intake once its work has closed (PLAN_DONE) (#1724)
