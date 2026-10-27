### Fixed

- A parent issue or `upstream` report whose `## Check` the maintainer chose to run by hand ("leave it open") no longer starts a gate session every tick: the session posts a `<!-- shipmill:check-waiting -->` comment naming who answered, and `triage_state.py` reads the parent as WITH_PERSON (`check waiting on @login`) and `upstream_state.py` the report as ASKED, neither an action, until a child closes or a check-failed or verified comment follows (#740)
