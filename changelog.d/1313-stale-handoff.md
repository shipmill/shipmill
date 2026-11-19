### Added

- `triage_state.py` reads an open person's item (labelled `role:<name>` or `human`) whose sub-issue parent closed as STALE_HANDOFF, an action noted `parent owner/repo#N closed`, until a trusted `<!-- shipmill:still-waits -->` comment after the close; `watch_state.py` lists it in an ISSUES row whose fix is "close it or say why it still waits on the maintainer"; and `shipmill gh issue close`, as the App, refuses with exit 2 to close an issue with an open person's sub-issue, naming it (#1313)
