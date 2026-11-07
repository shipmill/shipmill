---
name: finding-spec-answer-stale
tags: [github-pr-triage]
runs: 3
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Write, Glob, Grep, Skill]
---

/shipmill:github-pr-triage shipmill/shipmill post-merge review of #606, which merged before anyone reviewed it; review only

This checkout is shipmill itself at #606's squash commit (HEAD), so its CLI runs as
`uv run shipmill`; its `.github/shipmill.toml` sets `[agents] app_id`, and the App writes as
shipmill-romamo[bot]. What #606 landed is `git diff HEAD^ HEAD`, where `HEAD^` is main just
before it.

#606, "Land a spec PR on a trusted answer that takes every recommendation (D-49)", builds
D-49 (#547): a spec pull request is approved by the maintainer's merge or by a trusted answer
to its needs-decision question that takes every recommendation unchanged, after which
github-pr-triage lands it once it is mergeable and green. It changes the skills' prose
(`spec-gate.md`, `comments.md`, `needs-decision.md`, github-issue-triage's and
github-pr-triage's `SKILL.md`), `docs/design/product-layer.md`, two eval cases, and tests.

This case is offline: GitHub holds no recording, so don't run `gh` or `shipmill gh` reads
(`pr view`, `pr diff`, `api`); what you need is above and in this checkout. No reviewer agent
is available here: review the change in this session, then end with your report, the
verdict and each finding with its file and line.

Headless: nobody can answer AskUserQuestion or a permission prompt. A decision for the user,
or a tool call that was denied, goes in your report.
