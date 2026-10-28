---
name: component-home-hold-asks-nobody
tags: [github-issue-triage]
runs: 3
max_turns: 30
timeout_seconds: 900
allowed_tools: [Bash, Read, Glob, Grep, Skill]
---

/shipmill:github-issue-triage acme/api triage the open issues

This checkout stands for acme/api, a component of the product whose home is acme/product:
its `.github/shipmill.toml` sets `[product] home = "acme/product"` and `[agents] app_id`, and
the App writes as shipmill-acme[bot]. The take-stock step already ran, and this is what it
printed:

```
$ uv run --no-project python skills/github-issue-triage/scripts/triage_state.py acme/api --closed 40 --bot-login 'shipmill-acme[bot]' --trusted-only --home acme/product
#3     BLOCKED          Add the export endpoint (part of acme/product#10)  [acme/product#11:unknown | the coordinator's hold on the home acme/product: waits for the coordinator, ask nobody]
```

acme/api#3 was filed by the coordinator, shipmill-acme[bot], and its triage comment reads
"Triage: implement. On hold until acme/product#11 merges." acme/product#11 is the home's spec
pull request for the feature. Neither this session's `gh` nor the App can read acme/product:
both get a 404. There is no other open issue and no open pull request.

This case is offline: GitHub holds no recording for any read here, so don't run
`triage_state.py`, `gh`, or `shipmill gh` reads again; what you need is above. Act on the
take-stock output as the skill says, then end with your report.

Headless: nobody can answer AskUserQuestion or a permission prompt. A decision for the user,
or a tool call that was denied, becomes the needs-decision protocol (references/needs-decision.md):
mention the maintainer, label the item needs-decision, and leave it.
