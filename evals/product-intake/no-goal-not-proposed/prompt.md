---
name: no-goal-not-proposed
tags: [product-intake]
runs: 3
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Write, Glob, Grep, Skill]
---

Run product intake on shipmill/shipmill: group the new feature requests into opportunity
issues and report what waits for the maintainer. This checkout is shipmill itself, so its
CLI runs as `uv run shipmill`.

Headless: nobody is attached to this session. Do not ask questions; a decision that is the
maintainer's goes in the report.
