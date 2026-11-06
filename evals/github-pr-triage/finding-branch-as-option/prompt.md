---
name: finding-branch-as-option
tags: [github-pr-triage]
runs: 3
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Write, Glob, Grep, Skill]
---

/shipmill:github-pr-triage shipmill/shipmill post-merge review of #888, which merged before anyone reviewed it; review only

This checkout is shipmill itself at #888's merge commit (HEAD), so its CLI runs as
`uv run shipmill`; its `.github/shipmill.toml` sets `[agents] app_id`, and the App writes as
shipmill-romamo[bot]. #888 merged as a merge commit: what it landed is
`git diff HEAD^1 HEAD`, where `HEAD^1` (d1277f50) is main just before it.

#888, "Catch the local default branch up on each gate tick", builds D-66 (issue #886). Its
summary: each `shipmill gate` tick now catches the repo's local default branch up to
`origin/<default>` by fast-forward only, never with `switch`, `stash`, `reset`, `rebase`, or a
forced refspec; `[agents] catch_up = false` turns it off. The default branch is the config's
`branch` key, read from the repository's own `.github/shipmill.toml`. The step runs after the
tick's decision, beside the gate's other git calls in `src/shipmill/gate.py`, and the
ahead/behind read moves to the new `src/shipmill/catch_up.py`.

This case is offline: GitHub holds no recording, so don't run `gh` or `shipmill gh` reads
(`pr view`, `pr diff`, `api`); what you need is above and in this checkout. No reviewer agent
is available here: review the change in this session, then end with your report, the
verdict and each finding with its file and line.

Headless: nobody can answer AskUserQuestion or a permission prompt. A decision for the user,
or a tool call that was denied, goes in your report.
