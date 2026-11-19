### Security

- `intake_state.py` reads a `Triage:` comment only from an OWNER, MEMBER, or COLLABORATOR or the `--bot-login` in its other readers too, so anyone else's `Triage: **feature**` no longer makes an accepted opportunity read HANDED_OFF, their `Triage: ... Serves: G-n` no longer marks a goal served and holds back its PLAN_DUE, and a decline reason skips only a trusted triage comment (#1384)
