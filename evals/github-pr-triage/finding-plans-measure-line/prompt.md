---
name: finding-plans-measure-line
tags: [github-pr-triage]
runs: 3
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Write, Glob, Grep, Skill]
---

/shipmill:github-pr-triage shipmill/shipmill post-merge review of #533, which merged before anyone reviewed it; review only

This checkout is shipmill itself at #533's squash commit (HEAD), so its CLI runs as
`uv run shipmill`; its `.github/shipmill.toml` sets `[agents] app_id`, and the App writes as
shipmill-romamo[bot]. What #533 landed is `git diff HEAD^ HEAD`, where `HEAD^` is main just
before it.

#533, "Check a goal plan's body and list its items (S-028-6, S-028-7)", fixes #507. Its
summary: it adds `skills/product-intake/scripts/plans.py` (spec 028, standard library only,
Python 3.10+). `plans.py check FILE [--root DIR]` holds a plan body to the grammar in spec
028's Behaviour, the goal it names listed in `docs/product.md` (read the way
`shipmill product ids` reads it, a moved Goals section followed); `plans.py items` lists a
plan's work items and the issue carrying each one's marker. Tests are in
`tests/test_plans.py`.

This case is offline: GitHub holds no recording, so don't run `gh` or `shipmill gh` reads
(`pr view`, `pr diff`, `api`); what you need is above and in this checkout. No reviewer agent
is available here: review the change in this session, then end with your report, the
verdict and each finding with its file and line.

Headless: nobody can answer AskUserQuestion or a permission prompt. A decision for the user,
or a tool call that was denied, goes in your report.
