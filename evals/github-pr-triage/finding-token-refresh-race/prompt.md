---
name: finding-token-refresh-race
tags: [github-pr-triage]
runs: 3
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Write, Glob, Grep, Skill]
---

/shipmill:github-pr-triage shipmill/shipmill post-merge review of #879, which merged before anyone reviewed it; review only

This checkout is shipmill itself at #879's merge commit (HEAD), so its CLI runs as
`uv run shipmill`; its `.github/shipmill.toml` sets `[agents] app_id`, and the App writes as
shipmill-romamo[bot]. #879 merged as a merge commit: what it landed is
`git diff HEAD^1 HEAD`, where `HEAD^1` (46f33d44) is main just before it.

#879, "shipmill gh writes as the decider with their stored token in assisted mode", builds
spec 051's S-051-7, S-051-8, S-051-9, and S-051-12 (issue #866). Its summary: with
`[agents] author = "decider"`, `shipmill gh` runs `issue create`, `pr create`, and `pr merge`
with the decider's user access token stored by `shipmill app-login`, refreshing it when it
has expired (`src/shipmill/app_login.py`), and every other command with the App's
installation token. Several `shipmill gh` processes run on one host at once: gate sessions,
and a session and its agents.

This case is offline: GitHub holds no recording, so don't run `gh` or `shipmill gh` reads
(`pr view`, `pr diff`, `api`); what you need is above and in this checkout. No reviewer agent
is available here: review the change in this session, then end with your report, the
verdict and each finding with its file and line.

Headless: nobody can answer AskUserQuestion or a permission prompt. A decision for the user,
or a tool call that was denied, goes in your report.
