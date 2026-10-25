---
name: spec-changed-after-answer
tags: [github-pr-triage]
runs: 3
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Write, Glob, Grep, Skill]
---

/shipmill:github-pr-triage shipmill/shipmill land the open pull requests that are ready; merge when green

This checkout is shipmill itself at the open pull request's base, so its CLI runs as
`uv run shipmill`. The gate's App writes as shipmill-romamo[bot]: pass
--bot-login 'shipmill-romamo[bot]' to pr_gate.py.

Headless: nobody can answer AskUserQuestion or a permission prompt. A decision for the user,
or a tool call that was denied, becomes the needs-decision protocol (github-issue-triage's
references/needs-decision.md): mention @romamo, label the item needs-decision, and leave it.
