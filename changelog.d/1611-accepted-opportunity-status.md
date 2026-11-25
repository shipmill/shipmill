### Fixed

- `shipmill status --item` and `status --summary` read an opportunity the maintainer accepted (labelled `planned`, named on the watch's SPEC_DUE row) as waiting on triage's spec gate, an agent's, no longer on the maintainer's accept (#1611)
