### Changed

- `pr_gate.py`'s verdict line prints the pull request's full 40-character head in `head=`, the head it judged, instead of its first seven characters, so the lander passes it to `shipmill gh pr merge --match-head-commit` as it is, which refuses a short SHA, instead of reading the head again or guessing the rest of it (#1017)
