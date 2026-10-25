### Added

- In a repo whose default branch's config has `[agents]`, `pr_gate.py` reads a pull request's zones with `shipmill decide classify`: a `never` zone is the new `MAINTAINER_ONLY` verdict, exit 7, which `--maintainer-accepted` doesn't lift; an `ask` zone waits on the maintainer with exit 5; a `notify` zone keeps the verdict and prints a `notify:` line; and `shipmill gh pr merge` or a `shipmill gh api -X PUT .../pulls/<n>/merge`, as the App, exits 2 for a pull request with a `never` zone, since only the maintainer merges it, by hand (#612)

### Changed

- In a repo whose default branch's config has `[agents]`, an agent's pull request that edits `docs/product.md` or `docs/product/` is `MAINTAINER_ONLY` (`pr_gate.py` exit 7) instead of `NEEDS_DECISION` (set `direction = "ask"` under `[decisions]` for the old behaviour), and a pull request in the `security` (`.github/**`), `scope` (a spec whose status becomes `approved`), or `contract-change` (an entry under a `[bump] major` heading) zone exits 5 until `--maintainer-accepted` (#612)
