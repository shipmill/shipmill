---
name: person-report-code-span
tags: [github-issue-triage]
runs: 3
max_turns: 30
timeout_seconds: 900
allowed_tools: [Bash, Read, Write, Glob, Grep, Skill]
---

/shipmill:github-issue-triage acme/ops triage the open issues

This checkout stands for acme/ops: its `.github/shipmill.toml` sets `[agents] app_id`, and the
App writes as shipmill-acme[bot]. The take-stock step already ran, and this is what it printed:

```
$ uv run --no-project python skills/github-issue-triage/scripts/triage_state.py acme/ops --closed 40 --bot-login 'shipmill-acme[bot]' --trusted-only
#12    VERIFY_DUE       Add the DNS record for status.acme.dev
```

acme/ops#12 is a person's item, labelled `role:infra` and assigned to amy; its body has the
steps and no `## Check` section. shipmill-acme[bot] posted its hand-off to `@amy`, and amy
(a COLLABORATOR) replied after it: "done, the record is live". There is no other open issue
and no open pull request.

This case is offline: GitHub holds no recording for any read here, so don't run
`triage_state.py` or any `gh` or `shipmill gh` read; what you need is above. Act on the
take-stock output as the skill says, writing through `shipmill gh` as the App, then end with
your report.

Headless: nobody can answer AskUserQuestion or a permission prompt. A decision for the user,
or a tool call that was denied, goes in your report.
