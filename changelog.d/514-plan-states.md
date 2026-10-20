### Added

- `intake_state.py --plans` reads each goal plan issue's state from the maintainer's reply: PLAN_OPEN, PLAN_ANSWERED (`decline` or `edit`), PLAN_ACCEPTED until every `feature` and `fix` item is filed (and in the named milestone), PLAN_FILED, PLAN_MALFORMED naming the line, and PLAN_DECLINED with the reason; only an OWNER, MEMBER, or COLLABORATOR other than the `--bot-login` answers, a `plan-revised` comment makes an earlier answer stale, and an accept older than the body's last edit reads PLAN_OPEN (#514)
