### Added

- `shipmill status` and the watch name why the gate waits: `GATE_PAUSED <limit|auth> until <when>` while the credential its sessions use is paused, with the token's fix for `auth`, and `GATE_RETRY <item> after <time>: <n> error ends in a row` for each item in backoff; `shipmill status --item N` says the pause or the backoff for an item the gate would take up, instead of "the gate takes it up on a coming tick". Spec 089 is built (#1556)
