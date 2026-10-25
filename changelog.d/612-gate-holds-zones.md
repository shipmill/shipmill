### Added

- In a repo whose default branch's config has `[agents]`, `pr_gate.py` reads a pull request's zones with `shipmill decide classify`: a `never` zone is the new `MAINTAINER_ONLY` verdict, exit 7, which `--maintainer-accepted` doesn't lift; an `ask` zone waits on the maintainer with exit 5; a `notify` zone keeps the verdict and prints a `notify:` line; and `shipmill gh pr merge` or a `shipmill gh api -X PUT .../pulls/<n>/merge`, as the App, exits 2 for a pull request with a `never` zone, since only the maintainer merges it, by hand (#612)
