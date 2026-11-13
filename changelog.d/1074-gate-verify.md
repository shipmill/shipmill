### Added

- `shipmill gate` checks `[agents] verify` on a real headless launch, after the hook self-test and the preflight, when the state directory's `verify.json` holds no result for the fingerprint of the list, the tool flags, the settings files, the PATH, and the plugin's version, or holds a failing one `retry_hours` old; the decision line ends with `; verify: ...`, the session starts whatever the result, and with `notify = true` a failing result sends one desktop notification per fingerprint (#1074)
