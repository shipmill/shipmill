### Fixed

- `setup_state.py`'s Identity row no longer stops setup with exit 2 when one sibling's config read fails with anything but 404 (a 5xx, a rate limit, SAML): it names that repo as `owner/name (unread: <reason>)` and the run goes on; the Product row, read with `[agents] app_id`, still exits 2 on such a failure (#1375)
