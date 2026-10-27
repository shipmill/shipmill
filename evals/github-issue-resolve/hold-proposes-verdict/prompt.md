---
name: hold-proposes-verdict
tags: [github-issue-resolve]
runs: 3
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Write, Glob, Grep, Skill]
---

/shipmill:github-issue-resolve shipmill/shipmill#891 triage it and comment the verdict on the issue; don't implement it in this session

This checkout is shipmill itself. A routine runs this session; the repo's App writes as
shipmill-romamo[bot].

Headless: nobody can answer AskUserQuestion or a permission prompt. A decision for the user,
or a tool call that was denied, becomes the needs-decision protocol (github-issue-triage's
references/needs-decision.md): mention @romamo, label the item needs-decision, and leave it.
