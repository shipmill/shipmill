### Fixed

- Evals: a case's session runs the offline `gh` stub and its `shipmill` and `uvx` shims, not the real ones, and its git works: the sandbox hid the checkout holding `evals/bin` and the shared clone's objects, so `.eval/gh.jsonl` stayed empty. `evals/scaffold.sh` now copies every object into the workspace, copies `evals/bin/` to `.eval/bin/`, and writes the workspace's `.claude/settings.local.json`, excluded from git, putting `.eval/bin` first on the session's `PATH` and its uv cache at `.eval/uv-cache` (#936)
