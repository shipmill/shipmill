### Fixed

- In a headless gate session the delivery hook's uv-run rule also refuses a `test_proof.py` call whose command after `--` runs a program the headless allowlist doesn't (`gh`, `git`, `uv`, `uvx`, as written), so `-- sh -c ls`, `-- env X=1 uv run pytest`, and `-- npm test` no longer start a program past the allowlist; `-- uv run pytest tests/test_a.py` and `-- git status` still pass, and an interactive session is unchanged (S-076-11) (#1406)
