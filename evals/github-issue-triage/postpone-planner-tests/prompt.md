---
name: postpone-planner-tests
tags: [github-issue-triage]
runs: 3
max_turns: 30
timeout_seconds: 900
allowed_tools: [Bash, Read, Write, Glob, Grep, Skill]
---

/shipmill:github-issue-triage shipmill/shipmill triage the open issues; verdicts only, don't implement in this pass

This checkout is shipmill itself at the commit the pass ran on, so its CLI runs as
`uv run shipmill`; its `.github/shipmill.toml` sets `[agents] app_id`, and the App writes as
shipmill-romamo[bot]. The take-stock step already ran, and this is what it printed:

```
$ uv run --no-project python skills/github-issue-triage/scripts/triage_state.py shipmill/shipmill --closed 40 --bot-login 'shipmill-romamo[bot]' --trusted-only
#836   NEW              Test release rules at the planner instead of through real git
```

#836 was opened by shipmill-romamo[bot], the App, from an agent's test audit; its
`author_association` is CONTRIBUTOR. Product intake's state was read too:
`intake_state.py shipmill/shipmill` lists no opportunity whose outcome is #836's. There is no
other open issue to act on and no open pull request.

This case is offline: GitHub holds one recording, the issue itself, read with
`gh issue view 836 -R shipmill/shipmill --json title,body,comments,labels,state`. Don't run
`triage_state.py`, `intake_state.py`, or any other `gh` or `shipmill gh` read; what else you
need is above and in this checkout. Act on the take-stock output as the skill says, writing
through `shipmill gh` as the App, then end with your report.

Headless: nobody can answer AskUserQuestion or a permission prompt. A decision for the user,
or a tool call that was denied, becomes the needs-decision protocol (github-issue-triage's
references/needs-decision.md): mention @romamo, label the item needs-decision, and leave it.
