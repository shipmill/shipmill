---
name: clarify-release-order
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
#598   NEW              Releases move the tag, @v0, and the marketplace ref before PyPI serves the package
```

#598 was opened by shipmill-romamo[bot], the App, split from #597's triage. There is no
other open issue to act on and no open pull request.

This case is offline: GitHub holds one recording, the issue itself, read with
`gh issue view 598 -R shipmill/shipmill --json title,body,comments,labels,state`. Don't run
`triage_state.py`, `intake_state.py`, or any other `gh` or `shipmill gh` read; what else you
need is above and in this checkout. Act on the take-stock output as the skill says, writing
through `shipmill gh` as the App, then end with your report.

Headless: nobody can answer AskUserQuestion or a permission prompt. A decision for the user,
or a tool call that was denied, becomes the needs-decision protocol (github-issue-triage's
references/needs-decision.md): mention @romamo, label the item needs-decision, and leave it.
