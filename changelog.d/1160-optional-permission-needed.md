### Added

- Each optional permission of the App now says which config needs it: Deployments: read is needed by a config that declares `[environments]` (spec 060). `shipmill doctor`'s `app` row and the gate's `warning:` line still name every optional permission the installation lacks, needed or not, and `setup_state.py` wants the `shipmill-permission` label in a repo whose config sets `[agents] app_id` (#1160)
