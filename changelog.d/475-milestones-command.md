### Added

- `shipmill milestones` (`--json` for one object) prints spec 022's MILESTONE_WAITING and MILESTONE_OVERTAKEN rows, the overtaken one with its number, the version to rename it to, and the rename through `shipmill gh api`; github-ship-watch's `watch_state.py` runs it when a lane sets `milestone = true`, so `shipmill status --rows` and `--json` show both rows, MILESTONE_OVERTAKEN is an action (exit 1), and under "watch" a pass renames an overtaken milestone (#475)
