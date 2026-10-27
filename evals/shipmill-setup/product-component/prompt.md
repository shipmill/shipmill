---
name: product-component
tags: [shipmill-setup]
runs: 3
max_turns: 30
timeout_seconds: 900
allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, Skill]
---

connect acme/api and acme/web to acme/product as one product

This checkout stands for acme/api (`gh repo view --json nameWithOwner` answers it). Its
`.github/shipmill.toml` is acme/api's config: lanes and `[agents]`, `app_id` included, are
already set up and merged, and it has no `[product]` table. The setup checklist already
ran here: its Product row read `PRODUCT_SIBLINGS acme/web, acme/product set app_id 5209412
too`. The maintainer's request above answers the Product question: acme/product is the
home, and acme/api and acme/web are its components. The App is installed on all three.

This case is offline: GitHub holds no recording for acme/web or acme/product, so don't
read them, and don't run `setup_state.py` or `doctor` again. Make the config change in this
checkout and stop before any commit, push, or pull request; end with your report.

Headless: nobody can answer AskUserQuestion or a permission prompt. A decision for the user,
or a tool call that was denied, goes in your report.
