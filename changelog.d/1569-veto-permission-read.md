### Fixed

- `pr_gate.py` stops with exit 2 when it can't read the permission of the maintainer a relayed veto names (no `[agents.roles]` maintainer listed), instead of dropping the veto and letting the pull request land; a 404 still reads as no maintainer, and an answer's failed read keeps its safe side (#1569)
