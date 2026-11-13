### Added

- `shipmill doctor` prints one `verify command` row per `[agents] verify` command from the gate's last check: PASS for `ok`, FAIL with its result, detail, and fix (a missing program's fix is installing it on the gate's PATH, never an allow rule), and WARN `not checked yet` until the gate checks the current list (#1077)
