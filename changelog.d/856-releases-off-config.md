### Changed

- With `mode = "off"`, `.github/shipmill.toml` may leave out `[changelog]`, `[bump]`, `version_files`, and `[lanes]`, so a repo that uses only the agent side loads in `shipmill doctor` and the gate; a table that is there is checked as before, a command that releases exits 2 naming the table it needs, and doctor notes each one left out, such as `releases off (mode = "off"): no [changelog]`; under `mode = "release"` or `"dry-run"` they stay required with the same messages (#856)
