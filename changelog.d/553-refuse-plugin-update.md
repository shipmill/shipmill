### Removed

- `[agents] plugin_update` (spec 031): a config that sets it, whatever its value, now exits 2 with `[agents] plugin_update was removed (spec 031); delete it`, and `doctor` fails the policy with that line instead of warning; delete the key (#553)
