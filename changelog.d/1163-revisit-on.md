### Added

- `triage_state.py`: a postpone comment's `` Revisit on: `<path>` `` line keeps its issue POSTPONED (`waits on <paths>`) until a file a path matches changes between the newest stable tag before the comment and the newest one, then reads REVISIT naming the file, instead of REVISIT on every stable tag; one compare per base tag, and no base tag, a compare at GitHub's 300-file cap, or no line read REVISIT as before, an unreadable line at once (spec 061) (#1163)
