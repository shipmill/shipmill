---
name: fix-plans-measure-line
tags: [github-issue-resolve]
runs: 3
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, Skill]
---

/shipmill:github-issue-resolve shipmill/shipmill#749 triage it, and fix it if a fix is warranted

This checkout is shipmill itself at the commit the session ran on, so its CLI runs as
`uv run shipmill`; its `.github/shipmill.toml` sets `[agents] app_id`, and the App writes as
shipmill-romamo[bot]. The default branch is `main`, at this checkout's HEAD; `origin` here is
a local clone with no `origin/main`, so branch from HEAD, and push to `origin` as usual.

This case is offline: GitHub holds one recording, the issue itself, read with
`gh issue view 749 -R shipmill/shipmill --json title,body,comments,labels,state`. Don't run
any other `gh` or `shipmill gh` read; what else you need is in this checkout.

Headless: nobody can answer AskUserQuestion or a permission prompt. A decision for the user,
or a tool call that was denied, becomes the needs-decision protocol (github-issue-triage's
references/needs-decision.md): mention @romamo, label the item needs-decision, and leave it.
