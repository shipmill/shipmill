### Added

- `[agents] identity` takes a third value, `"none"`: agents don't write to GitHub in this repo, refused beside `app_id` as `"host"` is; shipmill-setup's `setup_state.py` reads the same three values and prints one Identity row (`IDENTITY_APP`, `IDENTITY_HOST`, `IDENTITY_NONE`, or `IDENTITY_UNCHOSEN`, which names the Apps the host already has: a key file in `~/.config/shipmill/`, never opened, and the owner's other repos' `app_id`), an action only with an `[agents]` section (#1273)
