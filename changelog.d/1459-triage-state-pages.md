### Changed

- `triage_state.py` reads open issues 20 a page instead of 100 on the first page and 50 on later ones, and the first query's closed decided issues 20 instead of 50, so its first query costs GitHub 2 rate-limit points instead of 8 and each later page 1 instead of 3: GitHub charges a query by its worst-case requests, an open issue's six nested connections times the page; every issue is still read, over more pages (#1459)
