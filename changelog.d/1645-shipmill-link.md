### Added

- `shipmill link` and `shipmill unlink` record and remove a hold between issues and pull requests: on an issue GitHub's native relation and a strict `Depends on` line, on a pull request the line in its body (spec 041 amended). The gate doesn't hand a pull request whose `Depends on` names an open item, `queue` and `status --item` hold it by its target, and triage reads HOLD_UNLINKED for an agent comment that names a wait with no link (#1645)
