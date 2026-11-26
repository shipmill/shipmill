### Changed

- `shipmill status --item` follows a held goal plan: while held, its holder is `postponed`, waiting on the event `held until <condition>`; once the hold is met, product intake's re-check holds it; once re-checked, it waits on the maintainer's answer again. `shipmill status` adds no WAITS ON YOU reason for a held plan or one whose re-check is due. The watch's `--item` read gains a `PLAN_HELD` row naming each held plan's condition, which the full report doesn't list (spec 098) (#1734)
