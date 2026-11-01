### Added

- A refused config key now shows where you look: `shipmill doctor` prints a FAIL row named `refused` with its message, beside a PASS `policy` row, and runs every other check; `shipmill status` prints a FAIL row with the key's fix; and every `--json` that prints an object (`decide levels`, `decide classify`, `autonomy`, `roles`, `milestones`, `factory`, `gate`, `app-install`, `upgrade --apply`) carries a `"refused"` list of `{"key", "spec", "off", "fix"}`, empty without one (spec 052) (#860)
