### Fixed

- A deploy proposal from `operate.yml` reaches the maintainer queue: given the App's private key as its new optional `SHIPMILL_OPERATE_KEY` secret, with `[agents] app_id` set, operate opens and updates the "Ready to promote" issue as the App, with a token limited to the repository and `issues: write`, instead of as `github-actions[bot]`, which the queue leaves out; without the secret nothing changes (#1371)
