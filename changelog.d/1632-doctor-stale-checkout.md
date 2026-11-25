### Fixed

- `shipmill doctor` says when the checkout it reads is behind origin's default branch: a new `checkout` row, after the policy row and before the rows read from the working tree, WARNs with the branch or detached HEAD, how many commits it is behind `origin/<default>`, and the fix, since the workflows, `.github/shipmill.toml`, and `pyproject.toml` rows describe that older commit (#1632)
