### Fixed

- Plugin: the fix printed for a stale shipmill@shipmill install (the gate's `PLUGIN_STALE` tick, `doctor`, `status`, the setup checklist, and github-ship-watch's `SHIPMILL_OUTDATED`) runs `claude plugin marketplace update shipmill` before the update or reinstall, and the gate's daily update with `plugin_update = true` refreshes the marketplace once before updating its checkout's installs, reporting a failed refresh and still trying the update; `claude plugin update` alone left an install behind when Claude Code's copy of the marketplace predated the release (#477)
