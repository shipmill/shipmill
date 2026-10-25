---
name: contract-change-asks
tags: [github-issue-resolve]
runs: 3
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, Skill]
---

/shipmill:github-issue-resolve shipmill/shipmill#892 triage it, and fix it if a fix is warranted

This checkout is shipmill itself, so its CLI runs as `uv run shipmill`. The gate's App
writes as shipmill-romamo[bot].

Headless: nobody can answer AskUserQuestion or a permission prompt. A decision for the user,
or a tool call that was denied, becomes the needs-decision protocol (github-issue-triage's
references/needs-decision.md): mention @romamo, label the item needs-decision, and leave it.
