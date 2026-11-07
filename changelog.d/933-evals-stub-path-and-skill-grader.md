### Fixed

- Evals: the gh stub reaches the case's session. The session's sandbox can't read the checkout, and the `env.PATH` in the workspace's `.claude/settings.local.json` isn't applied to its shell, so the real `gh` still answered; the workflow now puts the workspace's copy of the stub first on `PATH` as the relative entries `.eval/bin:../.eval/bin:../../.eval/bin`. `shipmill evals check` refuses a case whose prompt opens with a slash command and that grades a `Skill` call, which can't happen there (#933)
