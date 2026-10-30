### Changed

- `watch_state.py`'s full report makes fewer `gh` calls: the comments of the pull requests labelled needs-decision or decided, open and closed, are one GraphQL query per 50 items instead of one REST read each, and the postmortems folder and its files' texts are one query instead of a listing and a read per file; on shipmill's own repo a run went from 45 calls in 54 s to 37 in 46 s, with the same rows (#842)
