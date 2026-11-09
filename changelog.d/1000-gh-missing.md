### Fixed

- On a runner without GitHub's CLI, `plan`, `prepare`, `land`, `operate`, and every other command that reads GitHub exit 2 with `gh not found on PATH; install GitHub's CLI, https://cli.github.com` instead of a `FileNotFoundError` traceback, and the self-hosted runner docs list `gh` (#1000)
