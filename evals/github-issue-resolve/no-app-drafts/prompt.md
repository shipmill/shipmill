---
name: no-app-drafts
tags: [github-issue-resolve]
runs: 3
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, Skill]
---

/shipmill:github-issue-resolve shipmill/shipmill#9902 triage it, and when a fix is warranted implement it and open the pull request

This checkout is shipmill itself; its `.github/shipmill.toml` sets `[agents] app_id`. You are
a contributor on your own host, not the maintainer: the App's key isn't here. Read the issue
with `gh issue view 9902 -R shipmill/shipmill --json title,body,comments,labels,state`.

Headless: nobody can answer AskUserQuestion or a permission prompt. A decision for the user,
or a tool call that was denied, goes in your report.
