### Fixed

- `shipmill queue` and `status --summary` put a person's item assigned to the maintainer (spec 036's `maintainer` role: its listed users and teams, else the host's `gh` login) under `waits on you`, with why `assigned to you: ...`, instead of `waits on people` and `waits on nobody` (#1641)
