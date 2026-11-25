### Added

- Gate sandbox: the first tick after a sandboxed session ended names what the sandbox refused in it, `sandbox refused <n>: <first words> (<host or path>)` with the `[agents.sandbox]` entry that allows it, in its line and `tick.json`; with `--sandbox` the `[agents] verify` check runs each command through `srt` with the session's rules and reads `refused by sandbox`, or `not checked` without `srt` on the gate's PATH; and the needs-decision protocol tells a sandbox refusal from a denial, a hook refusal, and a missing program (#1535)
