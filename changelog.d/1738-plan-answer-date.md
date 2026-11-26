### Added

- A goal plan's answer date (spec 106): a PLAN_OPEN plan's note ends `answer by <date>`, seven days after its newest revision or its re-check after a hold, or the date the newest trusted `answer by YYYY-MM-DD` reply sets (a reply that answers nothing), and `--json` gives it as `answer_by`; past that date in UTC the plan reads PLAN_OVERDUE, no action. The ship watch accepts PLAN_OVERDUE and still lists the plan as waiting on the maintainer (#1738)
